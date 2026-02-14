/**
 * module.c — CPython extension entry point for komparu._core.
 *
 * Exposes C comparison functions to Python.
 * Handles GIL release/acquire and free-threaded builds.
 */

#include "module.h"
#include "compare.h"
#include "reader_file.h"
#include "reader_http.h"

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

    static char *kwlist[] = {
        "source_a", "source_b", "chunk_size", "size_precheck", "quick_check",
        NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "ss|npp", kwlist,
            &source_a, &source_b, &chunk_size, &size_precheck, &quick_check)) {
        return NULL;
    }

    if (chunk_size <= 0) {
        PyErr_SetString(PyExc_ValueError, "chunk_size must be positive");
        return NULL;
    }

    /* Open readers */
    const char *err_msg = NULL;
    komparu_reader_t *reader_a = komparu_reader_file_open(source_a, &err_msg);
    if (!reader_a) {
        PyErr_Format(PyExc_FileNotFoundError, "cannot open '%s': %s",
                     source_a, err_msg ? err_msg : "unknown error");
        return NULL;
    }

    komparu_reader_t *reader_b = komparu_reader_file_open(source_b, &err_msg);
    if (!reader_b) {
        reader_a->close(reader_a);
        PyErr_Format(PyExc_FileNotFoundError, "cannot open '%s': %s",
                     source_b, err_msg ? err_msg : "unknown error");
        return NULL;
    }

    /* Release GIL for C I/O work */
    komparu_result_t result;

    KOMPARU_GIL_STATE_DECL
    KOMPARU_GIL_RELEASE()

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

done:
    KOMPARU_GIL_ACQUIRE()

    /* Cleanup readers */
    reader_a->close(reader_a);
    reader_b->close(reader_b);

    /* Convert result to Python */
    switch (result) {
        case KOMPARU_EQUAL:
            Py_RETURN_TRUE;
        case KOMPARU_DIFFERENT:
            Py_RETURN_FALSE;
        case KOMPARU_ERROR:
            PyErr_Format(PyExc_IOError, "comparison error: %s",
                         err_msg ? err_msg : "unknown");
            return NULL;
        default:
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
        "quick_check=True) -> bool\n\n"
        "Compare two local files byte-by-byte.\n"
        "Returns True if files are identical, False otherwise."
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
