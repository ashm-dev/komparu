/**
 * dirwalk.c — Recursive directory traversal.
 *
 * Stub for Phase 1. Full implementation in Phase 3.
 */

#include "dirwalk.h"
#include <stdlib.h>

int komparu_dirwalk(
    const char *base_dir,
    bool follow_symlinks,
    komparu_pathlist_t *result,
    const char **err_msg
) {
    (void)base_dir;
    (void)follow_symlinks;
    (void)result;
    *err_msg = "directory walker not yet implemented";
    return -1;
}

void komparu_pathlist_free(komparu_pathlist_t *list) {
    if (!list) return;
    for (size_t i = 0; i < list->count; i++) {
        free(list->paths[i]);
    }
    free(list->paths);
    list->paths = NULL;
    list->count = 0;
    list->capacity = 0;
}
