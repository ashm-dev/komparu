/**
 * pool.c — Thread pool for parallel file comparison.
 *
 * Design:
 * - Dynamic task queue (resizable array, ring buffer via head/tail)
 * - Mutex + condvar for synchronization
 * - Active task counter for pool_wait
 * - Graceful shutdown: drain queue, then join workers
 *
 * pthreads on Linux/macOS, Windows threads (CRITICAL_SECTION +
 * CONDITION_VARIABLE) on Windows.
 */

#include "pool.h"
#include <stdlib.h>
#include <string.h>
#ifdef KOMPARU_WINDOWS
#include <process.h>  /* _beginthreadex */
#endif

/* =========================================================================
 * Task queue entry
 * ========================================================================= */

typedef struct {
    komparu_task_fn fn;
    void *arg;
} pool_task_t;

/* =========================================================================
 * Pool structure
 * ========================================================================= */

struct komparu_pool {
    /* Worker threads */
#ifdef KOMPARU_WINDOWS
    HANDLE *threads;
#else
    pthread_t *threads;
#endif
    size_t num_workers;

    /* Task queue (dynamic array, FIFO via head/tail indices) */
    pool_task_t *queue;
    size_t queue_cap;
    size_t queue_head;   /* next task to dequeue */
    size_t queue_tail;   /* next slot to enqueue */
    size_t queue_count;  /* number of pending tasks */

    /* Synchronization */
#ifdef KOMPARU_WINDOWS
    CRITICAL_SECTION mutex;
    CONDITION_VARIABLE task_avail;   /* signaled when a task is added or shutdown */
    CONDITION_VARIABLE all_done;     /* signaled when active_count drops to 0 and queue empty */
#else
    pthread_mutex_t mutex;
    pthread_cond_t task_avail;
    pthread_cond_t all_done;
#endif

    /* Counters */
    size_t active_count;   /* tasks currently being executed */
    bool shutdown;
};

#define INITIAL_QUEUE_CAP 256

/* =========================================================================
 * Platform lock/condvar wrappers — keep main logic clean
 * ========================================================================= */

#ifdef KOMPARU_WINDOWS

#define POOL_LOCK(p)           EnterCriticalSection(&(p)->mutex)
#define POOL_UNLOCK(p)         LeaveCriticalSection(&(p)->mutex)
#define POOL_COND_WAIT(c, p)   SleepConditionVariableCS(&(p)->c, &(p)->mutex, INFINITE)
#define POOL_COND_SIGNAL(c, p) WakeConditionVariable(&(p)->c)
#define POOL_COND_BCAST(c, p)  WakeAllConditionVariable(&(p)->c)

#else

#define POOL_LOCK(p)           pthread_mutex_lock(&(p)->mutex)
#define POOL_UNLOCK(p)         pthread_mutex_unlock(&(p)->mutex)
#define POOL_COND_WAIT(c, p)   pthread_cond_wait(&(p)->c, &(p)->mutex)
#define POOL_COND_SIGNAL(c, p) pthread_cond_signal(&(p)->c)
#define POOL_COND_BCAST(c, p)  pthread_cond_broadcast(&(p)->c)

#endif

/* =========================================================================
 * Worker thread function
 * ========================================================================= */

#ifdef KOMPARU_WINDOWS
static unsigned __stdcall worker_fn(void *arg) {
#else
static void *worker_fn(void *arg) {
#endif
    komparu_pool_t *pool = (komparu_pool_t *)arg;

    for (;;) {
        pool_task_t task;

        POOL_LOCK(pool);

        /* Wait for a task or shutdown */
        while (pool->queue_count == 0 && !pool->shutdown) {
            POOL_COND_WAIT(task_avail, pool);
        }

        if (pool->shutdown && pool->queue_count == 0) {
            POOL_UNLOCK(pool);
#ifdef KOMPARU_WINDOWS
            return 0;
#else
            return NULL;
#endif
        }

        /* Dequeue task */
        task = pool->queue[pool->queue_head];
        pool->queue_head = (pool->queue_head + 1) % pool->queue_cap;
        pool->queue_count--;
        pool->active_count++;

        POOL_UNLOCK(pool);

        /* Execute task */
        task.fn(task.arg);

        /* Signal completion */
        POOL_LOCK(pool);
        pool->active_count--;
        if (pool->active_count == 0 && pool->queue_count == 0) {
            POOL_COND_BCAST(all_done, pool);
        }
        POOL_UNLOCK(pool);
    }
}

/* =========================================================================
 * Public API
 * ========================================================================= */

komparu_pool_t *komparu_pool_create(size_t num_workers) {
    if (num_workers == 0) {
        num_workers = komparu_cpu_count();
        if (num_workers > KOMPARU_MAX_DEFAULT_WORKERS)
            num_workers = KOMPARU_MAX_DEFAULT_WORKERS;
    }

    komparu_pool_t *pool = calloc(1, sizeof(komparu_pool_t));
    if (!pool) return NULL;

    pool->num_workers = num_workers;
    pool->queue_cap = INITIAL_QUEUE_CAP;
    pool->queue = calloc(pool->queue_cap, sizeof(pool_task_t));
    if (!pool->queue) {
        free(pool);
        return NULL;
    }

    /* Init synchronization primitives */
#ifdef KOMPARU_WINDOWS
    InitializeCriticalSection(&pool->mutex);
    InitializeConditionVariable(&pool->task_avail);
    InitializeConditionVariable(&pool->all_done);
#else
    if (pthread_mutex_init(&pool->mutex, NULL) != 0) {
        free(pool->queue);
        free(pool);
        return NULL;
    }
    if (pthread_cond_init(&pool->task_avail, NULL) != 0) {
        pthread_mutex_destroy(&pool->mutex);
        free(pool->queue);
        free(pool);
        return NULL;
    }
    if (pthread_cond_init(&pool->all_done, NULL) != 0) {
        pthread_cond_destroy(&pool->task_avail);
        pthread_mutex_destroy(&pool->mutex);
        free(pool->queue);
        free(pool);
        return NULL;
    }
#endif

    /* Allocate thread handles */
#ifdef KOMPARU_WINDOWS
    pool->threads = calloc(num_workers, sizeof(HANDLE));
#else
    pool->threads = calloc(num_workers, sizeof(pthread_t));
#endif
    if (!pool->threads) {
#ifdef KOMPARU_WINDOWS
        DeleteCriticalSection(&pool->mutex);
#else
        pthread_cond_destroy(&pool->all_done);
        pthread_cond_destroy(&pool->task_avail);
        pthread_mutex_destroy(&pool->mutex);
#endif
        free(pool->queue);
        free(pool);
        return NULL;
    }

    /* Create worker threads */
    for (size_t i = 0; i < num_workers; i++) {
#ifdef KOMPARU_WINDOWS
        pool->threads[i] = (HANDLE)_beginthreadex(NULL, 0, worker_fn, pool, 0, NULL);
        if (!pool->threads[i]) {
#else
        if (pthread_create(&pool->threads[i], NULL, worker_fn, pool) != 0) {
#endif
            /* Shutdown already-created threads */
            POOL_LOCK(pool);
            pool->shutdown = true;
            POOL_COND_BCAST(task_avail, pool);
            POOL_UNLOCK(pool);
            for (size_t j = 0; j < i; j++) {
#ifdef KOMPARU_WINDOWS
                WaitForSingleObject(pool->threads[j], INFINITE);
                CloseHandle(pool->threads[j]);
#else
                pthread_join(pool->threads[j], NULL);
#endif
            }
#ifdef KOMPARU_WINDOWS
            DeleteCriticalSection(&pool->mutex);
#else
            pthread_cond_destroy(&pool->all_done);
            pthread_cond_destroy(&pool->task_avail);
            pthread_mutex_destroy(&pool->mutex);
#endif
            free(pool->threads);
            free(pool->queue);
            free(pool);
            return NULL;
        }
    }

    return pool;
}

int komparu_pool_submit(komparu_pool_t *pool, komparu_task_fn fn, void *arg) {
    POOL_LOCK(pool);

    /* Grow queue if full */
    if (pool->queue_count >= pool->queue_cap) {
        size_t new_cap = pool->queue_cap * 2;
        pool_task_t *new_queue = calloc(new_cap, sizeof(pool_task_t));
        if (!new_queue) {
            POOL_UNLOCK(pool);
            return -1;
        }
        /* Linearize the circular buffer into the new array */
        for (size_t i = 0; i < pool->queue_count; i++) {
            new_queue[i] = pool->queue[(pool->queue_head + i) % pool->queue_cap];
        }
        free(pool->queue);
        pool->queue = new_queue;
        pool->queue_head = 0;
        pool->queue_tail = pool->queue_count;
        pool->queue_cap = new_cap;
    }

    pool->queue[pool->queue_tail] = (pool_task_t){ .fn = fn, .arg = arg };
    pool->queue_tail = (pool->queue_tail + 1) % pool->queue_cap;
    pool->queue_count++;

    POOL_COND_SIGNAL(task_avail, pool);
    POOL_UNLOCK(pool);
    return 0;
}

void komparu_pool_wait(komparu_pool_t *pool) {
    POOL_LOCK(pool);
    while (pool->queue_count > 0 || pool->active_count > 0) {
        POOL_COND_WAIT(all_done, pool);
    }
    POOL_UNLOCK(pool);
}

void komparu_pool_destroy(komparu_pool_t *pool) {
    if (!pool) return;

    /* Wait for pending tasks */
    komparu_pool_wait(pool);

    /* Signal shutdown */
    POOL_LOCK(pool);
    pool->shutdown = true;
    POOL_COND_BCAST(task_avail, pool);
    POOL_UNLOCK(pool);

    /* Join all workers */
    for (size_t i = 0; i < pool->num_workers; i++) {
#ifdef KOMPARU_WINDOWS
        WaitForSingleObject(pool->threads[i], INFINITE);
        CloseHandle(pool->threads[i]);
#else
        pthread_join(pool->threads[i], NULL);
#endif
    }

#ifdef KOMPARU_WINDOWS
    DeleteCriticalSection(&pool->mutex);
#else
    pthread_cond_destroy(&pool->all_done);
    pthread_cond_destroy(&pool->task_avail);
    pthread_mutex_destroy(&pool->mutex);
#endif
    free(pool->threads);
    free(pool->queue);
    free(pool);
}
