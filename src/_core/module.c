/**
 * module.c — CPython extension entry point for komparu._core.
 *
 * Exposes C comparison functions to Python.
 * Handles GIL release/acquire and free-threaded builds.
 * Auto-detects URL vs local file path.
 */

#include "module.h"
#include "compare.h"
#include "reader_file.h"
#include "reader_http.h"
#include "curl_share.h"
#include "dirwalk.h"
#include "reader_archive.h"
#include "async_task.h"
#include <string.h>
#include <stdlib.h>

/* =========================================================================
 * URL detection — check if source is an HTTP(S) URL
 * ========================================================================= */

static bool is_url(const char *source) {
    return (strncmp(source, "http://", 7) == 0 ||
            strncmp(source, "https://", 8) == 0);
}

/* =========================================================================
 * Convert Python dict to NULL-terminated C header array.
 * Must be called with GIL held. Caller must free with free_header_array().
 * ========================================================================= */

static const char **build_header_array(
    PyObject *py_headers,
    size_t *out_count,
    const char **err_msg
) {
    *out_count = 0;
    if (!py_headers || py_headers == Py_None || !PyDict_Check(py_headers))
        return NULL;

    size_t count = (size_t)PyDict_Size(py_headers);
    if (count == 0) return NULL;

    const char **arr = calloc(count + 1, sizeof(const char *));
    if (!arr) {
        *err_msg = "out of memory for headers";
        return NULL;
    }

    PyObject *key, *value;
    Py_ssize_t pos = 0;
    size_t idx = 0;
    while (PyDict_Next(py_headers, &pos, &key, &value)) {
        const char *k = PyUnicode_AsUTF8(key);
        const char *v = PyUnicode_AsUTF8(value);
        if (!k || !v) {
            for (size_t j = 0; j < idx; j++) free((void *)arr[j]);
            free(arr);
            *err_msg = "header keys and values must be strings";
            return NULL;
        }
        /* Reject CRLF in headers to prevent header injection */
        if (strpbrk(k, "\r\n") || strpbrk(v, "\r\n")) {
            for (size_t j = 0; j < idx; j++) free((void *)arr[j]);
            free(arr);
            *err_msg = "header keys/values must not contain CR/LF";
            return NULL;
        }
        size_t len = strlen(k) + strlen(v) + 3;
        char *hdr = malloc(len);
        if (!hdr) {
            for (size_t j = 0; j < idx; j++) free((void *)arr[j]);
            free(arr);
            *err_msg = "out of memory for header string";
            return NULL;
        }
        snprintf(hdr, len, "%s: %s", k, v);
        arr[idx++] = hdr;
    }
    arr[idx] = NULL;
    *out_count = idx;
    return arr;
}

static void free_header_array(const char **arr, size_t count) {
    if (!arr) return;
    for (size_t i = 0; i < count; i++) free((void *)arr[i]);
    free(arr);
}

/* =========================================================================
 * Open a reader based on source type (file or HTTP).
 * Pure C — no Python API calls. Safe to call without GIL.
 * ========================================================================= */

static komparu_reader_t *open_reader(
    const char *source,
    const char **header_array,  /* NULL-terminated C array or NULL */
    double timeout,
    int follow_redirects,
    int verify_ssl,
    int allow_private,
    const char *proxy,
    const char **err_msg
) {
    if (is_url(source)) {
        return komparu_reader_http_open_ex(
            source, header_array,
            timeout, (bool)follow_redirects, (bool)verify_ssl,
            (bool)allow_private, proxy,
            err_msg
        );
    }

    /* Local file */
    return komparu_reader_file_open(source, err_msg);
}

/* =========================================================================
 * Python wrapper: compare(source_a, source_b, ...) -> bool
 * ========================================================================= */

static PyObject *py_compare(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *source_a = NULL;
    const char *source_b = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    int size_precheck = 1;
    int quick_check = 1;
    PyObject *py_headers = Py_None;
    double timeout = 30.0;
    int follow_redirects = 1;
    int verify_ssl = 1;
    int allow_private = 0;
    const char *proxy = NULL;

    static char *kwlist[] = {
        "source_a", "source_b", "chunk_size", "size_precheck", "quick_check",
        "headers", "timeout", "follow_redirects", "verify_ssl", "allow_private",
        "proxy", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|nppOdpppz", kwlist,
            &source_a, &source_b, &chunk_size, &size_precheck, &quick_check,
            &py_headers, &timeout, &follow_redirects, &verify_ssl,
            &allow_private, &proxy)) {
        return NULL;
    }

    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk_size must be positive");
        return NULL;
    }

    /* Validate headers type */
    if (py_headers != Py_None && !PyDict_Check(py_headers)) {
        PyErr_SetString(PyExc_TypeError, "headers must be a dict or None");
        return NULL;
    }

    /* Convert Python headers to C array while GIL is held */
    const char *err_msg = NULL;
    size_t header_count = 0;
    const char **header_array = build_header_array(py_headers, &header_count, &err_msg);
    if (err_msg) {
        /* build_header_array failed (OOM or bad types) */
        PyErr_SetString(PyExc_ValueError, err_msg);
        return NULL;
    }

    /* Copy source strings — PyArg strings are only valid while GIL is held */
    char *src_a = strdup(source_a);
    char *src_b = strdup(source_b);
    char *proxy_copy = proxy ? strdup(proxy) : NULL;
    if (!src_a || !src_b || (proxy && !proxy_copy)) {
        free(src_a);
        free(src_b);
        free(proxy_copy);
        free_header_array(header_array, header_count);
        PyErr_NoMemory();
        return NULL;
    }

    bool src_a_is_url = is_url(src_a);
    bool src_b_is_url = is_url(src_b);

    /*
     * Release GIL for ALL I/O work: open_reader does curl_easy_perform
     * (HEAD request) which blocks. If GIL is held, Python-threaded test
     * servers (werkzeug/pytest_httpserver) deadlock.
     */
    komparu_result_t result;
    komparu_reader_t *reader_a = NULL;
    komparu_reader_t *reader_b = NULL;

    KOMPARU_GIL_STATE_DECL
    KOMPARU_GIL_RELEASE()

    reader_a = open_reader(
        src_a, header_array, timeout, follow_redirects, verify_ssl, allow_private, proxy_copy, &err_msg
    );
    if (!reader_a) goto open_failed;

    reader_b = open_reader(
        src_b, header_array, timeout, follow_redirects, verify_ssl, allow_private, proxy_copy, &err_msg
    );
    if (!reader_b) goto open_failed;

    /* Optional quick check */
    if (quick_check) {
        result = komparu_quick_check(reader_a, reader_b,
                                     (size_t)chunk_size, &err_msg);
        if (result == KOMPARU_DIFFERENT) {
            goto done;
        }
        /* EQUAL from quick_check = samples match, still need full compare */
        /* ERROR = seek not supported — reset to start before full compare */
        if (result == KOMPARU_ERROR && reader_a->seek && reader_b->seek) {
            reader_a->seek(reader_a, 0);
            reader_b->seek(reader_b, 0);
        }
    }

    result = komparu_compare(reader_a, reader_b,
                             (size_t)chunk_size, (bool)size_precheck,
                             &err_msg);
    goto done;

open_failed:
    result = KOMPARU_ERROR;

done:
    KOMPARU_GIL_ACQUIRE()

    /* Cleanup */
    if (reader_a) reader_a->close(reader_a);
    if (reader_b) reader_b->close(reader_b);
    free_header_array(header_array, header_count);
    free(proxy_copy);

    /* Convert result to Python */
    switch (result) {
        case KOMPARU_EQUAL:
            free(src_a);
            free(src_b);
            Py_RETURN_TRUE;
        case KOMPARU_DIFFERENT:
            free(src_a);
            free(src_b);
            Py_RETURN_FALSE;
        case KOMPARU_ERROR:
            if (!reader_a) {
                if (src_a_is_url) {
                    PyErr_Format(PyExc_IOError, "cannot open '%s': %s",
                                 src_a, err_msg ? err_msg : "unknown error");
                } else {
                    PyErr_Format(PyExc_FileNotFoundError, "cannot open '%s': %s",
                                 src_a, err_msg ? err_msg : "unknown error");
                }
            } else if (!reader_b) {
                if (src_b_is_url) {
                    PyErr_Format(PyExc_IOError, "cannot open '%s': %s",
                                 src_b, err_msg ? err_msg : "unknown error");
                } else {
                    PyErr_Format(PyExc_FileNotFoundError, "cannot open '%s': %s",
                                 src_b, err_msg ? err_msg : "unknown error");
                }
            } else {
                PyErr_Format(PyExc_IOError, "comparison error: %s",
                             err_msg ? err_msg : "unknown");
            }
            free(src_a);
            free(src_b);
            return NULL;
        default:
            free(src_a);
            free(src_b);
            PyErr_SetString(PyExc_RuntimeError, "unexpected comparison result");
            return NULL;
    }
}

/* =========================================================================
 * Convert C dir_result_t to Python dict.
 * Must be called with GIL held.
 * ========================================================================= */

static const char *diff_reason_str(int reason) {
    switch (reason) {
        case KOMPARU_DIFF_CONTENT: return "content_mismatch";
        case KOMPARU_DIFF_SIZE:    return "size_mismatch";
        case KOMPARU_DIFF_READ_ERROR: return "read_error";
        default: return "unknown";
    }
}

static PyObject *dir_result_to_python(komparu_dir_result_t *r) {
    PyObject *dict = PyDict_New();
    if (!dict) return NULL;

    /* equal */
    PyObject *equal = r->equal ? Py_True : Py_False;
    if (PyDict_SetItemString(dict, "equal", equal) < 0) goto fail;

    /* diff: dict[str, str] */
    {
        PyObject *diff = PyDict_New();
        if (!diff) goto fail;
        for (size_t i = 0; i < r->diff_count; i++) {
            PyObject *key = PyUnicode_FromString(r->diffs[i].path);
            PyObject *val = PyUnicode_FromString(diff_reason_str(r->diffs[i].reason));
            if (!key || !val || PyDict_SetItem(diff, key, val) < 0) {
                Py_XDECREF(key);
                Py_XDECREF(val);
                Py_DECREF(diff);
                goto fail;
            }
            Py_DECREF(key);
            Py_DECREF(val);
        }
        if (PyDict_SetItemString(dict, "diff", diff) < 0) {
            Py_DECREF(diff);
            goto fail;
        }
        Py_DECREF(diff);
    }

    /* only_left: set[str] */
    {
        PyObject *ol = PySet_New(NULL);
        if (!ol) goto fail;
        for (size_t i = 0; i < r->only_left_count; i++) {
            PyObject *s = PyUnicode_FromString(r->only_left[i]);
            if (!s || PySet_Add(ol, s) < 0) {
                Py_XDECREF(s);
                Py_DECREF(ol);
                goto fail;
            }
            Py_DECREF(s);
        }
        if (PyDict_SetItemString(dict, "only_left", ol) < 0) {
            Py_DECREF(ol);
            goto fail;
        }
        Py_DECREF(ol);
    }

    /* only_right: set[str] */
    {
        PyObject *or_set = PySet_New(NULL);
        if (!or_set) goto fail;
        for (size_t i = 0; i < r->only_right_count; i++) {
            PyObject *s = PyUnicode_FromString(r->only_right[i]);
            if (!s || PySet_Add(or_set, s) < 0) {
                Py_XDECREF(s);
                Py_DECREF(or_set);
                goto fail;
            }
            Py_DECREF(s);
        }
        if (PyDict_SetItemString(dict, "only_right", or_set) < 0) {
            Py_DECREF(or_set);
            goto fail;
        }
        Py_DECREF(or_set);
    }

    return dict;

fail:
    Py_DECREF(dict);
    return NULL;
}

/* =========================================================================
 * Python wrapper: compare_dir(dir_a, dir_b, ...) -> dict
 * ========================================================================= */

static PyObject *py_compare_dir(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *dir_a = NULL;
    const char *dir_b = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    int size_precheck = 1;
    int quick_check = 1;
    int follow_symlinks = 1;
    Py_ssize_t max_workers = 0;  /* 0 = auto */

    static char *kwlist[] = {
        "dir_a", "dir_b", "chunk_size", "size_precheck",
        "quick_check", "follow_symlinks", "max_workers", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|npppn", kwlist,
            &dir_a, &dir_b, &chunk_size, &size_precheck,
            &quick_check, &follow_symlinks, &max_workers)) {
        return NULL;
    }

    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk_size must be positive");
        return NULL;
    }

    char *da = strdup(dir_a);
    char *db = strdup(dir_b);
    if (!da || !db) {
        free(da);
        free(db);
        PyErr_NoMemory();
        return NULL;
    }

    const char *err_msg = NULL;
    komparu_dir_result_t *result;

    KOMPARU_GIL_STATE_DECL
    KOMPARU_GIL_RELEASE()

    result = komparu_compare_dirs(da, db,
        (size_t)chunk_size, (bool)size_precheck,
        (bool)quick_check, (bool)follow_symlinks,
        (size_t)(max_workers >= 0 ? max_workers : 0),
        &err_msg);

    KOMPARU_GIL_ACQUIRE()

    free(da);
    free(db);

    if (!result) {
        PyErr_Format(PyExc_IOError, "directory comparison failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    PyObject *py_result = dir_result_to_python(result);
    komparu_dir_result_free(result);
    return py_result;
}

/* =========================================================================
 * Python wrapper: compare_archive(path_a, path_b, ...) -> dict
 * ========================================================================= */

static PyObject *py_compare_archive(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *path_a = NULL;
    const char *path_b = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    long long max_decompressed_size = -1;  /* -1 = use default */
    int max_compression_ratio = -1;
    long long max_entries = -1;
    long long max_entry_name_length = -1;
    int hash_compare = 0;

    static char *kwlist[] = {
        "path_a", "path_b", "chunk_size",
        "max_decompressed_size", "max_compression_ratio",
        "max_entries", "max_entry_name_length", "hash_compare", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|nLiLLp", kwlist,
            &path_a, &path_b, &chunk_size,
            &max_decompressed_size, &max_compression_ratio,
            &max_entries, &max_entry_name_length, &hash_compare)) {
        return NULL;
    }

    char *pa = strdup(path_a);
    char *pb = strdup(path_b);
    if (!pa || !pb) {
        free(pa);
        free(pb);
        PyErr_NoMemory();
        return NULL;
    }

    /* Apply defaults for -1 values */
    int64_t mds = max_decompressed_size >= 0 ? (int64_t)max_decompressed_size : 0;
    int mcr = max_compression_ratio >= 0 ? max_compression_ratio : 0;
    int64_t me = max_entries >= 0 ? (int64_t)max_entries : 0;
    int64_t menl = max_entry_name_length >= 0 ? (int64_t)max_entry_name_length : 0;

    const char *err_msg = NULL;
    komparu_dir_result_t *result;

    KOMPARU_GIL_STATE_DECL
    KOMPARU_GIL_RELEASE()

    if (hash_compare) {
        result = komparu_compare_archives_hashed(pa, pb,
            mds, mcr, me, menl, NULL, &err_msg);
    } else {
        result = komparu_compare_archives(pa, pb,
            (size_t)chunk_size, mds, mcr, me, menl, &err_msg);
    }

    KOMPARU_GIL_ACQUIRE()

    free(pa);
    free(pb);

    if (!result) {
        PyErr_Format(PyExc_IOError, "archive comparison failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    PyObject *py_result = dir_result_to_python(result);
    komparu_dir_result_free(result);
    return py_result;
}

/* =========================================================================
 * Python wrapper: compare_buffers(buf_a, buf_b) -> bool
 * ========================================================================= */

static PyObject *py_compare_buffers(PyObject *self, PyObject *args) {
    (void)self;

    Py_buffer buf_a, buf_b;
    if (!PyArg_ParseTuple(args, "y*y*", &buf_a, &buf_b)) {
        return NULL;
    }

    bool equal;
    if (buf_a.len != buf_b.len) {
        equal = false;
    } else if (buf_a.len == 0) {
        equal = true;
    } else {
        equal = (memcmp(buf_a.buf, buf_b.buf, (size_t)buf_a.len) == 0);
    }

    PyBuffer_Release(&buf_a);
    PyBuffer_Release(&buf_b);

    if (equal) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

/* =========================================================================
 * Async task wrappers — C pool + eventfd/pipe for asyncio integration
 * ========================================================================= */

static void async_task_capsule_destructor(PyObject *capsule) {
    komparu_async_task_t *task = PyCapsule_GetPointer(capsule, "komparu.async_task");
    if (task) komparu_async_task_free(task);
}

static PyObject *py_async_compare_start(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *source_a = NULL;
    const char *source_b = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    int size_precheck = 1;
    int quick_check = 1;
    PyObject *py_headers = Py_None;
    double timeout = 30.0;
    int follow_redirects = 1;
    int verify_ssl = 1;
    int allow_private = 0;
    const char *proxy = NULL;

    static char *kwlist[] = {
        "source_a", "source_b", "chunk_size", "size_precheck", "quick_check",
        "headers", "timeout", "follow_redirects", "verify_ssl", "allow_private",
        "proxy", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|nppOdpppz", kwlist,
            &source_a, &source_b, &chunk_size, &size_precheck, &quick_check,
            &py_headers, &timeout, &follow_redirects, &verify_ssl,
            &allow_private, &proxy)) {
        return NULL;
    }

    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk_size must be positive");
        return NULL;
    }

    if (py_headers != Py_None && !PyDict_Check(py_headers)) {
        PyErr_SetString(PyExc_TypeError, "headers must be a dict or None");
        return NULL;
    }

    /* Build header array while GIL is held */
    const char *err_msg = NULL;
    size_t header_count = 0;
    const char **header_array = build_header_array(py_headers, &header_count, &err_msg);
    if (err_msg) {
        PyErr_SetString(PyExc_ValueError, err_msg);
        return NULL;
    }

    /* Submit async task — runs in C pool, no GIL */
    komparu_async_task_t *task = komparu_async_compare(
        source_a, source_b, header_array,
        (size_t)chunk_size, (bool)size_precheck, (bool)quick_check,
        timeout, (bool)follow_redirects, (bool)verify_ssl, (bool)allow_private,
        proxy, &err_msg
    );

    free_header_array(header_array, header_count);

    if (!task) {
        PyErr_Format(PyExc_RuntimeError, "async compare failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    int fd = komparu_async_task_fd(task);
    PyObject *capsule = PyCapsule_New(task, "komparu.async_task",
                                      async_task_capsule_destructor);
    if (!capsule) {
        komparu_async_task_free(task);
        return NULL;
    }

    return Py_BuildValue("(iN)", fd, capsule);
}

static PyObject *py_async_compare_result(PyObject *self, PyObject *arg) {
    (void)self;

    komparu_async_task_t *task = PyCapsule_GetPointer(arg, "komparu.async_task");
    if (!task) {
        PyErr_SetString(PyExc_ValueError, "invalid async task handle");
        return NULL;
    }

    const char *err_msg = NULL;
    bool result;
    if (komparu_async_task_cmp_result(task, &result, &err_msg) != 0) {
        PyErr_Format(PyExc_IOError, "%s", err_msg ? err_msg : "unknown error");
        return NULL;
    }

    if (result) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject *py_async_compare_dir_start(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *dir_a = NULL;
    const char *dir_b = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    int size_precheck = 1;
    int quick_check = 1;
    int follow_symlinks = 1;
    Py_ssize_t max_workers = 0;

    static char *kwlist[] = {
        "dir_a", "dir_b", "chunk_size", "size_precheck",
        "quick_check", "follow_symlinks", "max_workers", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|npppn", kwlist,
            &dir_a, &dir_b, &chunk_size, &size_precheck,
            &quick_check, &follow_symlinks, &max_workers)) {
        return NULL;
    }

    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk_size must be positive");
        return NULL;
    }

    const char *err_msg = NULL;
    komparu_async_task_t *task = komparu_async_compare_dir(
        dir_a, dir_b,
        (size_t)chunk_size, (bool)size_precheck, (bool)quick_check,
        (bool)follow_symlinks,
        (size_t)(max_workers >= 0 ? max_workers : 0),
        &err_msg
    );

    if (!task) {
        PyErr_Format(PyExc_RuntimeError, "async compare_dir failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    int fd = komparu_async_task_fd(task);
    PyObject *capsule = PyCapsule_New(task, "komparu.async_task",
                                      async_task_capsule_destructor);
    if (!capsule) {
        komparu_async_task_free(task);
        return NULL;
    }

    return Py_BuildValue("(iN)", fd, capsule);
}

static PyObject *py_async_compare_dir_result(PyObject *self, PyObject *arg) {
    (void)self;

    komparu_async_task_t *task = PyCapsule_GetPointer(arg, "komparu.async_task");
    if (!task) {
        PyErr_SetString(PyExc_ValueError, "invalid async task handle");
        return NULL;
    }

    const char *err_msg = NULL;
    komparu_dir_result_t *result = komparu_async_task_dir_result(task, &err_msg);
    if (!result) {
        PyErr_Format(PyExc_IOError, "directory comparison failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    PyObject *py_result = dir_result_to_python(result);
    komparu_dir_result_free(result);
    return py_result;
}

/* =========================================================================
 * Async archive comparison
 * ========================================================================= */

static PyObject *py_async_compare_archive_start(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *path_a = NULL;
    const char *path_b = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    long long max_decompressed_size = -1;
    int max_compression_ratio = -1;
    long long max_entries = -1;
    long long max_entry_name_length = -1;
    int hash_compare = 0;

    static char *kwlist[] = {
        "path_a", "path_b", "chunk_size",
        "max_decompressed_size", "max_compression_ratio",
        "max_entries", "max_entry_name_length", "hash_compare", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|nLiLLp", kwlist,
            &path_a, &path_b, &chunk_size,
            &max_decompressed_size, &max_compression_ratio,
            &max_entries, &max_entry_name_length, &hash_compare)) {
        return NULL;
    }

    int64_t mds = max_decompressed_size >= 0 ? (int64_t)max_decompressed_size : 0;
    int mcr = max_compression_ratio >= 0 ? max_compression_ratio : 0;
    int64_t me = max_entries >= 0 ? (int64_t)max_entries : 0;
    int64_t menl = max_entry_name_length >= 0 ? (int64_t)max_entry_name_length : 0;

    const char *err_msg = NULL;
    komparu_async_task_t *task = komparu_async_compare_archive(
        path_a, path_b, (size_t)chunk_size,
        mds, mcr, me, menl, hash_compare, &err_msg);

    if (!task) {
        PyErr_Format(PyExc_RuntimeError, "async compare_archive failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    int fd = komparu_async_task_fd(task);
    PyObject *capsule = PyCapsule_New(task, "komparu.async_task",
                                      async_task_capsule_destructor);
    if (!capsule) {
        komparu_async_task_free(task);
        return NULL;
    }

    return Py_BuildValue("(iN)", fd, capsule);
}

static PyObject *py_async_compare_archive_result(PyObject *self, PyObject *arg) {
    (void)self;

    komparu_async_task_t *task = PyCapsule_GetPointer(arg, "komparu.async_task");
    if (!task) {
        PyErr_SetString(PyExc_ValueError, "invalid async task handle");
        return NULL;
    }

    const char *err_msg = NULL;
    komparu_dir_result_t *result = komparu_async_task_dir_result(task, &err_msg);
    if (!result) {
        PyErr_Format(PyExc_IOError, "archive comparison failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    PyObject *py_result = dir_result_to_python(result);
    komparu_dir_result_free(result);
    return py_result;
}

/* =========================================================================
 * Async dir_urls comparison
 * ========================================================================= */

static PyObject *py_async_compare_dir_urls_start(PyObject *self, PyObject *args, PyObject *kwargs) {
    (void)self;

    const char *dir_path = NULL;
    PyObject *py_url_map = NULL;
    Py_ssize_t chunk_size = KOMPARU_DEFAULT_CHUNK_SIZE;
    int size_precheck = 1;
    int quick_check = 1;
    PyObject *py_headers = Py_None;
    double timeout = 30.0;
    int follow_redirects = 1;
    int verify_ssl = 1;
    int allow_private = 0;
    const char *proxy = NULL;

    static char *kwlist[] = {
        "dir_path", "url_map", "chunk_size", "size_precheck", "quick_check",
        "headers", "timeout", "follow_redirects", "verify_ssl", "allow_private",
        "proxy", NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "sO|nppOdpppz", kwlist,
            &dir_path, &py_url_map, &chunk_size, &size_precheck, &quick_check,
            &py_headers, &timeout, &follow_redirects, &verify_ssl,
            &allow_private, &proxy)) {
        return NULL;
    }

    if (!PyDict_Check(py_url_map)) {
        PyErr_SetString(PyExc_TypeError, "url_map must be a dict");
        return NULL;
    }

    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk_size must be positive");
        return NULL;
    }

    /* Convert url_map dict to parallel C arrays */
    Py_ssize_t map_size = PyDict_Size(py_url_map);
    const char **rel_paths = NULL;
    const char **url_strs = NULL;

    if (map_size > 0) {
        rel_paths = calloc((size_t)map_size, sizeof(const char *));
        url_strs = calloc((size_t)map_size, sizeof(const char *));
        if (!rel_paths || !url_strs) {
            free(rel_paths);
            free(url_strs);
            PyErr_NoMemory();
            return NULL;
        }

        PyObject *key, *value;
        Py_ssize_t pos = 0;
        Py_ssize_t idx = 0;
        while (PyDict_Next(py_url_map, &pos, &key, &value)) {
            rel_paths[idx] = PyUnicode_AsUTF8(key);
            url_strs[idx] = PyUnicode_AsUTF8(value);
            if (!rel_paths[idx] || !url_strs[idx]) {
                free(rel_paths);
                free(url_strs);
                PyErr_SetString(PyExc_TypeError, "url_map keys and values must be strings");
                return NULL;
            }
            idx++;
        }
    }

    /* Build headers */
    const char *err_msg = NULL;
    size_t header_count = 0;
    const char **header_array = build_header_array(py_headers, &header_count, &err_msg);
    if (err_msg) {
        free(rel_paths);
        free(url_strs);
        PyErr_SetString(PyExc_ValueError, err_msg);
        return NULL;
    }

    komparu_async_task_t *task = komparu_async_compare_dir_urls(
        dir_path, rel_paths, url_strs, (size_t)map_size,
        header_array,
        (size_t)chunk_size, (bool)size_precheck, (bool)quick_check,
        timeout, (bool)follow_redirects, (bool)verify_ssl, (bool)allow_private,
        proxy, &err_msg);

    free(rel_paths);
    free(url_strs);
    free_header_array(header_array, header_count);

    if (!task) {
        PyErr_Format(PyExc_RuntimeError, "async compare_dir_urls failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    int fd = komparu_async_task_fd(task);
    PyObject *capsule = PyCapsule_New(task, "komparu.async_task",
                                      async_task_capsule_destructor);
    if (!capsule) {
        komparu_async_task_free(task);
        return NULL;
    }

    return Py_BuildValue("(iN)", fd, capsule);
}

static PyObject *py_async_compare_dir_urls_result(PyObject *self, PyObject *arg) {
    (void)self;

    komparu_async_task_t *task = PyCapsule_GetPointer(arg, "komparu.async_task");
    if (!task) {
        PyErr_SetString(PyExc_ValueError, "invalid async task handle");
        return NULL;
    }

    const char *err_msg = NULL;
    komparu_dir_result_t *result = komparu_async_task_dir_result(task, &err_msg);
    if (!result) {
        PyErr_Format(PyExc_IOError, "dir_urls comparison failed: %s",
                     err_msg ? err_msg : "unknown error");
        return NULL;
    }

    PyObject *py_result = dir_result_to_python(result);
    komparu_dir_result_free(result);
    return py_result;
}

/* =========================================================================
 * Module definition
 * ========================================================================= */

static PyMethodDef module_methods[] = {
    {
        "compare",
        (PyCFunction)(void(*)(void))py_compare,
        METH_VARARGS | METH_KEYWORDS,
        "compare(source_a, source_b, *, chunk_size=65536, size_precheck=True, "
        "quick_check=True, headers=None, timeout=30.0, follow_redirects=True, "
        "verify_ssl=True) -> bool\n\n"
        "Compare two sources byte-by-byte. Sources can be file paths or HTTP(S) URLs.\n"
        "Returns True if sources are identical, False otherwise."
    },
    {
        "compare_dir",
        (PyCFunction)(void(*)(void))py_compare_dir,
        METH_VARARGS | METH_KEYWORDS,
        "compare_dir(dir_a, dir_b, *, chunk_size=65536, size_precheck=True, "
        "quick_check=True, follow_symlinks=True) -> dict\n\n"
        "Compare two directories recursively.\n"
        "Returns dict with equal, diff, only_left, only_right."
    },
    {
        "compare_archive",
        (PyCFunction)(void(*)(void))py_compare_archive,
        METH_VARARGS | METH_KEYWORDS,
        "compare_archive(path_a, path_b, *, chunk_size=65536, hash_compare=False) -> dict\n\n"
        "Compare two archive files entry-by-entry.\n"
        "hash_compare: use streaming hash (O(entries) memory).\n"
        "Returns dict with equal, diff, only_left, only_right."
    },
    {
        "compare_buffers",
        (PyCFunction)py_compare_buffers,
        METH_VARARGS,
        "compare_buffers(buf_a, buf_b) -> bool\n\n"
        "Compare two bytes-like objects via memcmp.\n"
        "Returns True if identical, False otherwise."
    },
    /* Async — C pool + eventfd/pipe for asyncio integration */
    {
        "async_compare_start",
        (PyCFunction)(void(*)(void))py_async_compare_start,
        METH_VARARGS | METH_KEYWORDS,
        "async_compare_start(source_a, source_b, ...) -> (fd, task)\n\n"
        "Submit async comparison to C pool. Returns (notification_fd, task_capsule)."
    },
    {
        "async_compare_result",
        (PyCFunction)py_async_compare_result,
        METH_O,
        "async_compare_result(task) -> bool\n\n"
        "Get result of async comparison. Call after fd is readable."
    },
    {
        "async_compare_dir_start",
        (PyCFunction)(void(*)(void))py_async_compare_dir_start,
        METH_VARARGS | METH_KEYWORDS,
        "async_compare_dir_start(dir_a, dir_b, ...) -> (fd, task)\n\n"
        "Submit async directory comparison. Returns (notification_fd, task_capsule)."
    },
    {
        "async_compare_dir_result",
        (PyCFunction)py_async_compare_dir_result,
        METH_O,
        "async_compare_dir_result(task) -> dict\n\n"
        "Get result of async directory comparison. Call after fd is readable."
    },
    {
        "async_compare_archive_start",
        (PyCFunction)(void(*)(void))py_async_compare_archive_start,
        METH_VARARGS | METH_KEYWORDS,
        "async_compare_archive_start(path_a, path_b, ...) -> (fd, task)\n\n"
        "Submit async archive comparison. Returns (notification_fd, task_capsule)."
    },
    {
        "async_compare_archive_result",
        (PyCFunction)py_async_compare_archive_result,
        METH_O,
        "async_compare_archive_result(task) -> dict\n\n"
        "Get result of async archive comparison. Call after fd is readable."
    },
    {
        "async_compare_dir_urls_start",
        (PyCFunction)(void(*)(void))py_async_compare_dir_urls_start,
        METH_VARARGS | METH_KEYWORDS,
        "async_compare_dir_urls_start(dir_path, url_map, ...) -> (fd, task)\n\n"
        "Submit async dir-vs-URL-map comparison. Returns (notification_fd, task_capsule)."
    },
    {
        "async_compare_dir_urls_result",
        (PyCFunction)py_async_compare_dir_urls_result,
        METH_O,
        "async_compare_dir_urls_result(task) -> dict\n\n"
        "Get result of async dir_urls comparison. Call after fd is readable."
    },
    {NULL, NULL, 0, NULL}
};

/* Module slots for multi-phase init */
static struct PyModuleDef_Slot module_slots[] = {
#ifdef KOMPARU_FREE_THREADED
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
#endif
    {0, NULL}
};

static struct PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_core",
    .m_doc = "komparu C23 core — ultra-fast file comparison engine.",
    .m_size = 0,
    .m_methods = module_methods,
    .m_slots = module_slots,
};

PyMODINIT_FUNC PyInit__core(void) {
    /* Initialize SIGBUS handler for mmap safety */
    if (komparu_sigbus_init() != 0) {
        PyErr_SetString(PyExc_RuntimeError,
                        "failed to install SIGBUS handler");
        return NULL;
    }

    /* Initialize libcurl */
    if (komparu_curl_global_init() != 0) {
        PyErr_SetString(PyExc_RuntimeError,
                        "failed to initialize libcurl");
        return NULL;
    }

    /* Initialize curl share handle for DNS/connection/TLS reuse */
    if (komparu_curl_share_init() != 0) {
        PyErr_SetString(PyExc_RuntimeError,
                        "failed to initialize curl share handle");
        return NULL;
    }
    Py_AtExit(komparu_curl_share_cleanup);
    Py_AtExit(komparu_compare_tls_cleanup);

    return PyModuleDef_Init(&module_def);
}
