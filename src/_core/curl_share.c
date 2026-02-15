/**
 * curl_share.c — CURLSH share interface for connection/DNS/TLS reuse.
 *
 * Global CURLSH* with per-lock-data mutexes for thread-safe sharing of:
 * - DNS cache (avoid repeated DNS lookups to the same host)
 * - Connection pool (reuse TCP/TLS connections across easy handles)
 * - TLS session cache (TLS session resumption, skip full handshake)
 *
 * Locking strategy: one mutex per curl_lock_data type for maximum concurrency.
 * POSIX uses pthread_mutex_t, Windows uses SRWLOCK (static init, no cleanup).
 */

#include "curl_share.h"
#include "compat.h"

/*
 * curl_lock_data values we need to cover:
 *   CURL_LOCK_DATA_DNS           = 2
 *   CURL_LOCK_DATA_CONNECT       = 5
 *   CURL_LOCK_DATA_SSL_SESSION   = 4
 *   CURL_LOCK_DATA_COOKIE        = 1
 *   CURL_LOCK_DATA_PSL           = 6
 *
 * Allocate enough mutexes to index by curl_lock_data directly.
 * CURL_LOCK_DATA_LAST (or a safe upper bound) covers all values.
 */
#define SHARE_LOCK_COUNT 8  /* covers all curl_lock_data values (0..7) */

/* =========================================================================
 * Platform-specific mutex array
 * ========================================================================= */

#ifdef KOMPARU_WINDOWS

static SRWLOCK share_locks[SHARE_LOCK_COUNT] = {
    SRWLOCK_INIT, SRWLOCK_INIT, SRWLOCK_INIT, SRWLOCK_INIT,
    SRWLOCK_INIT, SRWLOCK_INIT, SRWLOCK_INIT, SRWLOCK_INIT,
};

static void lock_cb(CURL *handle, curl_lock_data data,
                    curl_lock_access access, void *userptr)
{
    (void)handle;
    (void)access;
    (void)userptr;
    if ((int)data < SHARE_LOCK_COUNT)
        AcquireSRWLockExclusive(&share_locks[(int)data]);
}

static void unlock_cb(CURL *handle, curl_lock_data data, void *userptr)
{
    (void)handle;
    (void)userptr;
    if ((int)data < SHARE_LOCK_COUNT)
        ReleaseSRWLockExclusive(&share_locks[(int)data]);
}

#else /* POSIX */

static pthread_mutex_t share_locks[SHARE_LOCK_COUNT];
static bool locks_initialized = false;

static void lock_cb(CURL *handle, curl_lock_data data,
                    curl_lock_access access, void *userptr)
{
    (void)handle;
    (void)access;
    (void)userptr;
    if ((int)data < SHARE_LOCK_COUNT)
        pthread_mutex_lock(&share_locks[(int)data]);
}

static void unlock_cb(CURL *handle, curl_lock_data data, void *userptr)
{
    (void)handle;
    (void)userptr;
    if ((int)data < SHARE_LOCK_COUNT)
        pthread_mutex_unlock(&share_locks[(int)data]);
}

#endif

/* =========================================================================
 * Global share handle
 * ========================================================================= */

static CURLSH *g_share = NULL;

int komparu_curl_share_init(void) {
    if (g_share)
        return 0;  /* already initialized */

#ifndef KOMPARU_WINDOWS
    /* Initialize POSIX mutexes */
    for (int i = 0; i < SHARE_LOCK_COUNT; i++) {
        if (pthread_mutex_init(&share_locks[i], NULL) != 0) {
            /* Cleanup already-initialized mutexes */
            for (int j = 0; j < i; j++)
                pthread_mutex_destroy(&share_locks[j]);
            return -1;
        }
    }
    locks_initialized = true;
#endif

    g_share = curl_share_init();
    if (!g_share) {
#ifndef KOMPARU_WINDOWS
        for (int i = 0; i < SHARE_LOCK_COUNT; i++)
            pthread_mutex_destroy(&share_locks[i]);
        locks_initialized = false;
#endif
        return -1;
    }

    /* Set lock callbacks */
    curl_share_setopt(g_share, CURLSHOPT_LOCKFUNC, lock_cb);
    curl_share_setopt(g_share, CURLSHOPT_UNLOCKFUNC, unlock_cb);

    /* Share DNS cache, connection pool, and TLS sessions */
    curl_share_setopt(g_share, CURLSHOPT_SHARE, CURL_LOCK_DATA_DNS);
    curl_share_setopt(g_share, CURLSHOPT_SHARE, CURL_LOCK_DATA_CONNECT);
    curl_share_setopt(g_share, CURLSHOPT_SHARE, CURL_LOCK_DATA_SSL_SESSION);

    return 0;
}

void komparu_curl_share_cleanup(void) {
    if (g_share) {
        curl_share_cleanup(g_share);
        g_share = NULL;
    }

#ifndef KOMPARU_WINDOWS
    if (locks_initialized) {
        for (int i = 0; i < SHARE_LOCK_COUNT; i++)
            pthread_mutex_destroy(&share_locks[i]);
        locks_initialized = false;
    }
#endif
}

CURLSH *komparu_curl_share_get(void) {
    return g_share;
}
