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
 * Recursive walker — uses fd-relative operations for performance
 * ========================================================================= */

static int walk_recursive(
    int parent_fd,          /* consumed — fdopendir takes ownership */
    const char *rel_prefix, /* "" for root */
    int stat_flags,
    komparu_pathlist_t *result,
    const char **err_msg
) {
    DIR *dir = fdopendir(parent_fd);
    if (KOMPARU_UNLIKELY(!dir)) {
        close(parent_fd);
        strerror_r(errno, dirwalk_errbuf, sizeof(dirwalk_errbuf));
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
        if (KOMPARU_UNLIKELY(fstatat(dfd, name, &st, stat_flags) != 0))
            continue;

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
            if (KOMPARU_UNLIKELY(sub_fd < 0)) continue;

            if (KOMPARU_UNLIKELY(walk_recursive(sub_fd, rel_path, stat_flags, result, err_msg) != 0)) {
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
    const char **err_msg
) {
    memset(result, 0, sizeof(*result));

    int fd = open(base_dir, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (KOMPARU_UNLIKELY(fd < 0)) {
        strerror_r(errno, dirwalk_errbuf, sizeof(dirwalk_errbuf));
        *err_msg = dirwalk_errbuf;
        return -1;
    }

    int stat_flags = follow_symlinks ? 0 : AT_SYMLINK_NOFOLLOW;

    if (KOMPARU_UNLIKELY(walk_recursive(fd, "", stat_flags, result, err_msg) != 0)) {
        komparu_pathlist_free(result);
        return -1;
    }

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
    komparu_pathlist_t paths_a = {0};
    komparu_pathlist_t paths_b = {0};

    if (komparu_dirwalk(dir_a, follow_symlinks, &paths_a, err_msg) != 0) {
        return NULL;
    }

    if (komparu_dirwalk(dir_b, follow_symlinks, &paths_b, err_msg) != 0) {
        komparu_pathlist_free(&paths_a);
        return NULL;
    }

    komparu_dir_result_t *result = komparu_dir_result_new();
    if (KOMPARU_UNLIKELY(!result)) {
        *err_msg = "out of memory";
        komparu_pathlist_free(&paths_a);
        komparu_pathlist_free(&paths_b);
        return NULL;
    }

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
                    komparu_pool_wait(pool);
                    komparu_pool_destroy(pool);
                    for (size_t m = k; m < task_count; m++)
                        dir_cmp_task_exec(&tasks[m]);
                    pool = NULL;
                    break;
                }
            }
            komparu_pool_wait(pool);
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
