/**
 * reader_archive.h — Archive reader using libarchive.
 *
 * Reads archive entries as a stream. No disk extraction.
 * Nested archives compared as binary blobs (never recursed).
 * Archive bomb protection: size, ratio, entry count, name length.
 */

#ifndef KOMPARU_READER_ARCHIVE_H
#define KOMPARU_READER_ARCHIVE_H

#include "reader.h"

/* Forward declarations */
typedef struct komparu_archive_iter komparu_archive_iter_t;
struct komparu_dir_result;
typedef struct komparu_dir_result komparu_dir_result_t;

/**
 * Compare two archive files entry-by-entry.
 *
 * Reads both archives into sorted in-memory entry lists,
 * then performs sorted merge comparison.
 *
 * path_a, path_b: local file paths to archive files.
 * chunk_size: unused (in-memory memcmp).
 * max_decompressed_size: max total decompressed bytes (0 = no limit).
 * max_compression_ratio: max ratio decompressed/compressed (0 = no limit).
 * max_entries: max number of entries (0 = no limit).
 * max_entry_name_length: max entry path length (0 = no limit).
 *
 * Returns allocated dir_result_t, or NULL on error.
 * Caller must free with komparu_dir_result_free().
 */
komparu_dir_result_t *komparu_compare_archives(
    const char *path_a,
    const char *path_b,
    size_t chunk_size,
    int64_t max_decompressed_size,
    int max_compression_ratio,
    int64_t max_entries,
    int64_t max_entry_name_length,
    const char **err_msg
);

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
