/**
 * reader_file.h — Local file reader with mmap (Unix) / ReadFile (Windows).
 *
 * Includes SIGBUS protection for mmap on Unix.
 */

#ifndef KOMPARU_READER_FILE_H
#define KOMPARU_READER_FILE_H

#include "reader.h"

/**
 * Initialize SIGBUS handler for mmap safety.
 * Must be called once during module init.
 * Thread-safe: uses per-thread sigjmp_buf.
 *
 * Returns 0 on success, -1 if sigaction fails.
 */
int komparu_sigbus_init(void);

#endif /* KOMPARU_READER_FILE_H */
