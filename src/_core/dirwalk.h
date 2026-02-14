/**
 * dirwalk.h — Recursive directory traversal.
 *
 * Produces a sorted list of relative paths for all regular files.
 */

#ifndef KOMPARU_DIRWALK_H
#define KOMPARU_DIRWALK_H

#include "compat.h"

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

#endif /* KOMPARU_DIRWALK_H */
