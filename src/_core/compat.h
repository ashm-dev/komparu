/**
 * compat.h — Python version / platform compatibility macros.
 *
 * Handles:
 * - Python version detection (3.12, 3.13, 3.14+)
 * - Free-threaded build detection (Py_GIL_DISABLED)
 * - GIL release/acquire macros
 * - Platform-specific includes
 */

#ifndef KOMPARU_COMPAT_H
#define KOMPARU_COMPAT_H

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* =========================================================================
 * Python version detection
 * ========================================================================= */

#if PY_VERSION_HEX >= 0x030E0000  /* 3.14+ */
    #define KOMPARU_PY314 1
#endif

#if PY_VERSION_HEX >= 0x030D0000  /* 3.13+ */
    #define KOMPARU_PY313 1
#endif

/* =========================================================================
 * Free-threaded build detection (no-GIL)
 * ========================================================================= */

#ifdef Py_GIL_DISABLED
    #define KOMPARU_FREE_THREADED 1
#endif

/* =========================================================================
 * GIL management macros
 * ========================================================================= */

#ifdef KOMPARU_FREE_THREADED
    /* GIL does not exist in free-threaded builds — no-ops */
    #define KOMPARU_GIL_RELEASE()
    #define KOMPARU_GIL_ACQUIRE()
    #define KOMPARU_GIL_STATE_DECL
#else
    #define KOMPARU_GIL_STATE_DECL   PyThreadState *_komparu_save;
    #define KOMPARU_GIL_RELEASE()    _komparu_save = PyEval_SaveThread();
    #define KOMPARU_GIL_ACQUIRE()    PyEval_RestoreThread(_komparu_save);
#endif

/* =========================================================================
 * Platform detection
 * ========================================================================= */

#ifdef _WIN32
    #define KOMPARU_WINDOWS 1
#elif defined(__APPLE__)
    #define KOMPARU_MACOS 1
#elif defined(__linux__)
    #define KOMPARU_LINUX 1
#endif

/* =========================================================================
 * Platform-specific includes
 * ========================================================================= */

#ifdef KOMPARU_WINDOWS
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>
#else
    #include <unistd.h>
    #include <sys/mman.h>
    #include <sys/stat.h>
    #include <fcntl.h>
    #include <signal.h>
    #include <setjmp.h>
    #include <pthread.h>
#endif

/* =========================================================================
 * Compiler attributes
 * ========================================================================= */

#if defined(__GNUC__) || defined(__clang__)
    #define KOMPARU_UNUSED      __attribute__((unused))
    #define KOMPARU_NOINLINE    __attribute__((noinline))
    #define KOMPARU_LIKELY(x)   __builtin_expect(!!(x), 1)
    #define KOMPARU_UNLIKELY(x) __builtin_expect(!!(x), 0)
#elif defined(_MSC_VER)
    #define KOMPARU_UNUSED
    #define KOMPARU_NOINLINE    __declspec(noinline)
    #define KOMPARU_LIKELY(x)   (x)
    #define KOMPARU_UNLIKELY(x) (x)
#else
    #define KOMPARU_UNUSED
    #define KOMPARU_NOINLINE
    #define KOMPARU_LIKELY(x)   (x)
    #define KOMPARU_UNLIKELY(x) (x)
#endif

/* Default chunk size: 64 KB */
#define KOMPARU_DEFAULT_CHUNK_SIZE  (64 * 1024)

/* Maximum number of default workers */
#define KOMPARU_MAX_DEFAULT_WORKERS 8

#endif /* KOMPARU_COMPAT_H */
