/**
 * pool.c — Thread pool for parallel file comparison.
 *
 * Design:
 * - Dynamic task queue (resizable array, not ring buffer)
 * - Mutex + condvar for synchronization
 * - Active task counter for pool_wait
 * - Graceful shutdown: drain queue, then join workers
 *
 * pthreads on Linux/macOS. Windows support via compat.h (future).
 */

#include "pool.h"
#include <stdlib.h>
#include <string.h>

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
    pthread_t *threads;
    size_t num_workers;

    /* Task queue (dynamic array, FIFO via head/tail indices) */
    pool_task_t *queue;
    size_t queue_cap;
    size_t queue_head;   /* next task to dequeue */
    size_t queue_tail;   /* next slot to enqueue */
    size_t queue_count;  /* number of pending tasks */

    /* Synchronization */
    pthread_mutex_t mutex;
    pthread_cond_t task_avail;   /* signaled when a task is added or shutdown */
    pthread_cond_t all_done;     /* signaled when active_count drops to 0 and queue empty */

    /* Counters */
    size_t active_count;   /* tasks currently being executed */
    bool shutdown;
};

#define INITIAL_QUEUE_CAP 256

/* =========================================================================
 * Worker thread function
 * ========================================================================= */

static void *worker_fn(void *arg) {
    komparu_pool_t *pool = (komparu_pool_t *)arg;

    for (;;) {
        pool_task_t task;

        pthread_mutex_lock(&pool->mutex);

        /* Wait for a task or shutdown */
        while (pool->queue_count == 0 && !pool->shutdown) {
            pthread_cond_wait(&pool->task_avail, &pool->mutex);
        }

        if (pool->shutdown && pool->queue_count == 0) {
            pthread_mutex_unlock(&pool->mutex);
            return NULL;
        }

        /* Dequeue task */
        task = pool->queue[pool->queue_head];
        pool->queue_head = (pool->queue_head + 1) % pool->queue_cap;
        pool->queue_count--;
        pool->active_count++;

        pthread_mutex_unlock(&pool->mutex);

        /* Execute task */
        task.fn(task.arg);

        /* Signal completion */
        pthread_mutex_lock(&pool->mutex);
        pool->active_count--;
        if (pool->active_count == 0 && pool->queue_count == 0) {
            pthread_cond_broadcast(&pool->all_done);
        }
        pthread_mutex_unlock(&pool->mutex);
    }
}

/* =========================================================================
 * Public API
 * ========================================================================= */

komparu_pool_t *komparu_pool_create(size_t num_workers) {
    if (num_workers == 0) {
        long ncpu = sysconf(_SC_NPROCESSORS_ONLN);
        if (ncpu < 1) ncpu = 1;
        num_workers = (size_t)ncpu;
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

    pool->threads = calloc(num_workers, sizeof(pthread_t));
    if (!pool->threads) {
        pthread_cond_destroy(&pool->all_done);
        pthread_cond_destroy(&pool->task_avail);
        pthread_mutex_destroy(&pool->mutex);
        free(pool->queue);
        free(pool);
        return NULL;
    }

    for (size_t i = 0; i < num_workers; i++) {
        if (pthread_create(&pool->threads[i], NULL, worker_fn, pool) != 0) {
            /* Shutdown already-created threads */
            pthread_mutex_lock(&pool->mutex);
            pool->shutdown = true;
            pthread_cond_broadcast(&pool->task_avail);
            pthread_mutex_unlock(&pool->mutex);
            for (size_t j = 0; j < i; j++)
                pthread_join(pool->threads[j], NULL);
            pthread_cond_destroy(&pool->all_done);
            pthread_cond_destroy(&pool->task_avail);
            pthread_mutex_destroy(&pool->mutex);
            free(pool->threads);
            free(pool->queue);
            free(pool);
            return NULL;
        }
    }

    return pool;
}

int komparu_pool_submit(komparu_pool_t *pool, komparu_task_fn fn, void *arg) {
    pthread_mutex_lock(&pool->mutex);

    /* Grow queue if full */
    if (pool->queue_count >= pool->queue_cap) {
        size_t new_cap = pool->queue_cap * 2;
        pool_task_t *new_queue = calloc(new_cap, sizeof(pool_task_t));
        if (!new_queue) {
            pthread_mutex_unlock(&pool->mutex);
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

    pthread_cond_signal(&pool->task_avail);
    pthread_mutex_unlock(&pool->mutex);
    return 0;
}

void komparu_pool_wait(komparu_pool_t *pool) {
    pthread_mutex_lock(&pool->mutex);
    while (pool->queue_count > 0 || pool->active_count > 0) {
        pthread_cond_wait(&pool->all_done, &pool->mutex);
    }
    pthread_mutex_unlock(&pool->mutex);
}

void komparu_pool_destroy(komparu_pool_t *pool) {
    if (!pool) return;

    /* Wait for pending tasks */
    komparu_pool_wait(pool);

    /* Signal shutdown */
    pthread_mutex_lock(&pool->mutex);
    pool->shutdown = true;
    pthread_cond_broadcast(&pool->task_avail);
    pthread_mutex_unlock(&pool->mutex);

    /* Join all workers */
    for (size_t i = 0; i < pool->num_workers; i++) {
        pthread_join(pool->threads[i], NULL);
    }

    pthread_cond_destroy(&pool->all_done);
    pthread_cond_destroy(&pool->task_avail);
    pthread_mutex_destroy(&pool->mutex);
    free(pool->threads);
    free(pool->queue);
    free(pool);
}
