/**
 * reader_http.c — HTTP Range reader using libcurl easy interface (sync).
 *
 * Strategy:
 * - HEAD request on open() to detect size and validate connectivity
 * - Per-read Range GET requests (one curl_easy_perform per read call)
 * - Direct buffer write (curl callback writes into user buffer)
 * - Seek = change offset, next read uses new Range header
 * - SSRF protection via CURLOPT_OPENSOCKETFUNCTION (blocks private IPs)
 * - Connection reuse via TCP keepalive on the same CURL handle
 */

#include "reader_http.h"
#include <curl/curl.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>  /* strncasecmp */
#include <errno.h>

#ifndef KOMPARU_WINDOWS
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#endif

/* Thread-local error buffer for HTTP errors */
static _Thread_local char http_errbuf[512];

/* =========================================================================
 * SSRF Protection — block connections to private/internal networks
 * ========================================================================= */

#ifndef KOMPARU_WINDOWS

static bool is_private_ipv4(const struct in_addr *addr) {
    uint32_t ip = ntohl(addr->s_addr);

    /* 127.0.0.0/8 — loopback */
    if ((ip & 0xFF000000) == 0x7F000000) return true;
    /* 10.0.0.0/8 — private */
    if ((ip & 0xFF000000) == 0x0A000000) return true;
    /* 172.16.0.0/12 — private */
    if ((ip & 0xFFF00000) == 0xAC100000) return true;
    /* 192.168.0.0/16 — private */
    if ((ip & 0xFFFF0000) == 0xC0A80000) return true;
    /* 169.254.0.0/16 — link-local */
    if ((ip & 0xFFFF0000) == 0xA9FE0000) return true;
    /* 0.0.0.0/8 — "this" network */
    if ((ip & 0xFF000000) == 0x00000000) return true;

    return false;
}

static bool is_private_ipv6(const struct in6_addr *addr) {
    /* ::1 — loopback */
    if (IN6_IS_ADDR_LOOPBACK(addr)) return true;
    /* fe80::/10 — link-local */
    if (IN6_IS_ADDR_LINKLOCAL(addr)) return true;
    /* fc00::/7 — unique local (ULA) */
    if ((addr->s6_addr[0] & 0xFE) == 0xFC) return true;
    /* ::ffff:x.x.x.x — IPv4-mapped, check the IPv4 part */
    if (IN6_IS_ADDR_V4MAPPED(addr)) {
        struct in_addr v4;
        memcpy(&v4, &addr->s6_addr[12], 4);
        return is_private_ipv4(&v4);
    }

    return false;
}

/**
 * CURLOPT_OPENSOCKETFUNCTION callback.
 * Called before curl creates the socket. We inspect the resolved IP
 * and return CURL_SOCKET_BAD to block connections to private networks.
 * This also catches DNS rebinding attacks.
 */
static curl_socket_t ssrf_opensocket_cb(
    void *clientp,
    curlsocktype purpose,
    struct curl_sockaddr *address
) {
    (void)purpose;
    bool *allow_private = (bool *)clientp;

    if (!allow_private || !*allow_private) {
        if (address->family == AF_INET) {
            struct sockaddr_in *sin = (struct sockaddr_in *)&address->addr;
            if (is_private_ipv4(&sin->sin_addr)) {
                return CURL_SOCKET_BAD;
            }
        } else if (address->family == AF_INET6) {
            struct sockaddr_in6 *sin6 = (struct sockaddr_in6 *)&address->addr;
            if (is_private_ipv6(&sin6->sin6_addr)) {
                return CURL_SOCKET_BAD;
            }
        }
    }

    /* Create the socket normally */
    return socket(address->family, address->socktype, address->protocol);
}

#endif /* KOMPARU_WINDOWS */

/* =========================================================================
 * Write callback — direct write into user buffer
 * ========================================================================= */

typedef struct {
    char *buf;          /* User-provided buffer */
    size_t buf_size;    /* Total buffer capacity */
    size_t written;     /* Bytes written so far */
    bool overflow;      /* Server sent more data than buffer capacity */
} write_ctx_t;

static size_t write_callback(void *contents, size_t size, size_t nmemb, void *userp) {
    size_t total = size * nmemb;
    write_ctx_t *wctx = (write_ctx_t *)userp;

    size_t remaining = wctx->buf_size - wctx->written;

    if (total > remaining) {
        /* Server sent more data than requested — Range was ignored */
        if (remaining > 0) {
            memcpy(wctx->buf + wctx->written, contents, remaining);
            wctx->written += remaining;
        }
        wctx->overflow = true;
        return total;  /* Keep curl happy */
    }

    memcpy(wctx->buf + wctx->written, contents, total);
    wctx->written += total;
    return total;
}

/* Discard callback for HEAD requests */
static size_t discard_callback(void *contents, size_t size, size_t nmemb, void *userp) {
    (void)contents;
    (void)userp;
    return size * nmemb;
}

/* Header callback for HEAD requests — detect Accept-Ranges */
static size_t head_header_callback(char *buffer, size_t size, size_t nitems, void *userp) {
    size_t total = size * nitems;
    bool *range_flag = (bool *)userp;
    const char *end = buffer + total;

    /* Need at least "Accept-Ranges: bytes" (20 chars + CRLF) */
    if (total >= 22 &&
        (buffer[0] == 'A' || buffer[0] == 'a') &&
        (buffer[1] == 'c' || buffer[1] == 'C') &&
        strncasecmp(buffer, "Accept-Ranges:", 14) == 0) {
        const char *val = buffer + 14;
        while (val < end && (*val == ' ' || *val == '\t')) val++;
        if (val + 5 <= end && strncasecmp(val, "bytes", 5) == 0) {
            *range_flag = true;
        }
    }

    return total;
}

/* =========================================================================
 * HTTP reader context
 * ========================================================================= */

typedef struct {
    CURL *easy;
    char *url;                  /* Owned copy of URL */
    struct curl_slist *headers; /* Owned curl header list */

    int64_t file_size;          /* Total file size (-1 if unknown) */
    int64_t offset;             /* Current read position */
    bool range_supported;       /* Server supports Range requests */
    bool allow_private;         /* Allow SSRF (private network redirects) */

    char curl_errbuf[CURL_ERROR_SIZE]; /* Per-handle curl error buffer */
} http_ctx_t;

/* =========================================================================
 * Reader interface implementations
 * ========================================================================= */

static int64_t http_get_size(komparu_reader_t *self) {
    http_ctx_t *ctx = (http_ctx_t *)self->ctx;
    return ctx->file_size;
}

static int http_seek(komparu_reader_t *self, int64_t offset) {
    http_ctx_t *ctx = (http_ctx_t *)self->ctx;

    if (!ctx->range_supported) {
        return -1; /* Seek requires Range support */
    }

    if (offset < 0) {
        return -1;
    }

    /* Allow seek beyond known size — server will return appropriate error */
    ctx->offset = offset;
    return 0;
}

static int64_t http_read(komparu_reader_t *self, void *buf, size_t size) {
    if (size == 0) return 0;

    http_ctx_t *ctx = (http_ctx_t *)self->ctx;

    /* EOF check if size is known */
    if (ctx->file_size >= 0 && ctx->offset >= ctx->file_size) {
        return 0;
    }

    /* Guard: non-Range server can only do one full GET from offset 0 */
    if (!ctx->range_supported && ctx->offset > 0) {
        snprintf(http_errbuf, sizeof(http_errbuf),
                 "server does not support Range requests");
        return -1;
    }

    /* Clamp read size to remaining bytes if size known */
    if (ctx->file_size >= 0) {
        int64_t remaining = ctx->file_size - ctx->offset;
        if ((int64_t)size > remaining) {
            size = (size_t)remaining;
        }
    }

    /* Set up direct buffer write */
    write_ctx_t wctx = {
        .buf = (char *)buf,
        .buf_size = size,
        .written = 0,
        .overflow = false,
    };

    curl_easy_setopt(ctx->easy, CURLOPT_NOBODY, 0L);
    curl_easy_setopt(ctx->easy, CURLOPT_HTTPGET, 1L);
    curl_easy_setopt(ctx->easy, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(ctx->easy, CURLOPT_WRITEDATA, &wctx);

    if (ctx->range_supported) {
        /* Configure Range header: "start-end" (inclusive) */
        char range_str[64];
        snprintf(range_str, sizeof(range_str), "%lld-%lld",
                 (long long)ctx->offset,
                 (long long)(ctx->offset + (int64_t)size - 1));
        curl_easy_setopt(ctx->easy, CURLOPT_RANGE, range_str);
    } else {
        /* No Range — full GET, only valid from current sequential position */
        curl_easy_setopt(ctx->easy, CURLOPT_RANGE, NULL);
    }

    CURLcode res = curl_easy_perform(ctx->easy);

    if (res != CURLE_OK) {
        snprintf(http_errbuf, sizeof(http_errbuf),
                 "HTTP read error: %s", ctx->curl_errbuf);
        return -1;
    }

    long response_code = 0;
    curl_easy_getinfo(ctx->easy, CURLINFO_RESPONSE_CODE, &response_code);

    if (response_code == 206) {
        /* Partial Content — Range supported, as expected */
        ctx->offset += (int64_t)wctx.written;
        return (int64_t)wctx.written;
    }

    if (response_code == 200) {
        /*
         * Server ignored Range and sent full file.
         * This is only acceptable for the very first read from offset 0
         * when requesting the entire file.
         */
        if (ctx->offset == 0) {
            ctx->range_supported = false;
            ctx->offset += (int64_t)wctx.written;
            return (int64_t)wctx.written;
        }
        /* Requested a range but got full file — can't do random access */
        snprintf(http_errbuf, sizeof(http_errbuf),
                 "server does not support Range requests");
        return -1;
    }

    if (response_code == 416) {
        /* Range Not Satisfiable — treat as EOF */
        return 0;
    }

    /* 4xx / 5xx error */
    snprintf(http_errbuf, sizeof(http_errbuf),
             "HTTP error: status %ld", response_code);
    return -1;
}

static void http_close(komparu_reader_t *self) {
    if (!self) return;

    http_ctx_t *ctx = (http_ctx_t *)self->ctx;
    if (ctx) {
        if (ctx->headers) curl_slist_free_all(ctx->headers);
        if (ctx->easy) curl_easy_cleanup(ctx->easy);
        free(ctx->url);
        free(ctx);
    }
    /* source_name is ctx->url via pointer — already freed above.
     * Set to NULL to be safe. */
    free(self);
}

/* =========================================================================
 * Global init / cleanup
 * ========================================================================= */

int komparu_curl_global_init(void) {
    CURLcode res = curl_global_init(CURL_GLOBAL_DEFAULT);
    return (res == CURLE_OK) ? 0 : -1;
}

void komparu_curl_global_cleanup(void) {
    curl_global_cleanup();
}

/* =========================================================================
 * Constructor
 * ========================================================================= */

komparu_reader_t *komparu_reader_http_open(
    const char *url,
    const char **headers,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    const char **err_msg
) {
    return komparu_reader_http_open_ex(
        url, headers, timeout, follow_redirects, verify_ssl,
        false, /* allow_private = false by default */
        err_msg
    );
}

komparu_reader_t *komparu_reader_http_open_ex(
    const char *url,
    const char **headers,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    bool allow_private,
    const char **err_msg
) {
    /* Allocate structures */
    komparu_reader_t *reader = calloc(1, sizeof(komparu_reader_t));
    http_ctx_t *ctx = calloc(1, sizeof(http_ctx_t));
    if (!reader || !ctx) {
        *err_msg = "out of memory";
        free(reader);
        free(ctx);
        return NULL;
    }

    ctx->url = strdup(url);
    if (!ctx->url) {
        *err_msg = "out of memory";
        free(ctx);
        free(reader);
        return NULL;
    }

    /* Initialize curl easy handle */
    ctx->easy = curl_easy_init();
    if (!ctx->easy) {
        *err_msg = "failed to initialize libcurl handle";
        free(ctx->url);
        free(ctx);
        free(reader);
        return NULL;
    }

    /* ---- Basic configuration ---- */
    curl_easy_setopt(ctx->easy, CURLOPT_URL, ctx->url);
    curl_easy_setopt(ctx->easy, CURLOPT_ERRORBUFFER, ctx->curl_errbuf);
    curl_easy_setopt(ctx->easy, CURLOPT_NOSIGNAL, 1L);  /* Thread-safe */

    /* ---- Protocol restrictions ---- */
    curl_easy_setopt(ctx->easy, CURLOPT_PROTOCOLS_STR, "http,https");
    curl_easy_setopt(ctx->easy, CURLOPT_REDIR_PROTOCOLS_STR, "http,https");

    /* ---- Timeout ---- */
    long timeout_ms = (long)(timeout * 1000.0);
    if (timeout_ms <= 0) timeout_ms = 30000;
    curl_easy_setopt(ctx->easy, CURLOPT_TIMEOUT_MS, timeout_ms);
    curl_easy_setopt(ctx->easy, CURLOPT_CONNECTTIMEOUT_MS,
                     timeout_ms < 10000 ? timeout_ms : 10000L);

    /* ---- Redirects ---- */
    if (follow_redirects) {
        curl_easy_setopt(ctx->easy, CURLOPT_FOLLOWLOCATION, 1L);
        curl_easy_setopt(ctx->easy, CURLOPT_MAXREDIRS, 10L);
    } else {
        curl_easy_setopt(ctx->easy, CURLOPT_FOLLOWLOCATION, 0L);
    }

    /* ---- SSL ---- */
    curl_easy_setopt(ctx->easy, CURLOPT_SSL_VERIFYPEER, verify_ssl ? 1L : 0L);
    curl_easy_setopt(ctx->easy, CURLOPT_SSL_VERIFYHOST, verify_ssl ? 2L : 0L);

    /* ---- Connection reuse & keepalive ---- */
    curl_easy_setopt(ctx->easy, CURLOPT_TCP_KEEPALIVE, 1L);
    curl_easy_setopt(ctx->easy, CURLOPT_TCP_KEEPIDLE, 60L);
    curl_easy_setopt(ctx->easy, CURLOPT_TCP_KEEPINTVL, 30L);

    /* ---- Custom headers ---- */
    if (headers) {
        for (const char **h = headers; *h != NULL; h++) {
            ctx->headers = curl_slist_append(ctx->headers, *h);
        }
        curl_easy_setopt(ctx->easy, CURLOPT_HTTPHEADER, ctx->headers);
    }

    /* ---- SSRF protection ---- */
#ifndef KOMPARU_WINDOWS
    ctx->allow_private = allow_private;
    curl_easy_setopt(ctx->easy, CURLOPT_OPENSOCKETFUNCTION, ssrf_opensocket_cb);
    curl_easy_setopt(ctx->easy, CURLOPT_OPENSOCKETDATA, &ctx->allow_private);
#endif

    /* =========================================================================
     * HEAD request to detect size, Range support, and validate connectivity
     * ========================================================================= */
    bool head_range_supported = false;

    curl_easy_setopt(ctx->easy, CURLOPT_NOBODY, 1L);
    curl_easy_setopt(ctx->easy, CURLOPT_WRITEFUNCTION, discard_callback);
    curl_easy_setopt(ctx->easy, CURLOPT_WRITEDATA, NULL);
    curl_easy_setopt(ctx->easy, CURLOPT_HEADERFUNCTION, head_header_callback);
    curl_easy_setopt(ctx->easy, CURLOPT_HEADERDATA, &head_range_supported);

    CURLcode res = curl_easy_perform(ctx->easy);

    /* Remove header callback for subsequent requests */
    curl_easy_setopt(ctx->easy, CURLOPT_HEADERFUNCTION, NULL);
    curl_easy_setopt(ctx->easy, CURLOPT_HEADERDATA, NULL);

    if (res != CURLE_OK) {
        if (res == CURLE_COULDNT_CONNECT && ctx->curl_errbuf[0] == '\0') {
            *err_msg = "connection blocked by SSRF protection or network error";
        } else {
            snprintf(http_errbuf, sizeof(http_errbuf),
                     "HTTP HEAD failed: %s",
                     ctx->curl_errbuf[0] ? ctx->curl_errbuf : curl_easy_strerror(res));
            *err_msg = http_errbuf;
        }
        goto fail;
    }

    /* Check HTTP status */
    long response_code = 0;
    curl_easy_getinfo(ctx->easy, CURLINFO_RESPONSE_CODE, &response_code);

    if (response_code == 404 || response_code == 410) {
        snprintf(http_errbuf, sizeof(http_errbuf),
                 "HTTP %ld: resource not found", response_code);
        *err_msg = http_errbuf;
        goto fail;
    }

    if (response_code >= 400) {
        snprintf(http_errbuf, sizeof(http_errbuf),
                 "HTTP error: status %ld", response_code);
        *err_msg = http_errbuf;
        goto fail;
    }

    /* Extract Content-Length */
    curl_off_t content_length = -1;
    curl_easy_getinfo(ctx->easy, CURLINFO_CONTENT_LENGTH_DOWNLOAD_T, &content_length);
    ctx->file_size = (int64_t)content_length; /* -1 if unknown */

    /* Set Range support based on Accept-Ranges header from HEAD response */
    ctx->range_supported = head_range_supported;
    ctx->offset = 0;

    /* ---- Wire up reader interface ---- */
    reader->ctx = ctx;
    reader->source_name = ctx->url; /* Points into ctx, freed in http_close */
    reader->read = http_read;
    reader->get_size = http_get_size;
    reader->seek = http_seek;
    reader->close = http_close;

    return reader;

fail:
    if (ctx->headers) curl_slist_free_all(ctx->headers);
    if (ctx->easy) curl_easy_cleanup(ctx->easy);
    free(ctx->url);
    free(ctx);
    free(reader);
    return NULL;
}
