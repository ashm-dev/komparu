/**
 * reader_http.h — HTTP Range reader using libcurl.
 *
 * Sync: libcurl easy interface (blocking, GIL released).
 * Async: libcurl multi interface (non-blocking, event loop integration).
 */

#ifndef KOMPARU_READER_HTTP_H
#define KOMPARU_READER_HTTP_H

#include "reader.h"

/**
 * Initialize global libcurl state.
 * Must be called once during module init (curl_global_init).
 *
 * Returns 0 on success, -1 on failure.
 */
int komparu_curl_global_init(void);

/**
 * Cleanup global libcurl state.
 * Must be called during module cleanup.
 */
void komparu_curl_global_cleanup(void);

/**
 * Create an HTTP reader allowing connections to private networks.
 * Same as komparu_reader_http_open but with allow_private flag.
 */
komparu_reader_t *komparu_reader_http_open_ex(
    const char *url,
    const char **headers,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    bool allow_private,
    const char **err_msg
);

#endif /* KOMPARU_READER_HTTP_H */
