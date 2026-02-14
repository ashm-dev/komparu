/**
 * module.h — CPython extension module interface.
 */

#ifndef KOMPARU_MODULE_H
#define KOMPARU_MODULE_H

#include "compat.h"

/* Module initialization function — called by Python import machinery */
PyMODINIT_FUNC PyInit__core(void);

#endif /* KOMPARU_MODULE_H */
