/**
 * reader_archive.h — Archive reader using libarchive.
 *
 * Reads archive entries as a stream. No disk extraction.
 * Nested archives compared as binary blobs (never recursed).
 */

#ifndef KOMPARU_READER_ARCHIVE_H
#define KOMPARU_READER_ARCHIVE_H

#include "reader.h"

/* Forward declaration for archive entry iteration */
typedef struct komparu_archive_iter komparu_archive_iter_t;

/**
 * Open an archive for iteration over entries.
 *
 * inner_reader: reader providing the raw archive bytes.
 * Returns NULL on error.
 */
komparu_archive_iter_t *komparu_archive_iter_open(
    komparu_reader_t *inner_reader,
    const char **err_msg
);

/**
 * Get next entry from archive iterator.
 *
 * Sets *entry_name to the sanitized relative path.
 * Returns a reader for the entry data, or NULL if no more entries.
 */
komparu_reader_t *komparu_archive_iter_next(
    komparu_archive_iter_t *iter,
    const char **entry_name,
    const char **err_msg
);

/**
 * Close archive iterator and free resources.
 */
void komparu_archive_iter_close(komparu_archive_iter_t *iter);

#endif /* KOMPARU_READER_ARCHIVE_H */
