/**
 * curl_share.h — CURLSH share interface for connection/DNS/TLS reuse.
 *
 * Provides a global CURLSH* handle that all curl easy handles can attach to,
 * enabling connection pool, DNS cache, and TLS session reuse across requests.
 */

#ifndef KOMPARU_CURL_SHARE_H
#define KOMPARU_CURL_SHARE_H

#include <curl/curl.h>

/**
 * Initialize the global curl share handle.
 * Creates CURLSH with DNS, connection, and SSL session sharing.
 * Thread-safe: uses per-lock-data mutexes for concurrent access.
 *
 * Returns 0 on success, -1 on failure.
 */
int komparu_curl_share_init(void);

/**
 * Cleanup the global curl share handle.
 * Must be called during module cleanup (via Py_AtExit).
 */
void komparu_curl_share_cleanup(void);

/**
 * Get the current global share handle.
 * Returns NULL if not initialized.
 */
CURLSH *komparu_curl_share_get(void);

#endif /* KOMPARU_CURL_SHARE_H */
