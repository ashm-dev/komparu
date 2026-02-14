/**
 * reader.h — Abstract reader interface.
 *
 * Uniform API for reading bytes from any source:
 * local files, HTTP URLs, archive entries.
 */

#ifndef KOMPARU_READER_H
#define KOMPARU_READER_H

#include "compat.h"

/**
 * Abstract reader — a source of bytes.
 *
 * All implementations must set read, get_size, close, and ctx.
 * The reader owns its ctx and frees it in close().
 */
typedef struct komparu_reader {
    /**
     * Read up to `size` bytes into `buf`.
     *
     * Returns:
     *   > 0  — number of bytes read
     *     0  — EOF
     *    -1  — error (caller should check errno or reader-specific state)
     */
    int64_t (*read)(struct komparu_reader *self, void *buf, size_t size);

    /**
     * Get total size of the source if known.
     *
     * Returns:
     *   >= 0  — known size in bytes
     *     -1  — size unknown (e.g. chunked HTTP, streaming)
     */
    int64_t (*get_size)(struct komparu_reader *self);

    /**
     * Seek to absolute position `offset`.
     *
     * Returns:
     *    0  — success
     *   -1  — seek not supported or error
     */
    int (*seek)(struct komparu_reader *self, int64_t offset);

    /**
     * Close reader and free all resources.
     * After close(), the reader must not be used.
     */
    void (*close)(struct komparu_reader *self);

    /** Opaque implementation state. */
    void *ctx;

    /** Human-readable source identifier (for error messages). Not owned. */
    const char *source_name;
} komparu_reader_t;


/* =========================================================================
 * Reader constructors (implemented in reader_*.c)
 * ========================================================================= */

/**
 * Create a file reader using mmap (Unix) or ReadFile (Windows).
 *
 * Returns NULL on error (file not found, permission denied, etc.).
 * On error, sets *err_msg to a static or malloc'd error string.
 */
komparu_reader_t *komparu_reader_file_open(const char *path, const char **err_msg);

/**
 * Create an HTTP reader using libcurl.
 *
 * headers: NULL-terminated array of "Key: Value" strings, or NULL.
 * Returns NULL on error.
 */
komparu_reader_t *komparu_reader_http_open(
    const char *url,
    const char **headers,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    const char **err_msg
);

/**
 * Create an archive reader using libarchive.
 *
 * inner_reader: the reader for the archive file itself (file or HTTP).
 * Returns NULL on error.
 */
komparu_reader_t *komparu_reader_archive_open(
    komparu_reader_t *inner_reader,
    const char **err_msg
);

#endif /* KOMPARU_READER_H */
