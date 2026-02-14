/**
 * pool.c — Thread pool for parallel file comparison.
 *
 * Stub for Phase 1. Full implementation in Phase 4.
 */

#include "pool.h"
#include <stdlib.h>

komparu_pool_t *komparu_pool_create(size_t num_workers) {
    (void)num_workers;
    return NULL; /* Not yet implemented */
}

int komparu_pool_submit(komparu_pool_t *pool, komparu_task_fn fn, void *arg) {
    (void)pool;
    (void)fn;
    (void)arg;
    return -1;
}

void komparu_pool_wait(komparu_pool_t *pool) {
    (void)pool;
}

void komparu_pool_destroy(komparu_pool_t *pool) {
    (void)pool;
}
