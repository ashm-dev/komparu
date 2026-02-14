/**
 * reader_archive.c — Archive reader using libarchive.
 *
 * Stub for Phase 1. Full implementation in Phase 3.
 */

#include "reader_archive.h"

komparu_reader_t *komparu_reader_archive_open(
    komparu_reader_t *inner_reader,
    const char **err_msg
) {
    (void)inner_reader;
    *err_msg = "archive reader not yet implemented";
    return NULL;
}

komparu_archive_iter_t *komparu_archive_iter_open(
    komparu_reader_t *inner_reader,
    const char **err_msg
) {
    (void)inner_reader;
    *err_msg = "archive iterator not yet implemented";
    return NULL;
}

komparu_reader_t *komparu_archive_iter_next(
    komparu_archive_iter_t *iter,
    const char **entry_name,
    const char **err_msg
) {
    (void)iter;
    (void)entry_name;
    *err_msg = "archive iterator not yet implemented";
    return NULL;
}

void komparu_archive_iter_close(komparu_archive_iter_t *iter) {
    (void)iter;
}
