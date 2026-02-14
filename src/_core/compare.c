/**
 * compare.c — Chunk-based comparison engine.
 *
 * Algorithm:
 * 1. Size pre-check (if both sizes known and differ → DIFFERENT)
 * 2. Optional quick check (sample first/last/middle)
 * 3. Sequential chunk read + memcmp until EOF or difference
 *
 * Memory: O(chunk_size) — two buffers only.
 * I/O: stops at first difference.
 */

#include "compare.h"
#include <stdlib.h>
#include <string.h>

komparu_result_t komparu_compare(
    komparu_reader_t *reader_a,
    komparu_reader_t *reader_b,
    size_t chunk_size,
    bool size_precheck,
    const char **err_msg
) {
    if (chunk_size == 0) {
        chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    }

    /* Step 1: Size pre-check */
    if (size_precheck) {
        int64_t size_a = reader_a->get_size(reader_a);
        int64_t size_b = reader_b->get_size(reader_b);

        if (size_a >= 0 && size_b >= 0) {
            if (size_a != size_b) {
                return KOMPARU_DIFFERENT;
            }
            /* Both zero — identical */
            if (size_a == 0) {
                return KOMPARU_EQUAL;
            }
        }
    }

    /* Allocate comparison buffers */
    void *buf_a = malloc(chunk_size);
    void *buf_b = malloc(chunk_size);
    if (!buf_a || !buf_b) {
        free(buf_a);
        free(buf_b);
        *err_msg = "out of memory";
        return KOMPARU_ERROR;
    }

    komparu_result_t result = KOMPARU_EQUAL;

    /* Step 2: Sequential chunk comparison */
    for (;;) {
        int64_t n_a = reader_a->read(reader_a, buf_a, chunk_size);
        int64_t n_b = reader_b->read(reader_b, buf_b, chunk_size);

        /* Read errors */
        if (n_a < 0) {
            *err_msg = reader_a->source_name
                ? reader_a->source_name
                : "source A read error";
            result = KOMPARU_ERROR;
            break;
        }
        if (n_b < 0) {
            *err_msg = reader_b->source_name
                ? reader_b->source_name
                : "source B read error";
            result = KOMPARU_ERROR;
            break;
        }

        /* Different read lengths → different content */
        if (n_a != n_b) {
            result = KOMPARU_DIFFERENT;
            break;
        }

        /* Both EOF → identical */
        if (n_a == 0) {
            result = KOMPARU_EQUAL;
            break;
        }

        /* Compare chunk contents */
        if (memcmp(buf_a, buf_b, (size_t)n_a) != 0) {
            result = KOMPARU_DIFFERENT;
            break;
        }
    }

    free(buf_a);
    free(buf_b);
    return result;
}

komparu_result_t komparu_quick_check(
    komparu_reader_t *reader_a,
    komparu_reader_t *reader_b,
    size_t chunk_size,
    const char **err_msg
) {
    if (chunk_size == 0) {
        chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    }

    /* Both readers must support seek and have known sizes */
    int64_t size_a = reader_a->get_size(reader_a);
    int64_t size_b = reader_b->get_size(reader_b);

    if (size_a < 0 || size_b < 0) {
        return KOMPARU_ERROR; /* Size unknown — can't quick check */
    }

    if (size_a != size_b) {
        return KOMPARU_DIFFERENT;
    }

    if (size_a == 0) {
        return KOMPARU_EQUAL;
    }

    if (!reader_a->seek || !reader_b->seek) {
        return KOMPARU_ERROR; /* Seek not supported */
    }

    void *buf_a = malloc(chunk_size);
    void *buf_b = malloc(chunk_size);
    if (!buf_a || !buf_b) {
        free(buf_a);
        free(buf_b);
        *err_msg = "out of memory";
        return KOMPARU_ERROR;
    }

    /* Sample points: start, end, middle */
    int64_t sample_offsets[3];
    int num_samples = 0;

    /* Always check start */
    sample_offsets[num_samples++] = 0;

    /* Check end (last chunk) if file is larger than one chunk */
    if (size_a > (int64_t)chunk_size) {
        int64_t end_offset = size_a - (int64_t)chunk_size;
        if (end_offset < 0) end_offset = 0;
        sample_offsets[num_samples++] = end_offset;
    }

    /* Check middle if file is larger than two chunks */
    if (size_a > (int64_t)(chunk_size * 2)) {
        int64_t mid_offset = size_a / 2;
        sample_offsets[num_samples++] = mid_offset;
    }

    komparu_result_t result = KOMPARU_EQUAL;

    for (int i = 0; i < num_samples; i++) {
        if (reader_a->seek(reader_a, sample_offsets[i]) != 0 ||
            reader_b->seek(reader_b, sample_offsets[i]) != 0) {
            result = KOMPARU_ERROR;
            *err_msg = "seek failed during quick check";
            break;
        }

        int64_t n_a = reader_a->read(reader_a, buf_a, chunk_size);
        int64_t n_b = reader_b->read(reader_b, buf_b, chunk_size);

        if (n_a < 0 || n_b < 0) {
            result = KOMPARU_ERROR;
            *err_msg = "read failed during quick check";
            break;
        }

        if (n_a != n_b || memcmp(buf_a, buf_b, (size_t)n_a) != 0) {
            result = KOMPARU_DIFFERENT;
            break;
        }
    }

    free(buf_a);
    free(buf_b);

    /* Reset readers to start for subsequent full comparison */
    if (result == KOMPARU_EQUAL && reader_a->seek && reader_b->seek) {
        reader_a->seek(reader_a, 0);
        reader_b->seek(reader_b, 0);
    }

    return result;
}
