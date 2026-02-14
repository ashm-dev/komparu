/**
 * reader_http.c — HTTP Range reader using libcurl (sync: easy interface).
 *
 * Stub for Phase 1. Full implementation in Phase 2.
 */

#include "reader_http.h"
#include <curl/curl.h>

int komparu_curl_global_init(void) {
    CURLcode res = curl_global_init(CURL_GLOBAL_DEFAULT);
    return (res == CURLE_OK) ? 0 : -1;
}

void komparu_curl_global_cleanup(void) {
    curl_global_cleanup();
}

komparu_reader_t *komparu_reader_http_open(
    const char *url,
    const char **headers,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    const char **err_msg
) {
    (void)url;
    (void)headers;
    (void)timeout;
    (void)follow_redirects;
    (void)verify_ssl;
    *err_msg = "HTTP reader not yet implemented";
    return NULL;
}
