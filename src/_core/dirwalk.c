/**
 * dirwalk.c — Recursive directory traversal and comparison.
 *
 * Uses openat/fstatat/fdopendir for optimal performance (avoids
 * full path resolution on each stat). Produces sorted pathlist
 * for deterministic merge-comparison.
 */

#include "dirwalk.h"
#include "compare.h"
#include "reader_file.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <limits.h>

static _Thread_local char dirwalk_errbuf[512];

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
    list->paths[list->count] = strdup(path);
    if (KOMPARU_UNLIKELY(!list->paths[list->count])) {
        *err_msg = "out of memory";
        return -1;
    }
    list->count++;
    return 0;
}

static int path_cmp(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

void komparu_pathlist_free(komparu_pathlist_t *list) {
    if (!list) return;
    for (size_t i = 0; i < list->count; i++)
        free(list->paths[i]);
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
        if (rel_prefix[0]) {
            snprintf(rel_path, sizeof(rel_path), "%s/%s", rel_prefix, name);
        } else {
            snprintf(rel_path, sizeof(rel_path), "%s", name);
        }

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
 * Directory comparison — sorted merge of two directory trees
 * ========================================================================= */

komparu_dir_result_t *komparu_compare_dirs(
    const char *dir_a,
    const char *dir_b,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    bool follow_symlinks,
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

    /* Sorted merge */
    size_t i = 0, j = 0;
    while (i < paths_a.count && j < paths_b.count) {
        int cmp = strcmp(paths_a.paths[i], paths_b.paths[j]);

        if (cmp < 0) {
            /* Only in dir_a */
            if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_left(result, paths_a.paths[i]) != 0)) {
                *err_msg = "out of memory";
                goto fail;
            }
            i++;
        } else if (cmp > 0) {
            /* Only in dir_b */
            if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_right(result, paths_b.paths[j]) != 0)) {
                *err_msg = "out of memory";
                goto fail;
            }
            j++;
        } else {
            /* Same relative path — compare files */
            char path_a[PATH_MAX], path_b[PATH_MAX];
            snprintf(path_a, sizeof(path_a), "%s/%s", dir_a, paths_a.paths[i]);
            snprintf(path_b, sizeof(path_b), "%s/%s", dir_b, paths_b.paths[j]);

            const char *cmp_err = NULL;
            komparu_reader_t *ra = komparu_reader_file_open(path_a, &cmp_err);
            if (KOMPARU_UNLIKELY(!ra)) {
                komparu_dir_result_add_diff(result, paths_a.paths[i], KOMPARU_DIFF_READ_ERROR);
                i++; j++;
                continue;
            }

            komparu_reader_t *rb = komparu_reader_file_open(path_b, &cmp_err);
            if (KOMPARU_UNLIKELY(!rb)) {
                ra->close(ra);
                komparu_dir_result_add_diff(result, paths_a.paths[i], KOMPARU_DIFF_READ_ERROR);
                i++; j++;
                continue;
            }

            /* Size pre-check fast path */
            if (size_precheck) {
                int64_t sa = ra->get_size(ra);
                int64_t sb = rb->get_size(rb);
                if (sa >= 0 && sb >= 0 && sa != sb) {
                    ra->close(ra);
                    rb->close(rb);
                    komparu_dir_result_add_diff(result, paths_a.paths[i], KOMPARU_DIFF_SIZE);
                    i++; j++;
                    continue;
                }
            }

            /* Quick check */
            if (quick_check) {
                komparu_result_t qr = komparu_quick_check(ra, rb, chunk_size, &cmp_err);
                if (qr == KOMPARU_DIFFERENT) {
                    ra->close(ra);
                    rb->close(rb);
                    komparu_dir_result_add_diff(result, paths_a.paths[i], KOMPARU_DIFF_CONTENT);
                    i++; j++;
                    continue;
                }
                /* EQUAL from quick_check → still need full compare */
                /* ERROR → fall through to full compare */
            }

            komparu_result_t cr = komparu_compare(ra, rb, chunk_size, false, &cmp_err);
            ra->close(ra);
            rb->close(rb);

            if (cr == KOMPARU_DIFFERENT) {
                komparu_dir_result_add_diff(result, paths_a.paths[i], KOMPARU_DIFF_CONTENT);
            } else if (cr == KOMPARU_ERROR) {
                komparu_dir_result_add_diff(result, paths_a.paths[i], KOMPARU_DIFF_READ_ERROR);
            }

            i++; j++;
        }
    }

    /* Remaining entries in dir_a only */
    while (i < paths_a.count) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_left(result, paths_a.paths[i]) != 0)) {
            *err_msg = "out of memory";
            goto fail;
        }
        i++;
    }

    /* Remaining entries in dir_b only */
    while (j < paths_b.count) {
        if (KOMPARU_UNLIKELY(komparu_dir_result_add_only_right(result, paths_b.paths[j]) != 0)) {
            *err_msg = "out of memory";
            goto fail;
        }
        j++;
    }

    komparu_pathlist_free(&paths_a);
    komparu_pathlist_free(&paths_b);
    return result;

fail:
    komparu_pathlist_free(&paths_a);
    komparu_pathlist_free(&paths_b);
    komparu_dir_result_free(result);
    return NULL;
}
