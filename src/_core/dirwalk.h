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
 * Arena block for contiguous string storage.
 * Strings are packed sequentially into 64KB blocks, eliminating
 * per-allocation malloc overhead (~16 bytes/alloc).
 */
typedef struct komparu_arena_block {
    struct komparu_arena_block *next;
    size_t used;
    size_t capacity;
    char data[];  /* flexible array member */
} komparu_arena_block_t;

typedef struct {
    komparu_arena_block_t *head;    /* first block */
    komparu_arena_block_t *current; /* current block for allocation */
} komparu_arena_t;

/**
 * Directory entry list — dynamic array of relative paths.
 * Path strings live in the arena; only the pointer array is malloc'd.
 */
typedef struct {
    char **paths;       /* Array of pointers (into arena) */
    size_t count;       /* Number of entries */
    size_t capacity;    /* Allocated capacity */
    komparu_arena_t arena;
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
 * If max_workers > 1, file comparisons run in parallel.
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
    size_t max_workers,
    const char **err_msg
);

#endif /* KOMPARU_DIRWALK_H */
