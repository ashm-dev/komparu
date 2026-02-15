/**
 * compare.h — Comparison engine interface.
 *
 * Chunk-based byte comparison between two readers.
 */

#ifndef KOMPARU_COMPARE_H
#define KOMPARU_COMPARE_H

#include "reader.h"

/**
 * Comparison result codes.
 */
typedef enum {
    KOMPARU_EQUAL     =  1,   /* Sources are byte-identical */
    KOMPARU_DIFFERENT =  0,   /* Sources differ */
    KOMPARU_ERROR     = -1,   /* Error during comparison */
} komparu_result_t;

/**
 * Compare two readers byte-by-byte in chunks.
 *
 * chunk_size: read buffer size (default: KOMPARU_DEFAULT_CHUNK_SIZE).
 * size_precheck: if true, compare get_size() first as fast path.
 *
 * Returns KOMPARU_EQUAL, KOMPARU_DIFFERENT, or KOMPARU_ERROR.
 * On error, sets *err_msg.
 */
komparu_result_t komparu_compare(
    komparu_reader_t *reader_a,
    komparu_reader_t *reader_b,
    size_t chunk_size,
    bool size_precheck,
    const char **err_msg
);

/**
 * Quick check: sample up to 5 offsets (start, end, 25%, 50%, 75%) before full scan.
 * Only works if both readers support seek.
 *
 * Returns:
 *   KOMPARU_DIFFERENT — definite difference found
 *   KOMPARU_EQUAL     — samples match (caller should still do full compare)
 *   KOMPARU_ERROR     — seek not supported or error
 */
komparu_result_t komparu_quick_check(
    komparu_reader_t *reader_a,
    komparu_reader_t *reader_b,
    size_t chunk_size,
    const char **err_msg
);

/**
 * Free thread-local comparison buffers.
 * Call from worker threads before exit to prevent leaks.
 * Safe to call even if buffers were never allocated.
 */
void komparu_compare_tls_cleanup(void);

/* =========================================================================
 * Directory / archive comparison result
 * ========================================================================= */

/* Diff reasons */
#define KOMPARU_DIFF_CONTENT    0
#define KOMPARU_DIFF_SIZE       1
#define KOMPARU_DIFF_READ_ERROR 2

typedef struct {
    char *path;
    int reason;
} komparu_diff_entry_t;

typedef struct komparu_dir_result {
    bool equal;

    komparu_diff_entry_t *diffs;
    size_t diff_count;
    size_t diff_cap;

    char **only_left;
    size_t only_left_count;
    size_t only_left_cap;

    char **only_right;
    size_t only_right_count;
    size_t only_right_cap;
} komparu_dir_result_t;

komparu_dir_result_t *komparu_dir_result_new(void);
void komparu_dir_result_free(komparu_dir_result_t *result);

int komparu_dir_result_add_diff(komparu_dir_result_t *r, const char *path, int reason);
int komparu_dir_result_add_only_left(komparu_dir_result_t *r, const char *path);
int komparu_dir_result_add_only_right(komparu_dir_result_t *r, const char *path);

#endif /* KOMPARU_COMPARE_H */
