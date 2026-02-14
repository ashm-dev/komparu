/**
 * async_task.h — Async task infrastructure for asyncio integration.
 *
 * Submits comparison work to a C thread pool. Completion is signaled
 * via eventfd (Linux) or pipe (macOS) — Python registers the read fd
 * with asyncio.loop.add_reader() for non-blocking notification.
 *
 * No Python code runs in worker threads. No GIL involvement.
 * All I/O (file mmap, libcurl) happens in pure C.
 */

#ifndef KOMPARU_ASYNC_TASK_H
#define KOMPARU_ASYNC_TASK_H

#include "compat.h"
#include "compare.h"

typedef struct komparu_async_task komparu_async_task_t;

/**
 * Submit an async file/URL comparison.
 *
 * The comparison runs entirely in a C pool worker thread.
 * Returns a task handle; caller monitors task_fd() with asyncio,
 * then reads the result with task_cmp_result().
 *
 * headers: NULL-terminated "Key: Value" array (copied), or NULL.
 * Returns NULL on error (pool full, OOM).
 */
komparu_async_task_t *komparu_async_compare(
    const char *source_a,
    const char *source_b,
    const char **headers,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    double timeout,
    bool follow_redirects,
    bool verify_ssl,
    bool allow_private,
    const char **err_msg
);

/**
 * Submit an async directory comparison.
 *
 * Internally uses komparu_compare_dirs() which has its own parallelism.
 * Returns NULL on error.
 */
komparu_async_task_t *komparu_async_compare_dir(
    const char *dir_a,
    const char *dir_b,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    bool follow_symlinks,
    size_t max_workers,
    const char **err_msg
);

/** Get the read fd for asyncio.loop.add_reader(). */
int komparu_async_task_fd(komparu_async_task_t *task);

/**
 * Get comparison result. Call only after fd is readable.
 * Returns 0 on success (*out set), -1 on error (*err_msg set).
 */
int komparu_async_task_cmp_result(
    komparu_async_task_t *task,
    bool *out,
    const char **err_msg
);

/**
 * Get directory comparison result. Call only after fd is readable.
 * Returns result (caller owns), or NULL on error.
 */
komparu_dir_result_t *komparu_async_task_dir_result(
    komparu_async_task_t *task,
    const char **err_msg
);

/**
 * Free the task. If task is still running, blocks until completion.
 */
void komparu_async_task_free(komparu_async_task_t *task);

/** Cleanup global async pool (call at module teardown). */
void komparu_async_cleanup(void);

#endif /* KOMPARU_ASYNC_TASK_H */
