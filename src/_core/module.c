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
#include <string.h>

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
    const char **err_msg
) {
    if (is_url(source)) {
        return komparu_reader_http_open_ex(
            source, header_array,
            timeout, (bool)follow_redirects, (bool)verify_ssl,
            (bool)allow_private,
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

    static char *kwlist[] = {
        "source_a", "source_b", "chunk_size", "size_precheck", "quick_check",
        "headers", "timeout", "follow_redirects", "verify_ssl", "allow_private",
        NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|nppOdppp", kwlist,
            &source_a, &source_b, &chunk_size, &size_precheck, &quick_check,
            &py_headers, &timeout, &follow_redirects, &verify_ssl,
            &allow_private)) {
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
    if (!src_a || !src_b) {
        free(src_a);
        free(src_b);
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
        src_a, header_array, timeout, follow_redirects, verify_ssl, allow_private, &err_msg
    );
    if (!reader_a) goto open_failed;

    reader_b = open_reader(
        src_b, header_array, timeout, follow_redirects, verify_ssl, allow_private, &err_msg
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
        /* ERROR = seek not supported, fall through to full compare */
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

    return PyModuleDef_Init(&module_def);
}
