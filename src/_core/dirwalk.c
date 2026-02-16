/**
 * dirwalk.c — Recursive directory traversal and comparison.
 *
 * Uses openat/fstatat/fdopendir for optimal performance (avoids
 * full path resolution on each stat). Produces sorted pathlist
 * for deterministic merge-comparison.
 *
 * Parallel mode: when max_workers > 1, file comparisons are
 * submitted to a thread pool. Each task is independent (own readers).
 */

#include "dirwalk.h"
#include "compare.h"
#include "reader_file.h"
#include "reader_http.h"
#include "pool.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <limits.h>

static _Thread_local char dirwalk_errbuf[512];

/* =========================================================================
 * Arena allocator — contiguous string storage in 64KB blocks
 * ========================================================================= */

#define ARENA_BLOCK_SIZE (64 * 1024)  /* 64KB blocks */

static komparu_arena_block_t *arena_block_new(size_t min_size) {
    size_t cap = min_size > ARENA_BLOCK_SIZE ? min_size : ARENA_BLOCK_SIZE;
    komparu_arena_block_t *b = malloc(sizeof(*b) + cap);
    if (KOMPARU_UNLIKELY(!b)) return NULL;
    b->next = NULL;
    b->used = 0;
    b->capacity = cap;
    return b;
}

static char *arena_strdup(komparu_arena_t *arena, const char *s, size_t len) {
    /* len must include the NUL terminator */
    komparu_arena_block_t *blk = arena->current;
    if (!blk || blk->used + len > blk->capacity) {
        komparu_arena_block_t *nb = arena_block_new(len);
        if (KOMPARU_UNLIKELY(!nb)) return NULL;
        if (blk) blk->next = nb;
        else arena->head = nb;
        arena->current = nb;
        blk = nb;
    }
    char *dst = blk->data + blk->used;
    memcpy(dst, s, len);
    blk->used += len;
    return dst;
}

static void arena_free(komparu_arena_t *arena) {
    komparu_arena_block_t *b = arena->head;
    while (b) {
        komparu_arena_block_t *next = b->next;
        free(b);
        b = next;
    }
    arena->head = NULL;
    arena->current = NULL;
}

/* =========================================================================
 * Pathlist helpers
 * ========================================================================= */

static int pathlist_append(komparu_pathlist_t *list, const char *path, const char **err_msg) {
    if (list->count >= list->capacity) {
        size_t new_cap = list->capacity ? list->capacity * 2 : 256;
        char **tmp = realloc(list->paths, new_cap * sizeof(char *));
        if (KOMPARU_UNLIKELY(!tmp)) {
            *err_msg = "out of memory";
            return -1;
        }
        list->paths = tmp;
        list->capacity = new_cap;
    }
    size_t len = strlen(path) + 1;
    char *copy = arena_strdup(&list->arena, path, len);
    if (KOMPARU_UNLIKELY(!copy)) {
        *err_msg = "out of memory";
        return -1;
    }
    list->paths[list->count] = copy;
    list->count++;
    return 0;
}

static int path_cmp(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

void komparu_pathlist_free(komparu_pathlist_t *list) {
    if (!list) return;
    arena_free(&list->arena);
    free(list->paths);
    list->paths = NULL;
    list->count = 0;
    list->capacity = 0;
}

/* =========================================================================
 * Visited-directory set — (dev, ino) hash set for symlink loop detection
 * ========================================================================= */

typedef struct {
    dev_t dev;
    ino_t ino;
} devino_t;

typedef struct {
    devino_t *slots;    /* open-addressing table */
    size_t    capacity; /* always a power of 2 */
    size_t    count;    /* number of occupied slots */
} devino_set_t;

#define DEVINO_SET_INIT_CAP 64  /* handles typical trees without rehash */

static int devino_set_init(devino_set_t *set) {
    set->slots = calloc(DEVINO_SET_INIT_CAP, sizeof(devino_t));
    if (KOMPARU_UNLIKELY(!set->slots)) return -1;
    set->capacity = DEVINO_SET_INIT_CAP;
    set->count = 0;
    return 0;
}

static void devino_set_free(devino_set_t *set) {
    free(set->slots);
    set->slots = NULL;
    set->capacity = 0;
    set->count = 0;
}

static inline uint64_t devino_hash(dev_t dev, ino_t ino) {
    /* Mix dev and ino — splitmix64-style finalizer */
    uint64_t h = (uint64_t)dev * 0x9E3779B97F4A7C15ULL ^ (uint64_t)ino;
    h = (h ^ (h >> 30)) * 0xBF58476D1CE4E5B9ULL;
    h = (h ^ (h >> 27)) * 0x94D049BB133111EBULL;
    return h ^ (h >> 31);
}

/* Insert into table (no duplicate check, used during rehash). */
static void devino_set_insert_raw(devino_t *slots, size_t mask,
                                  dev_t dev, ino_t ino) {
    size_t idx = devino_hash(dev, ino) & mask;
    while (slots[idx].dev != 0 || slots[idx].ino != 0)
        idx = (idx + 1) & mask;
    slots[idx].dev = dev;
    slots[idx].ino = ino;
}

static int devino_set_grow(devino_set_t *set) {
    size_t new_cap = set->capacity * 2;
    devino_t *new_slots = calloc(new_cap, sizeof(devino_t));
    if (KOMPARU_UNLIKELY(!new_slots)) return -1;
    size_t new_mask = new_cap - 1;
    for (size_t i = 0; i < set->capacity; i++) {
        if (set->slots[i].dev != 0 || set->slots[i].ino != 0)
            devino_set_insert_raw(new_slots, new_mask,
                                  set->slots[i].dev, set->slots[i].ino);
    }
    free(set->slots);
    set->slots = new_slots;
    set->capacity = new_cap;
    return 0;
}

/**
 * Check if (dev, ino) is already in the set.
 * If not, insert it.
 * Returns: true if already present (loop detected), false if newly inserted.
 * Returns -1 on allocation failure.
 */
static int devino_set_check_and_add(devino_set_t *set, dev_t dev, ino_t ino) {
    size_t mask = set->capacity - 1;
    size_t idx = devino_hash(dev, ino) & mask;
    while (set->slots[idx].dev != 0 || set->slots[idx].ino != 0) {
        if (set->slots[idx].dev == dev && set->slots[idx].ino == ino)
            return 1;  /* already visited — loop */
        idx = (idx + 1) & mask;
    }
    /* Not found — insert */
    /* Grow at 75% load factor */
    if (set->count * 4 >= set->capacity * 3) {
        if (KOMPARU_UNLIKELY(devino_set_grow(set) != 0))
            return -1;
        /* Recompute insertion point after rehash */
        mask = set->capacity - 1;
        idx = devino_hash(dev, ino) & mask;
        while (set->slots[idx].dev != 0 || set->slots[idx].ino != 0)
            idx = (idx + 1) & mask;
    }
    set->slots[idx].dev = dev;
    set->slots[idx].ino = ino;
    set->count++;
    return 0;  /* newly inserted */
}

/* =========================================================================
 * Recursive walker — uses fd-relative operations for performance
 * ========================================================================= */

/* Guard against pathological directory depth (symlink cycles with
 * follow_symlinks=true, or genuinely deep trees). 256 levels of nesting
 * covers any real-world use case while preventing stack overflow. */
#define KOMPARU_MAX_WALK_DEPTH 256

static int walk_recursive(
    int parent_fd,          /* consumed — fdopendir takes ownership */
    const char *rel_prefix, /* "" for root */
    int stat_flags,
    int depth,
    devino_set_t *visited,  /* tracks visited directories for loop detection */
    komparu_pathlist_t *result,
    komparu_pathlist_t *errors,  /* NULL = ignore permission errors */
    const char **err_msg
) {
    if (KOMPARU_UNLIKELY(depth > KOMPARU_MAX_WALK_DEPTH)) {
        close(parent_fd);
        *err_msg = "directory tree too deep (>256 levels)";
        return -1;
    }
    DIR *dir = fdopendir(parent_fd);
    if (KOMPARU_UNLIKELY(!dir)) {
        close(parent_fd);
        komparu_strerror(errno, dirwalk_errbuf, sizeof(dirwalk_errbuf));
        *err_msg = dirwalk_errbuf;
        return -1;
    }
    /* dir now owns parent_fd */

    int dfd = dirfd(dir);
    struct dirent *entry;

    while ((entry = readdir(dir)) != NULL) {
        /* Skip . and .. */
        const char *name = entry->d_name;
        if (name[0] == '.') {
            if (name[1] == '\0') continue;
            if (name[1] == '.' && name[2] == '\0') continue;
        }

        struct stat st;
        if (KOMPARU_UNLIKELY(fstatat(dfd, name, &st, stat_flags) != 0)) {
            if (errors && (errno == EACCES || errno == EPERM)) {
                /* Build relative path for the error entry */
                char err_path[PATH_MAX];
                int elen;
                if (rel_prefix[0]) {
                    elen = snprintf(err_path, sizeof(err_path), "%s/%s", rel_prefix, name);
                } else {
                    elen = snprintf(err_path, sizeof(err_path), "%s", name);
                }
                if (elen >= 0 && (size_t)elen < sizeof(err_path)) {
                    if (KOMPARU_UNLIKELY(pathlist_append(errors, err_path, err_msg) != 0)) {
                        closedir(dir);
                        return -1;
                    }
                }
            }
            continue;
        }

        /* Build relative path */
        char rel_path[PATH_MAX];
        int plen;
        if (rel_prefix[0]) {
            plen = snprintf(rel_path, sizeof(rel_path), "%s/%s", rel_prefix, name);
        } else {
            plen = snprintf(rel_path, sizeof(rel_path), "%s", name);
        }
        if (KOMPARU_UNLIKELY(plen < 0 || (size_t)plen >= sizeof(rel_path)))
            continue; /* path too long — skip */

        if (S_ISREG(st.st_mode)) {
            if (KOMPARU_UNLIKELY(pathlist_append(result, rel_path, err_msg) != 0)) {
                closedir(dir);
                return -1;
            }
        } else if (S_ISDIR(st.st_mode)) {
            int sub_fd = openat(dfd, name, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
            if (KOMPARU_UNLIKELY(sub_fd < 0)) {
                if (errors && (errno == EACCES || errno == EPERM)) {
                    if (KOMPARU_UNLIKELY(pathlist_append(errors, rel_path, err_msg) != 0)) {
                        closedir(dir);
                        return -1;
                    }
                }
                continue;
            }

            /* Symlink loop detection: check (dev, ino) of this directory */
            struct stat dir_st;
            if (KOMPARU_UNLIKELY(fstat(sub_fd, &dir_st) != 0)) {
                close(sub_fd);
                continue;
            }
            int vis = devino_set_check_and_add(visited, dir_st.st_dev, dir_st.st_ino);
            if (vis == 1) {
                /* Already visited — symlink loop, skip silently */
                close(sub_fd);
                continue;
            }
            if (KOMPARU_UNLIKELY(vis < 0)) {
                close(sub_fd);
                closedir(dir);
                *err_msg = "out of memory";
                return -1;
            }

            if (KOMPARU_UNLIKELY(walk_recursive(sub_fd, rel_path, stat_flags, depth + 1, visited, result, errors, err_msg) != 0)) {
                closedir(dir);
                return -1;
            }
        }
    }

    closedir(dir);
    return 0;
}

int komparu_dirwalk(
    const char *base_dir,
    bool follow_symlinks,
    komparu_pathlist_t *result,
    komparu_pathlist_t *errors,
    const char **err_msg
) {
    memset(result, 0, sizeof(*result));
    if (errors) memset(errors, 0, sizeof(*errors));

    int fd = open(base_dir, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (KOMPARU_UNLIKELY(fd < 0)) {
        komparu_strerror(errno, dirwalk_errbuf, sizeof(dirwalk_errbuf));
        *err_msg = dirwalk_errbuf;
        return -1;
    }

    /* Initialize visited set for symlink loop detection */
    devino_set_t visited;
    if (KOMPARU_UNLIKELY(devino_set_init(&visited) != 0)) {
        close(fd);
        *err_msg = "out of memory";
        return -1;
    }

    /* Register the root directory so we detect cycles back to it */
    struct stat root_st;
    if (KOMPARU_UNLIKELY(fstat(fd, &root_st) != 0)) {
        komparu_strerror(errno, dirwalk_errbuf, sizeof(dirwalk_errbuf));
        *err_msg = dirwalk_errbuf;
        devino_set_free(&visited);
        close(fd);
        return -1;
    }
    devino_set_check_and_add(&visited, root_st.st_dev, root_st.st_ino);

    int stat_flags = follow_symlinks ? 0 : AT_SYMLINK_NOFOLLOW;

    if (KOMPARU_UNLIKELY(walk_recursive(fd, "", stat_flags, 0, &visited, result, errors, err_msg) != 0)) {
        devino_set_free(&visited);
        komparu_pathlist_free(result);
        if (errors) komparu_pathlist_free(errors);
        return -1;
    }

    devino_set_free(&visited);

    /* Sort for deterministic merge comparison */
    if (result->count > 1) {
        qsort(result->paths, result->count, sizeof(char *), path_cmp);
    }

    return 0;
}

/* =========================================================================
 * Per-file comparison task (used by both sequential and parallel paths)
 * ========================================================================= */

typedef struct {
    char *full_path_a;
    char *full_path_b;
    char *rel_path;
    size_t chunk_size;
    bool size_precheck;
    bool quick_check;
    int result_reason;  /* -1 = equal, else KOMPARU_DIFF_* */
} dir_cmp_task_t;

static void dir_cmp_task_exec(void *arg) {
    dir_cmp_task_t *task = (dir_cmp_task_t *)arg;
    task->result_reason = -1;  /* assume equal */

    /* Same-file short-circuit via inode comparison */
#ifndef KOMPARU_WINDOWS
    {
        struct stat sa, sb;
        if (stat(task->full_path_a, &sa) == 0 &&
            stat(task->full_path_b, &sb) == 0 &&
            sa.st_dev == sb.st_dev && sa.st_ino == sb.st_ino) {
            return;  /* same file — equal */
        }
    }
#endif

    const char *cmp_err = NULL;
    komparu_reader_t *ra = komparu_reader_file_open(task->full_path_a, &cmp_err);
    if (KOMPARU_UNLIKELY(!ra)) {
        task->result_reason = KOMPARU_DIFF_READ_ERROR;
        return;
    }

    komparu_reader_t *rb = komparu_reader_file_open(task->full_path_b, &cmp_err);
    if (KOMPARU_UNLIKELY(!rb)) {
        ra->close(ra);
        task->result_reason = KOMPARU_DIFF_READ_ERROR;
        return;
    }

    /* Size pre-check */
    if (task->size_precheck) {
        int64_t sa = ra->get_size(ra);
        int64_t sb = rb->get_size(rb);
        if (sa >= 0 && sb >= 0 && sa != sb) {
            ra->close(ra);
            rb->close(rb);
            task->result_reason = KOMPARU_DIFF_SIZE;
            return;
        }
    }

    /* Quick check */
    if (task->quick_check) {
        komparu_result_t qr = komparu_quick_check(ra, rb, task->chunk_size, &cmp_err);
        if (qr == KOMPARU_DIFFERENT) {
            ra->close(ra);
            rb->close(rb);
            task->result_reason = KOMPARU_DIFF_CONTENT;
            return;
        }
        if (qr == KOMPARU_ERROR && ra->seek && rb->seek) {
            ra->seek(ra, 0);
            rb->seek(rb, 0);
        }
    }

    komparu_result_t cr = komparu_compare(ra, rb, task->chunk_size, false, &cmp_err);
    ra->close(ra);
    rb->close(rb);

    if (cr == KOMPARU_DIFFERENT)
        task->result_reason = KOMPARU_DIFF_CONTENT;
    else if (cr == KOMPARU_ERROR)
        task->result_reason = KOMPARU_DIFF_READ_ERROR;
}

/* =========================================================================
 * Directory comparison — sorted merge of two directory trees
 * ========================================================================= */

komparu_dir_result_t *komparu_compare_dirs(
    const char *dir_a,
    const char *dir_b,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    bool follow_symlinks,
    size_t max_workers,
    const char **err_msg
) {
    /* Same-directory short-circuit: realpath both, compare strings.
     * Catches identical paths, symlinks, and trailing-slash variants. */
    char real_a[PATH_MAX], real_b[PATH_MAX];
    if (realpath(dir_a, real_a) && realpath(dir_b, real_b) &&
        strcmp(real_a, real_b) == 0) {
        komparu_dir_result_t *r = komparu_dir_result_new();
        if (KOMPARU_UNLIKELY(!r)) {
            *err_msg = "out of memory";
            return NULL;
        }
        return r;  /* equal=true, empty diff/only_left/only_right */
    }

    komparu_pathlist_t paths_a = {0};
    komparu_pathlist_t paths_b = {0};
    komparu_pathlist_t errors_a = {0};
    komparu_pathlist_t errors_b = {0};

    if (komparu_dirwalk(dir_a, follow_symlinks, &paths_a, &errors_a, err_msg) != 0) {
        return NULL;
    }

    if (komparu_dirwalk(dir_b, follow_symlinks, &paths_b, &errors_b, err_msg) != 0) {
        komparu_pathlist_free(&paths_a);
        komparu_pathlist_free(&errors_a);
        return NULL;
    }

    komparu_dir_result_t *result = komparu_dir_result_new();
    if (KOMPARU_UNLIKELY(!result)) {
        *err_msg = "out of memory";
        komparu_pathlist_free(&paths_a);
        komparu_pathlist_free(&paths_b);
        komparu_pathlist_free(&errors_a);
        komparu_pathlist_free(&errors_b);
        return NULL;
    }

    /* Merge permission errors from both walks into the result */
    for (size_t k = 0; k < errors_a.count; k++) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_error(result, errors_a.paths[k]) != 0)) {
            *err_msg = "out of memory";
            komparu_pathlist_free(&paths_a);
            komparu_pathlist_free(&paths_b);
            komparu_pathlist_free(&errors_a);
            komparu_pathlist_free(&errors_b);
            komparu_dir_result_free(result);
            return NULL;
        }
    }
    for (size_t k = 0; k < errors_b.count; k++) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_error(result, errors_b.paths[k]) != 0)) {
            *err_msg = "out of memory";
            komparu_pathlist_free(&paths_a);
            komparu_pathlist_free(&paths_b);
            komparu_pathlist_free(&errors_a);
            komparu_pathlist_free(&errors_b);
            komparu_dir_result_free(result);
            return NULL;
        }
    }
    komparu_pathlist_free(&errors_a);
    komparu_pathlist_free(&errors_b);

    if (chunk_size == 0) chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;

    /* Phase 1: Sorted merge — identify only_left, only_right, common files */
    dir_cmp_task_t *tasks = NULL;
    size_t task_count = 0;
    size_t task_cap = 0;

    size_t i = 0, j = 0;
    while (i < paths_a.count && j < paths_b.count) {
        int cmp = strcmp(paths_a.paths[i], paths_b.paths[j]);

        if (cmp < 0) {
            if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_left(result, paths_a.paths[i]) != 0)) {
                *err_msg = "out of memory";
                goto fail;
            }
            i++;
        } else if (cmp > 0) {
            if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_right(result, paths_b.paths[j]) != 0)) {
                *err_msg = "out of memory";
                goto fail;
            }
            j++;
        } else {
            /* Common entry — build task */
            if (task_count >= task_cap) {
                size_t new_cap = task_cap ? task_cap * 2 : 128;
                dir_cmp_task_t *tmp = realloc(tasks, new_cap * sizeof(dir_cmp_task_t));
                if (KOMPARU_UNLIKELY(!tmp)) {
                    *err_msg = "out of memory";
                    goto fail;
                }
                tasks = tmp;
                task_cap = new_cap;
            }

            dir_cmp_task_t *t = &tasks[task_count];
            memset(t, 0, sizeof(*t));

            /* Build full paths */
            size_t la = strlen(dir_a) + 1 + strlen(paths_a.paths[i]) + 1;
            size_t lb = strlen(dir_b) + 1 + strlen(paths_b.paths[j]) + 1;

            t->full_path_a = malloc(la);
            t->full_path_b = malloc(lb);
            t->rel_path = strdup(paths_a.paths[i]);

            if (KOMPARU_UNLIKELY(!t->full_path_a || !t->full_path_b || !t->rel_path)) {
                free(t->full_path_a);
                free(t->full_path_b);
                free(t->rel_path);
                *err_msg = "out of memory";
                goto fail;
            }

            snprintf(t->full_path_a, la, "%s/%s", dir_a, paths_a.paths[i]);
            snprintf(t->full_path_b, lb, "%s/%s", dir_b, paths_b.paths[j]);
            t->chunk_size = chunk_size;
            t->size_precheck = size_precheck;
            t->quick_check = quick_check;
            t->result_reason = -1;

            task_count++;
            i++; j++;
        }
    }

    while (i < paths_a.count) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_left(result, paths_a.paths[i]) != 0)) {
            *err_msg = "out of memory";
            goto fail;
        }
        i++;
    }

    while (j < paths_b.count) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_right(result, paths_b.paths[j]) != 0)) {
            *err_msg = "out of memory";
            goto fail;
        }
        j++;
    }

    /* Phase 2: Execute file comparisons */
    if (task_count > 0) {
        bool use_pool = (max_workers != 1 && task_count > 1);
        komparu_pool_t *pool = NULL;

        if (use_pool) {
            pool = komparu_pool_create(max_workers);
            /* Fall back to sequential if pool creation fails */
        }

        if (pool) {
            for (size_t k = 0; k < task_count; k++) {
                if (KOMPARU_UNLIKELY(komparu_pool_submit(pool, dir_cmp_task_exec, &tasks[k]) != 0)) {
                    /* Submit failed — execute remaining tasks inline */
                    (void)komparu_pool_wait(pool);
                    komparu_pool_destroy(pool);
                    for (size_t m = k; m < task_count; m++)
                        dir_cmp_task_exec(&tasks[m]);
                    pool = NULL;
                    break;
                }
            }
            (void)komparu_pool_wait(pool);
            komparu_pool_destroy(pool);
        } else {
            for (size_t k = 0; k < task_count; k++) {
                dir_cmp_task_exec(&tasks[k]);
            }
        }

        /* Phase 3: Collect results */
        for (size_t k = 0; k < task_count; k++) {
            if (tasks[k].result_reason >= 0) {
                if (KOMPARU_UNLIKELY(komparu_dir_result_add_diff(result, tasks[k].rel_path, tasks[k].result_reason) != 0)) {
                    *err_msg = "out of memory";
                    goto fail;
                }
            }
        }
    }

    /* Cleanup */
    for (size_t k = 0; k < task_count; k++) {
        free(tasks[k].full_path_a);
        free(tasks[k].full_path_b);
        free(tasks[k].rel_path);
    }
    free(tasks);
    komparu_pathlist_free(&paths_a);
    komparu_pathlist_free(&paths_b);
    return result;

fail:
    for (size_t k = 0; k < task_count; k++) {
        free(tasks[k].full_path_a);
        free(tasks[k].full_path_b);
        free(tasks[k].rel_path);
    }
    free(tasks);
    komparu_pathlist_free(&paths_a);
    komparu_pathlist_free(&paths_b);
    komparu_dir_result_free(result);
    return NULL;
}

/* =========================================================================
 * Directory vs URL map comparison — sorted merge of local tree vs URL set
 * ========================================================================= */

komparu_dir_result_t *komparu_compare_dir_urls(
    const char *dir_path,
    const char **rel_paths,
    const char **urls,
    size_t url_count,
    const char **headers,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    bool allow_private,
    const char *proxy,
    const char **err_msg
) {
    if (chunk_size == 0) chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;

    /* Walk local directory */
    komparu_pathlist_t local_paths = {0};
    komparu_pathlist_t local_errors = {0};
    if (komparu_dirwalk(dir_path, true, &local_paths, &local_errors, err_msg) != 0) {
        return NULL;
    }

    /* Build sorted index over URL rel_paths */
    size_t *url_order = NULL;
    if (url_count > 0) {
        url_order = malloc(url_count * sizeof(size_t));
        if (KOMPARU_UNLIKELY(!url_order)) {
            komparu_pathlist_free(&local_paths);
            komparu_pathlist_free(&local_errors);
            *err_msg = "out of memory";
            return NULL;
        }
        for (size_t k = 0; k < url_count; k++) url_order[k] = k;

        /* Insertion sort by rel_path — url_count is typically small */
        for (size_t k = 1; k < url_count; k++) {
            size_t tmp = url_order[k];
            size_t m = k;
            while (m > 0 && strcmp(rel_paths[url_order[m - 1]],
                                   rel_paths[tmp]) > 0) {
                url_order[m] = url_order[m - 1];
                m--;
            }
            url_order[m] = tmp;
        }
    }

    komparu_dir_result_t *result = komparu_dir_result_new();
    if (KOMPARU_UNLIKELY(!result)) {
        komparu_pathlist_free(&local_paths);
        komparu_pathlist_free(&local_errors);
        free(url_order);
        *err_msg = "out of memory";
        return NULL;
    }

    /* Merge permission errors into result */
    for (size_t k = 0; k < local_errors.count; k++) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_error(result, local_errors.paths[k]) != 0)) {
            komparu_pathlist_free(&local_paths);
            komparu_pathlist_free(&local_errors);
            free(url_order);
            komparu_dir_result_free(result);
            *err_msg = "out of memory";
            return NULL;
        }
    }
    komparu_pathlist_free(&local_errors);

    /* Sorted merge: local_paths (already sorted) vs url_order */
    size_t li = 0, ui = 0;
    while (li < local_paths.count && ui < url_count) {
        size_t uidx = url_order[ui];
        int cmp = strcmp(local_paths.paths[li], rel_paths[uidx]);

        if (cmp < 0) {
            if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_left(
                    result, local_paths.paths[li]) != 0)) {
                *err_msg = "out of memory";
                goto fail;
            }
            li++;
        } else if (cmp > 0) {
            if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_right(
                    result, rel_paths[uidx]) != 0)) {
                *err_msg = "out of memory";
                goto fail;
            }
            ui++;
        } else {
            /* Common entry — compare local file vs URL */
            char full_path[PATH_MAX];
            snprintf(full_path, sizeof(full_path), "%s/%s",
                     dir_path, local_paths.paths[li]);

            const char *open_err = NULL;
            komparu_reader_t *ra = komparu_reader_file_open(full_path, &open_err);
            if (!ra) {
                komparu_dir_result_add_diff(result, local_paths.paths[li],
                                            KOMPARU_DIFF_READ_ERROR);
                li++; ui++;
                continue;
            }

            komparu_reader_t *rb = komparu_reader_http_open_ex(
                urls[uidx], headers,
                timeout, follow_redirects, verify_ssl, allow_private,
                proxy, &open_err);
            if (!rb) {
                ra->close(ra);
                komparu_dir_result_add_diff(result, local_paths.paths[li],
                                            KOMPARU_DIFF_READ_ERROR);
                li++; ui++;
                continue;
            }

            /* Size pre-check */
            if (size_precheck) {
                int64_t sa = ra->get_size(ra);
                int64_t sb = rb->get_size(rb);
                if (sa >= 0 && sb >= 0 && sa != sb) {
                    ra->close(ra);
                    rb->close(rb);
                    komparu_dir_result_add_diff(result, local_paths.paths[li],
                                                KOMPARU_DIFF_SIZE);
                    li++; ui++;
                    continue;
                }
            }

            /* Quick check */
            if (quick_check) {
                const char *qerr = NULL;
                komparu_result_t qr = komparu_quick_check(
                    ra, rb, chunk_size, &qerr);
                if (qr == KOMPARU_DIFFERENT) {
                    ra->close(ra);
                    rb->close(rb);
                    komparu_dir_result_add_diff(result, local_paths.paths[li],
                                                KOMPARU_DIFF_CONTENT);
                    li++; ui++;
                    continue;
                }
                if (qr == KOMPARU_ERROR && ra->seek && rb->seek) {
                    ra->seek(ra, 0);
                    rb->seek(rb, 0);
                }
            }

            /* Full comparison */
            const char *cmp_err = NULL;
            komparu_result_t cr = komparu_compare(
                ra, rb, chunk_size, false, &cmp_err);
            ra->close(ra);
            rb->close(rb);

            if (cr == KOMPARU_DIFFERENT)
                komparu_dir_result_add_diff(result, local_paths.paths[li],
                                            KOMPARU_DIFF_CONTENT);
            else if (cr == KOMPARU_ERROR)
                komparu_dir_result_add_diff(result, local_paths.paths[li],
                                            KOMPARU_DIFF_READ_ERROR);

            li++; ui++;
        }
    }

    while (li < local_paths.count) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_left(
                result, local_paths.paths[li]) != 0)) {
            *err_msg = "out of memory";
            goto fail;
        }
        li++;
    }
    while (ui < url_count) {
        size_t uidx = url_order[ui];
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_right(
                result, rel_paths[uidx]) != 0)) {
            *err_msg = "out of memory";
            goto fail;
        }
        ui++;
    }

    komparu_pathlist_free(&local_paths);
    free(url_order);
    return result;

fail:
    komparu_pathlist_free(&local_paths);
    free(url_order);
    komparu_dir_result_free(result);
    return NULL;
}
