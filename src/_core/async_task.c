/**
 * async_task.c — Async task infrastructure for asyncio integration.
 *
 * Uses a global C thread pool for running comparison tasks.
 * Completion notification via eventfd (Linux) or pipe (macOS/other).
 * Python registers the read fd with asyncio.loop.add_reader().
 *
 * No Python code runs in worker threads. No GIL.
 * All I/O (mmap, libcurl easy) happens in pure C.
 */

#include "async_task.h"
#include "reader_file.h"
#include "reader_http.h"
#include "compare.h"
#include "dirwalk.h"
#include "pool.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdatomic.h>

#ifdef KOMPARU_LINUX
#include <sys/eventfd.h>
#endif

/* =========================================================================
 * Task type enum
 * ========================================================================= */

typedef enum {
    KOMPARU_ASYNC_COMPARE,
    KOMPARU_ASYNC_COMPARE_DIR,
} komparu_async_type_t;

/* Task lifecycle states (CAS transitions only):
 *   RUNNING → DONE      (worker finishes normally)
 *   RUNNING → ORPHANED  (Python discards handle before worker finishes)
 * Exactly one side (worker or destructor) owns the free. */
typedef enum {
    KOMPARU_TASK_RUNNING  = 0,  /* zero-init via calloc */
    KOMPARU_TASK_DONE     = 1,
    KOMPARU_TASK_ORPHANED = 2,
} komparu_task_state_t;

/* =========================================================================
 * Task structure
 * ========================================================================= */

struct komparu_async_task {
    komparu_async_type_t type;

    /* Notification fds */
    int read_fd;
    int write_fd;

    /* Common inputs (owned copies) */
    char *source_a;
    char *source_b;
    size_t chunk_size;
    bool size_precheck;
    bool quick_check;

    /* Compare-specific */
    char **headers;          /* NULL-terminated owned copy */
    size_t header_count;
    double timeout;
    bool follow_redirects;
    bool verify_ssl;
    bool allow_private;

    /* Dir-specific */
    bool follow_symlinks;
    size_t max_workers;

    /* Output */
    komparu_result_t cmp_result;
    komparu_dir_result_t *dir_result;
    char error_buf[512];
    bool has_error;

    /* Lifecycle state (CAS-only transitions, see komparu_task_state_t) */
    _Atomic int state;
};

/* =========================================================================
 * Notification fd — eventfd (Linux) or pipe (portable)
 * ========================================================================= */

static int notify_create(int *read_fd, int *write_fd) {
#ifdef KOMPARU_LINUX
    int efd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (efd < 0) return -1;
    *read_fd = efd;
    *write_fd = efd;
    return 0;
#else
    int fds[2];
    if (pipe(fds) != 0) return -1;
    fcntl(fds[0], F_SETFL, O_NONBLOCK);
    fcntl(fds[1], F_SETFL, O_NONBLOCK);
    fcntl(fds[0], F_SETFD, FD_CLOEXEC);
    fcntl(fds[1], F_SETFD, FD_CLOEXEC);
    *read_fd = fds[0];
    *write_fd = fds[1];
    return 0;
#endif
}

static void notify_signal(int write_fd) {
#ifdef KOMPARU_LINUX
    uint64_t val = 1;
    while (write(write_fd, &val, sizeof(val)) < 0 && errno == EINTR);
#else
    char c = 1;
    while (write(write_fd, &c, 1) < 0 && errno == EINTR);
#endif
}

static void notify_close(int read_fd, int write_fd) {
    if (read_fd >= 0) close(read_fd);
    if (write_fd >= 0 && write_fd != read_fd) close(write_fd);
}

/* =========================================================================
 * Global async pool — lazily initialized
 * ========================================================================= */

static _Atomic(komparu_pool_t *) g_async_pool = NULL;
static pthread_mutex_t g_pool_mutex = PTHREAD_MUTEX_INITIALIZER;

static komparu_pool_t *get_pool(void) {
    komparu_pool_t *pool = atomic_load_explicit(&g_async_pool, memory_order_acquire);
    if (pool) return pool;
    pthread_mutex_lock(&g_pool_mutex);
    pool = atomic_load_explicit(&g_async_pool, memory_order_relaxed);
    if (!pool) {
        pool = komparu_pool_create(0);  /* auto-detect workers */
        atomic_store_explicit(&g_async_pool, pool, memory_order_release);
    }
    pthread_mutex_unlock(&g_pool_mutex);
    return pool;
}

/* =========================================================================
 * URL detection
 * ========================================================================= */

static bool is_url(const char *s) {
    return (strncmp(s, "http://", 7) == 0 ||
            strncmp(s, "https://", 8) == 0);
}

static void task_free_internals(komparu_async_task_t *task);

/* =========================================================================
 * Worker completion: signal done + self-free if orphaned
 * ========================================================================= */

static void worker_finish(komparu_async_task_t *task) {
    int expected = KOMPARU_TASK_RUNNING;
    if (atomic_compare_exchange_strong_explicit(&task->state, &expected,
            KOMPARU_TASK_DONE, memory_order_acq_rel, memory_order_acquire)) {
        /* Normal completion — Python will read result and free. */
        notify_signal(task->write_fd);
    } else {
        /* ORPHANED: Python discarded the handle. We own the memory. */
        task_free_internals(task);
        free(task);
    }
}

/* =========================================================================
 * Worker: file/URL comparison
 * ========================================================================= */

static void compare_worker(void *arg) {
    komparu_async_task_t *task = (komparu_async_task_t *)arg;
    const char *err = NULL;

    /* Open reader A */
    komparu_reader_t *ra;
    if (is_url(task->source_a)) {
        ra = komparu_reader_http_open_ex(
            task->source_a,
            (const char **)task->headers,
            task->timeout, task->follow_redirects,
            task->verify_ssl, task->allow_private, &err);
    } else {
        ra = komparu_reader_file_open(task->source_a, &err);
    }
    if (KOMPARU_UNLIKELY(!ra)) {
        snprintf(task->error_buf, sizeof(task->error_buf),
                 "cannot open '%s': %s", task->source_a,
                 err ? err : "unknown error");
        task->has_error = true;
        worker_finish(task);
        return;
    }

    /* Open reader B */
    komparu_reader_t *rb;
    if (is_url(task->source_b)) {
        rb = komparu_reader_http_open_ex(
            task->source_b,
            (const char **)task->headers,
            task->timeout, task->follow_redirects,
            task->verify_ssl, task->allow_private, &err);
    } else {
        rb = komparu_reader_file_open(task->source_b, &err);
    }
    if (KOMPARU_UNLIKELY(!rb)) {
        ra->close(ra);
        snprintf(task->error_buf, sizeof(task->error_buf),
                 "cannot open '%s': %s", task->source_b,
                 err ? err : "unknown error");
        task->has_error = true;
        worker_finish(task);
        return;
    }

    /* Quick check */
    if (task->quick_check) {
        komparu_result_t qr = komparu_quick_check(
            ra, rb, task->chunk_size, &err);
        if (qr == KOMPARU_DIFFERENT) {
            task->cmp_result = KOMPARU_DIFFERENT;
            ra->close(ra);
            rb->close(rb);
            worker_finish(task);
            return;
        }
        if (qr == KOMPARU_ERROR && ra->seek && rb->seek) {
            ra->seek(ra, 0);
            rb->seek(rb, 0);
        }
    }

    /* Full compare */
    task->cmp_result = komparu_compare(
        ra, rb, task->chunk_size, task->size_precheck, &err);

    if (task->cmp_result == KOMPARU_ERROR) {
        snprintf(task->error_buf, sizeof(task->error_buf),
                 "comparison error: %s", err ? err : "unknown");
        task->has_error = true;
    }

    ra->close(ra);
    rb->close(rb);
    worker_finish(task);
}

/* =========================================================================
 * Worker: directory comparison
 * ========================================================================= */

static void compare_dir_worker(void *arg) {
    komparu_async_task_t *task = (komparu_async_task_t *)arg;
    const char *err = NULL;

    task->dir_result = komparu_compare_dirs(
        task->source_a, task->source_b,
        task->chunk_size, task->size_precheck,
        task->quick_check, task->follow_symlinks,
        task->max_workers, &err);

    if (!task->dir_result) {
        snprintf(task->error_buf, sizeof(task->error_buf),
                 "directory comparison failed: %s",
                 err ? err : "unknown error");
        task->has_error = true;
    }

    worker_finish(task);
}

/* =========================================================================
 * Allocate and init a task
 * ========================================================================= */

static komparu_async_task_t *task_alloc(
    komparu_async_type_t type,
    const char *source_a,
    const char *source_b,
    const char **err_msg
) {
    komparu_async_task_t *task = calloc(1, sizeof(*task));
    if (!task) {
        *err_msg = "out of memory";
        return NULL;
    }

    task->type = type;
    task->read_fd = -1;
    task->write_fd = -1;
    task->cmp_result = KOMPARU_ERROR;

    if (notify_create(&task->read_fd, &task->write_fd) != 0) {
        *err_msg = "failed to create notification fd";
        free(task);
        return NULL;
    }

    task->source_a = strdup(source_a);
    task->source_b = strdup(source_b);
    if (!task->source_a || !task->source_b) {
        *err_msg = "out of memory";
        task_free_internals(task);
        free(task);
        return NULL;
    }

    return task;
}

/* =========================================================================
 * Public API
 * ========================================================================= */

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
) {
    komparu_pool_t *pool = get_pool();
    if (!pool) {
        *err_msg = "failed to create async pool";
        return NULL;
    }

    komparu_async_task_t *task = task_alloc(
        KOMPARU_ASYNC_COMPARE, source_a, source_b, err_msg);
    if (!task) return NULL;

    /* Copy headers */
    if (headers) {
        size_t count = 0;
        while (headers[count]) count++;
        if (count > 0) {
            task->headers = calloc(count + 1, sizeof(char *));
            if (!task->headers) {
                *err_msg = "out of memory";
                task_free_internals(task);
                free(task);
                return NULL;
            }
            for (size_t i = 0; i < count; i++) {
                task->headers[i] = strdup(headers[i]);
                if (!task->headers[i]) {
                    *err_msg = "out of memory";
                    task_free_internals(task);
                    free(task);
                    return NULL;
                }
            }
            task->header_count = count;
        }
    }

    task->chunk_size = chunk_size ? chunk_size : KOMPARU_DEFAULT_CHUNK_SIZE;
    task->size_precheck = size_precheck;
    task->quick_check = quick_check;
    task->timeout = timeout > 0 ? timeout : 30.0;
    task->follow_redirects = follow_redirects;
    task->verify_ssl = verify_ssl;
    task->allow_private = allow_private;

    if (komparu_pool_submit(pool, compare_worker, task) != 0) {
        *err_msg = "async pool queue full";
        task_free_internals(task);
        free(task);
        return NULL;
    }

    return task;
}

komparu_async_task_t *komparu_async_compare_dir(
    const char *dir_a,
    const char *dir_b,
    size_t chunk_size,
    bool size_precheck,
    bool quick_check,
    bool follow_symlinks,
    size_t max_workers,
    const char **err_msg
) {
    komparu_pool_t *pool = get_pool();
    if (!pool) {
        *err_msg = "failed to create async pool";
        return NULL;
    }

    komparu_async_task_t *task = task_alloc(
        KOMPARU_ASYNC_COMPARE_DIR, dir_a, dir_b, err_msg);
    if (!task) return NULL;

    task->chunk_size = chunk_size ? chunk_size : KOMPARU_DEFAULT_CHUNK_SIZE;
    task->size_precheck = size_precheck;
    task->quick_check = quick_check;
    task->follow_symlinks = follow_symlinks;
    task->max_workers = max_workers;

    if (komparu_pool_submit(pool, compare_dir_worker, task) != 0) {
        *err_msg = "async pool queue full";
        task_free_internals(task);
        free(task);
        return NULL;
    }

    return task;
}

int komparu_async_task_fd(komparu_async_task_t *task) {
    return task->read_fd;
}

int komparu_async_task_cmp_result(
    komparu_async_task_t *task,
    bool *out,
    const char **err_msg
) {
    /* Acquire barrier: see all writes from the worker thread. */
    (void)atomic_load_explicit(&task->state, memory_order_acquire);
    if (task->has_error) {
        *err_msg = task->error_buf;
        return -1;
    }
    *out = (task->cmp_result == KOMPARU_EQUAL);
    return 0;
}

komparu_dir_result_t *komparu_async_task_dir_result(
    komparu_async_task_t *task,
    const char **err_msg
) {
    /* Acquire barrier: see all writes from the worker thread. */
    (void)atomic_load_explicit(&task->state, memory_order_acquire);
    if (task->has_error) {
        *err_msg = task->error_buf;
        return NULL;
    }
    komparu_dir_result_t *r = task->dir_result;
    task->dir_result = NULL;  /* transfer ownership */
    return r;
}

/** Free internal resources of a task (does NOT free the task struct). */
static void task_free_internals(komparu_async_task_t *task) {
    notify_close(task->read_fd, task->write_fd);
    free(task->source_a);
    free(task->source_b);
    if (task->headers) {
        for (size_t i = 0; i < task->header_count; i++)
            free(task->headers[i]);
        free(task->headers);
    }
    if (task->dir_result)
        komparu_dir_result_free(task->dir_result);
}

void komparu_async_task_free(komparu_async_task_t *task) {
    if (!task) return;

    int state = atomic_load_explicit(&task->state, memory_order_acquire);
    if (state == KOMPARU_TASK_DONE) {
        task_free_internals(task);
        free(task);
        return;
    }

    /* Task still running — try to orphan. Worker will free on completion. */
    int expected = KOMPARU_TASK_RUNNING;
    if (atomic_compare_exchange_strong_explicit(&task->state, &expected,
            KOMPARU_TASK_ORPHANED, memory_order_acq_rel, memory_order_acquire)) {
        return;  /* Worker owns the memory now */
    }

    /* CAS failed: worker finished between our load and CAS. Free now. */
    task_free_internals(task);
    free(task);
}

void komparu_async_cleanup(void) {
    pthread_mutex_lock(&g_pool_mutex);
    komparu_pool_t *pool = atomic_load_explicit(&g_async_pool, memory_order_relaxed);
    if (pool) {
        komparu_pool_wait(pool);
        komparu_pool_destroy(pool);
        atomic_store_explicit(&g_async_pool, NULL, memory_order_release);
    }
    pthread_mutex_unlock(&g_pool_mutex);
}
