/**
 * pool.h — Thread pool for parallel file comparison.
 *
 * Lock-free ring buffer task queue with worker threads.
 * pthreads on Linux/macOS, Windows threads on Windows.
 */

#ifndef KOMPARU_POOL_H
#define KOMPARU_POOL_H

#include "compat.h"

/* Forward declaration */
typedef struct komparu_pool komparu_pool_t;

/** Task function signature. */
typedef void (*komparu_task_fn)(void *arg);

/**
 * Create a thread pool with `num_workers` threads.
 * If num_workers == 0, uses min(CPU cores, KOMPARU_MAX_DEFAULT_WORKERS).
 *
 * Returns NULL on error.
 */
komparu_pool_t *komparu_pool_create(size_t num_workers);

/**
 * Submit a task to the pool.
 *
 * Returns 0 on success, -1 if queue is full.
 */
int komparu_pool_submit(komparu_pool_t *pool, komparu_task_fn fn, void *arg);

/**
 * Wait for all submitted tasks to complete.
 */
void komparu_pool_wait(komparu_pool_t *pool);

/**
 * Destroy the pool. Waits for pending tasks, then joins all threads.
 */
void komparu_pool_destroy(komparu_pool_t *pool);

#endif /* KOMPARU_POOL_H */
