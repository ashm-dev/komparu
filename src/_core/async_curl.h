/**
 * async_curl.h — Async HTTP reader using libcurl multi interface.
 *
 * Non-blocking HTTP downloads integrated with Python asyncio
 * via socket file descriptors and timer callbacks.
 *
 * Flow:
 * 1. komparu_async_http_open() — create handle, kick curl
 * 2. Python registers fileno() with asyncio loop
 * 3. On socket ready: komparu_async_http_perform()
 * 4. On timeout: komparu_async_http_timeout_perform()
 * 5. Read buffered data: komparu_async_http_read()
 * 6. komparu_async_http_close() — cleanup
 */

#ifndef KOMPARU_ASYNC_CURL_H
#define KOMPARU_ASYNC_CURL_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/* Opaque handle for async HTTP transfer */
typedef struct komparu_async_http komparu_async_http_t;

/* Event flags for asyncio integration (match CURL_CSELECT_*) */
#define KOMPARU_ASYNC_EV_IN   1
#define KOMPARU_ASYNC_EV_OUT  2

/**
 * Create an async HTTP reader and start the connection (non-blocking).
 * Returns NULL on error, sets *err_msg.
 */
komparu_async_http_t *komparu_async_http_open(
    const char *url,
    const char **headers,     /* NULL-terminated array of "Key: Value" strings, or NULL */
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    bool allow_private,
    const char **err_msg
);

/**
 * Get the socket fd for asyncio registration.
 * Returns -1 if no socket is active yet (use timeout to advance).
 */
int komparu_async_http_fileno(komparu_async_http_t *h);

/**
 * Get wanted events: KOMPARU_ASYNC_EV_IN and/or KOMPARU_ASYNC_EV_OUT.
 */
int komparu_async_http_events(komparu_async_http_t *h);

/**
 * Drive state machine on socket event.
 * ev_bitmask: KOMPARU_ASYNC_EV_IN and/or KOMPARU_ASYNC_EV_OUT.
 */
void komparu_async_http_perform(komparu_async_http_t *h, int fd, int ev_bitmask);

/**
 * Drive state machine on timeout.
 */
void komparu_async_http_timeout_perform(komparu_async_http_t *h);

/**
 * Milliseconds until next required timeout callback.
 * Returns -1 if no timer is needed.
 */
long komparu_async_http_timeout_ms(komparu_async_http_t *h);

/**
 * Read up to `size` bytes from internal buffer into `buf`.
 * Returns bytes copied (0 if buffer empty — check done() for EOF vs need-more-data).
 */
size_t komparu_async_http_read(komparu_async_http_t *h, void *buf, size_t size);

/**
 * Bytes available in the internal buffer.
 */
size_t komparu_async_http_buffered(komparu_async_http_t *h);

/**
 * Content-Length from response headers. Returns -1 if unknown/not yet available.
 */
int64_t komparu_async_http_size(komparu_async_http_t *h);

/**
 * True when transfer is complete (success or error).
 */
bool komparu_async_http_done(komparu_async_http_t *h);

/**
 * Error message if transfer failed. Returns NULL if no error.
 */
const char *komparu_async_http_error(komparu_async_http_t *h);

/**
 * HTTP status code. Returns 0 if not yet available.
 */
long komparu_async_http_status(komparu_async_http_t *h);

/**
 * Close and free all resources.
 */
void komparu_async_http_close(komparu_async_http_t *h);

#endif /* KOMPARU_ASYNC_CURL_H */
