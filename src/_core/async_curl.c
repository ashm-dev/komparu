/**
 * async_curl.c — Async HTTP reader using libcurl multi interface.
 *
 * Non-blocking HTTP: curl_multi_socket_action() driven by
 * asyncio event loop via socket fd registration.
 *
 * Data flow:
 * - curl write callback → linear buffer (compact on demand)
 * - Python reads from buffer via komparu_async_http_read()
 * - asyncio watches fileno() for events, calls perform()
 */

#include "async_curl.h"
#include "compat.h"
#include <curl/curl.h>
#include <stdlib.h>
#include <string.h>

#ifndef KOMPARU_WINDOWS
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#endif

/* =========================================================================
 * Internal structure
 * ========================================================================= */

struct komparu_async_http {
    CURLM *multi;
    CURL *easy;
    struct curl_slist *hdrs;
    int still_running;

    /* Socket tracking (single-transfer → one socket) */
    int sock;
    int sock_events;    /* KOMPARU_ASYNC_EV_IN | _OUT */

    /* Timer */
    long timer_ms;      /* -1 = no timer */

    /* Linear buffer: [consumed | available | free]
     *                 ^0        ^read_pos   ^write_pos  ^cap */
    uint8_t *buf;
    size_t buf_cap;
    size_t read_pos;
    size_t write_pos;

    /* Transfer status */
    bool done;
    bool error;
    char errmsg[512];

    /* Response info */
    int64_t content_length;
    long http_status;

    /* SSRF */
    bool allow_private;
};

/* =========================================================================
 * SSRF protection (duplicated from reader_http.c for static linkage)
 * ========================================================================= */

#ifndef KOMPARU_WINDOWS

static bool async_is_private_ipv4(const struct in_addr *addr) {
    uint32_t ip = ntohl(addr->s_addr);
    if ((ip & 0xFF000000) == 0x7F000000) return true;  /* 127.0.0.0/8 */
    if ((ip & 0xFF000000) == 0x0A000000) return true;  /* 10.0.0.0/8 */
    if ((ip & 0xFFF00000) == 0xAC100000) return true;  /* 172.16.0.0/12 */
    if ((ip & 0xFFFF0000) == 0xC0A80000) return true;  /* 192.168.0.0/16 */
    if ((ip & 0xFFFF0000) == 0xA9FE0000) return true;  /* 169.254.0.0/16 */
    if ((ip & 0xFF000000) == 0x00000000) return true;  /* 0.0.0.0/8 */
    return false;
}

static bool async_is_private_ipv6(const struct in6_addr *addr) {
    if (IN6_IS_ADDR_LOOPBACK(addr)) return true;
    if (IN6_IS_ADDR_LINKLOCAL(addr)) return true;
    if ((addr->s6_addr[0] & 0xFE) == 0xFC) return true;
    if (IN6_IS_ADDR_V4MAPPED(addr)) {
        struct in_addr v4;
        memcpy(&v4, &addr->s6_addr[12], 4);
        return async_is_private_ipv4(&v4);
    }
    return false;
}

static curl_socket_t async_ssrf_cb(
    void *clientp, curlsocktype purpose, struct curl_sockaddr *address
) {
    (void)purpose;
    bool *allow = (bool *)clientp;
    if (!allow || !*allow) {
        if (address->family == AF_INET) {
            struct sockaddr_in *sin = (struct sockaddr_in *)&address->addr;
            if (async_is_private_ipv4(&sin->sin_addr)) return CURL_SOCKET_BAD;
        } else if (address->family == AF_INET6) {
            struct sockaddr_in6 *sin6 = (struct sockaddr_in6 *)&address->addr;
            if (async_is_private_ipv6(&sin6->sin6_addr)) return CURL_SOCKET_BAD;
        }
    }
    return socket(address->family, address->socktype, address->protocol);
}

#endif /* KOMPARU_WINDOWS */

/* =========================================================================
 * curl callbacks
 * ========================================================================= */

static size_t async_write_cb(char *ptr, size_t size, size_t nmemb, void *userdata) {
    komparu_async_http_t *h = userdata;
    size_t total = size * nmemb;

    /* Compact if we need space and there's consumed data at front */
    if (h->write_pos + total > h->buf_cap && h->read_pos > 0) {
        size_t avail = h->write_pos - h->read_pos;
        if (avail > 0)
            memmove(h->buf, h->buf + h->read_pos, avail);
        h->write_pos = avail;
        h->read_pos = 0;
    }

    /* Grow if still not enough */
    if (h->write_pos + total > h->buf_cap) {
        size_t new_cap = h->buf_cap ? h->buf_cap * 2 : 65536;
        while (new_cap < h->write_pos + total) {
            if (KOMPARU_UNLIKELY(new_cap > SIZE_MAX / 2)) return 0;
            new_cap *= 2;
        }
        uint8_t *tmp = realloc(h->buf, new_cap);
        if (KOMPARU_UNLIKELY(!tmp)) return 0;
        h->buf = tmp;
        h->buf_cap = new_cap;
    }

    memcpy(h->buf + h->write_pos, ptr, total);
    h->write_pos += total;
    return total;
}

static int async_socket_cb(
    CURL *easy, curl_socket_t s, int what, void *cbp, void *sockp
) {
    (void)easy; (void)sockp;
    komparu_async_http_t *h = cbp;

    if (what == CURL_POLL_REMOVE) {
        h->sock = -1;
        h->sock_events = 0;
    } else {
        h->sock = (int)s;
        h->sock_events = 0;
        if (what & CURL_POLL_IN)  h->sock_events |= KOMPARU_ASYNC_EV_IN;
        if (what & CURL_POLL_OUT) h->sock_events |= KOMPARU_ASYNC_EV_OUT;
    }
    return 0;
}

static int async_timer_cb(CURLM *multi, long timeout_ms, void *cbp) {
    (void)multi;
    komparu_async_http_t *h = cbp;
    h->timer_ms = timeout_ms;
    return 0;
}

/* Check for completed transfers after socket_action */
static void async_check_done(komparu_async_http_t *h) {
    int msgs;
    CURLMsg *msg;
    while ((msg = curl_multi_info_read(h->multi, &msgs)) != NULL) {
        if (msg->msg == CURLMSG_DONE) {
            h->done = true;
            if (msg->data.result != CURLE_OK) {
                h->error = true;
                snprintf(h->errmsg, sizeof(h->errmsg),
                         "HTTP error: %s", curl_easy_strerror(msg->data.result));
            }
            curl_easy_getinfo(h->easy, CURLINFO_RESPONSE_CODE, &h->http_status);
            if (h->content_length < 0) {
                curl_off_t cl = -1;
                curl_easy_getinfo(h->easy, CURLINFO_CONTENT_LENGTH_DOWNLOAD_T, &cl);
                h->content_length = (int64_t)cl;
            }
        }
    }
}

/* =========================================================================
 * Public API
 * ========================================================================= */

komparu_async_http_t *komparu_async_http_open(
    const char *url,
    const char **headers,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    bool allow_private,
    const char **err_msg
) {
    komparu_async_http_t *h = calloc(1, sizeof(*h));
    if (KOMPARU_UNLIKELY(!h)) { *err_msg = "out of memory"; return NULL; }

    h->sock = -1;
    h->timer_ms = -1;
    h->content_length = -1;
    h->allow_private = allow_private;

    h->multi = curl_multi_init();
    if (KOMPARU_UNLIKELY(!h->multi)) {
        *err_msg = "curl_multi_init failed";
        free(h);
        return NULL;
    }

    h->easy = curl_easy_init();
    if (KOMPARU_UNLIKELY(!h->easy)) {
        *err_msg = "curl_easy_init failed";
        curl_multi_cleanup(h->multi);
        free(h);
        return NULL;
    }

    /* Configure easy handle */
    curl_easy_setopt(h->easy, CURLOPT_URL, url);
    curl_easy_setopt(h->easy, CURLOPT_WRITEFUNCTION, async_write_cb);
    curl_easy_setopt(h->easy, CURLOPT_WRITEDATA, h);
    curl_easy_setopt(h->easy, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(h->easy, CURLOPT_PROTOCOLS_STR, "http,https");
    curl_easy_setopt(h->easy, CURLOPT_REDIR_PROTOCOLS_STR, "http,https");

    if (timeout > 0) {
        long ms = (long)(timeout * 1000.0);
        curl_easy_setopt(h->easy, CURLOPT_TIMEOUT_MS, ms);
        curl_easy_setopt(h->easy, CURLOPT_CONNECTTIMEOUT_MS,
                         ms < 10000 ? ms : 10000L);
    }
    if (!verify_ssl) {
        curl_easy_setopt(h->easy, CURLOPT_SSL_VERIFYPEER, 0L);
        curl_easy_setopt(h->easy, CURLOPT_SSL_VERIFYHOST, 0L);
    }
    if (follow_redirects) {
        curl_easy_setopt(h->easy, CURLOPT_FOLLOWLOCATION, 1L);
        curl_easy_setopt(h->easy, CURLOPT_MAXREDIRS, 10L);
    }
    curl_easy_setopt(h->easy, CURLOPT_TCP_KEEPALIVE, 1L);

    /* Custom headers */
    if (headers) {
        for (const char **hp = headers; *hp; hp++)
            h->hdrs = curl_slist_append(h->hdrs, *hp);
        curl_easy_setopt(h->easy, CURLOPT_HTTPHEADER, h->hdrs);
    }

    /* SSRF protection */
#ifndef KOMPARU_WINDOWS
    curl_easy_setopt(h->easy, CURLOPT_OPENSOCKETFUNCTION, async_ssrf_cb);
    curl_easy_setopt(h->easy, CURLOPT_OPENSOCKETDATA, &h->allow_private);
#endif

    /* Set up multi handle callbacks */
    curl_multi_setopt(h->multi, CURLMOPT_SOCKETFUNCTION, async_socket_cb);
    curl_multi_setopt(h->multi, CURLMOPT_SOCKETDATA, h);
    curl_multi_setopt(h->multi, CURLMOPT_TIMERFUNCTION, async_timer_cb);
    curl_multi_setopt(h->multi, CURLMOPT_TIMERDATA, h);

    /* Add easy to multi */
    CURLMcode mc = curl_multi_add_handle(h->multi, h->easy);
    if (KOMPARU_UNLIKELY(mc != CURLM_OK)) {
        *err_msg = curl_multi_strerror(mc);
        curl_easy_cleanup(h->easy);
        curl_multi_cleanup(h->multi);
        if (h->hdrs) curl_slist_free_all(h->hdrs);
        free(h);
        return NULL;
    }

    /* Initial kick — triggers socket/timer callbacks */
    curl_multi_socket_action(h->multi, CURL_SOCKET_TIMEOUT, 0, &h->still_running);
    async_check_done(h);

    return h;
}

int komparu_async_http_fileno(komparu_async_http_t *h) {
    return h->sock;
}

int komparu_async_http_events(komparu_async_http_t *h) {
    return h->sock_events;
}

void komparu_async_http_perform(komparu_async_http_t *h, int fd, int ev_bitmask) {
    int action = 0;
    if (ev_bitmask & KOMPARU_ASYNC_EV_IN)  action |= CURL_CSELECT_IN;
    if (ev_bitmask & KOMPARU_ASYNC_EV_OUT) action |= CURL_CSELECT_OUT;
    curl_multi_socket_action(h->multi, (curl_socket_t)fd, action, &h->still_running);
    async_check_done(h);
}

void komparu_async_http_timeout_perform(komparu_async_http_t *h) {
    curl_multi_socket_action(h->multi, CURL_SOCKET_TIMEOUT, 0, &h->still_running);
    async_check_done(h);
}

long komparu_async_http_timeout_ms(komparu_async_http_t *h) {
    return h->timer_ms;
}

size_t komparu_async_http_read(komparu_async_http_t *h, void *buf, size_t size) {
    size_t avail = h->write_pos - h->read_pos;
    if (avail == 0) return 0;

    size_t n = size < avail ? size : avail;
    memcpy(buf, h->buf + h->read_pos, n);
    h->read_pos += n;

    /* Reset positions when buffer is empty */
    if (h->read_pos == h->write_pos) {
        h->read_pos = 0;
        h->write_pos = 0;
    }
    return n;
}

size_t komparu_async_http_buffered(komparu_async_http_t *h) {
    return h->write_pos - h->read_pos;
}

int64_t komparu_async_http_size(komparu_async_http_t *h) {
    if (h->content_length >= 0) return h->content_length;

    curl_off_t cl = -1;
    curl_easy_getinfo(h->easy, CURLINFO_CONTENT_LENGTH_DOWNLOAD_T, &cl);
    if (cl >= 0) h->content_length = (int64_t)cl;
    return h->content_length;
}

bool komparu_async_http_done(komparu_async_http_t *h) {
    return h->done;
}

const char *komparu_async_http_error(komparu_async_http_t *h) {
    if (!h->error) return NULL;
    return h->errmsg;
}

long komparu_async_http_status(komparu_async_http_t *h) {
    return h->http_status;
}

void komparu_async_http_close(komparu_async_http_t *h) {
    if (!h) return;
    if (h->easy && h->multi)
        curl_multi_remove_handle(h->multi, h->easy);
    if (h->easy) curl_easy_cleanup(h->easy);
    if (h->multi) curl_multi_cleanup(h->multi);
    if (h->hdrs) curl_slist_free_all(h->hdrs);
    free(h->buf);
    free(h);
}
