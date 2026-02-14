/**
 * dirwalk.h — Recursive directory traversal and comparison.
 *
 * Produces a sorted list of relative paths for all regular files.
 */

#ifndef KOMPARU_DIRWALK_H
#define KOMPARU_DIRWALK_H

#include "compat.h"

/* Forward declaration */
struct komparu_dir_result;
typedef struct komparu_dir_result komparu_dir_result_t;

/**
 * Directory entry list — dynamic array of relative paths.
 */
typedef struct {
    char **paths;       /* Array of malloc'd path strings */
    size_t count;       /* Number of entries */
    size_t capacity;    /* Allocated capacity */
} komparu_pathlist_t;

/**
 * Walk a directory recursively and collect all regular file paths.
 *
 * base_dir: root directory to walk.
 * follow_symlinks: if true, follow symbolic links.
 * result: output path list (caller must free with komparu_pathlist_free).
 *
 * Returns 0 on success, -1 on error.
 */
int komparu_dirwalk(
    const char *base_dir,
    bool follow_symlinks,
    komparu_pathlist_t *result,
    const char **err_msg
);

/**
 * Free a path list and all its strings.
 */
void komparu_pathlist_free(komparu_pathlist_t *list);

/**
 * Compare two directories recursively.
 *
 * Walks both directories, merge-compares sorted path lists,
 * opens file readers and uses komparu_compare for each common entry.
 *
 * Returns allocated dir_result_t on success, NULL on error.
 * Caller must free with komparu_dir_result_free().
 */
komparu_dir_result_t *komparu_compare_dirs(
    const char *dir_a,
    const char *dir_b,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    bool follow_symlinks,
    const char **err_msg
);

#endif /* KOMPARU_DIRWALK_H */
