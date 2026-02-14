/**
 * reader_file.c — Local file reader with mmap (Unix) / ReadFile (Windows).
 *
 * Includes SIGBUS protection: if a file is truncated while mmap'd,
 * we catch SIGBUS via sigaction + sigsetjmp/siglongjmp and convert
 * it to a read error instead of crashing the Python interpreter.
 */

#include "reader_file.h"
#include <string.h>
#include <stdlib.h>
#include <errno.h>

/* Thread-safe error message buffer */
static _Thread_local char komparu_errbuf[256];

/* =========================================================================
 * SIGBUS protection (Unix only)
 * ========================================================================= */

#ifndef KOMPARU_WINDOWS

/**
 * Per-thread jump buffer for SIGBUS recovery.
 * Thread-local ensures safety in multi-threaded comparisons.
 */
static _Thread_local sigjmp_buf sigbus_jmpbuf;
static _Thread_local volatile sig_atomic_t sigbus_armed = 0;

/**
 * SIGBUS signal handler.
 * If armed, longjmp back to the read function.
 * If not armed, re-raise with default handler (crash).
 */
static void sigbus_handler(int sig, siginfo_t *info, void *ucontext) {
    (void)info;
    (void)ucontext;

    if (sigbus_armed) {
        int saved_errno = errno;
        sigbus_armed = 0;
        errno = saved_errno;
        siglongjmp(sigbus_jmpbuf, 1);
    }

    /* Not armed — this is a real crash. Restore default and re-raise. */
    signal(SIGBUS, SIG_DFL);
    raise(sig);
}

int komparu_sigbus_init(void) {
    struct sigaction sa;
    sa.sa_sigaction = sigbus_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_SIGINFO;

    if (sigaction(SIGBUS, &sa, NULL) != 0) {
        return -1;
    }
    return 0;
}

#else /* KOMPARU_WINDOWS */

int komparu_sigbus_init(void) {
    /* Windows doesn't have SIGBUS — SEH handles page faults */
    return 0;
}

#endif /* KOMPARU_WINDOWS */

/* =========================================================================
 * File reader context
 * ========================================================================= */

#ifndef KOMPARU_WINDOWS

typedef struct {
    int fd;
    void *mapped;       /* mmap base address, or NULL if using read() */
    int64_t file_size;
    int64_t offset;     /* Current read position */
    char source[1024];  /* Source path for error messages */
} file_ctx_t;

/* ---- read via mmap ---- */

static int64_t file_read_mmap(komparu_reader_t *self, void *buf, size_t size) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;

    if (ctx->offset >= ctx->file_size) {
        return 0; /* EOF */
    }

    size_t remaining = (size_t)(ctx->file_size - ctx->offset);
    size_t to_read = (size < remaining) ? size : remaining;

    /* Arm SIGBUS protection before accessing mmap'd memory */
    sigbus_armed = 1;
    if (sigsetjmp(sigbus_jmpbuf, 1) != 0) {
        /* SIGBUS caught — file was truncated under us */
        sigbus_armed = 0;
        return -1;
    }

    memcpy(buf, (const char *)ctx->mapped + ctx->offset, to_read);
    sigbus_armed = 0;

    ctx->offset += (int64_t)to_read;
    return (int64_t)to_read;
}

static int64_t file_get_size(komparu_reader_t *self) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;
    return ctx->file_size;
}

static int file_seek(komparu_reader_t *self, int64_t offset) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;
    if (offset < 0 || offset > ctx->file_size) {
        return -1;
    }
    ctx->offset = offset;
    return 0;
}

static void file_close_mmap(komparu_reader_t *self) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;
    if (ctx->mapped != MAP_FAILED && ctx->mapped != NULL) {
        munmap(ctx->mapped, (size_t)ctx->file_size);
    }
    if (ctx->fd >= 0) {
        close(ctx->fd);
    }
    free(ctx);
    free(self);
}

/* ---- read via read() fallback ---- */

static int64_t file_read_fallback(komparu_reader_t *self, void *buf, size_t size) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;
    ssize_t n = read(ctx->fd, buf, size);
    if (n < 0) {
        return -1;
    }
    ctx->offset += n;
    return (int64_t)n;
}

static int file_seek_fallback(komparu_reader_t *self, int64_t offset) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;
    off_t result = lseek(ctx->fd, (off_t)offset, SEEK_SET);
    if (result == (off_t)-1) {
        return -1;
    }
    ctx->offset = offset;
    return 0;
}

static void file_close_fallback(komparu_reader_t *self) {
    file_ctx_t *ctx = (file_ctx_t *)self->ctx;
    if (ctx->fd >= 0) {
        close(ctx->fd);
    }
    free(ctx);
    free(self);
}

/* ---- constructor ---- */

komparu_reader_t *komparu_reader_file_open(const char *path, const char **err_msg) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        strerror_r(errno, komparu_errbuf, sizeof(komparu_errbuf));
        *err_msg = komparu_errbuf;
        return NULL;
    }

    struct stat st;
    if (fstat(fd, &st) != 0) {
        strerror_r(errno, komparu_errbuf, sizeof(komparu_errbuf));
        *err_msg = komparu_errbuf;
        close(fd);
        return NULL;
    }

    /* Reject non-regular files (directories, devices, pipes, sockets) */
    if (!S_ISREG(st.st_mode)) {
        *err_msg = "not a regular file";
        close(fd);
        return NULL;
    }

    /* Allocate reader + context */
    komparu_reader_t *reader = calloc(1, sizeof(komparu_reader_t));
    file_ctx_t *ctx = calloc(1, sizeof(file_ctx_t));
    if (!reader || !ctx) {
        *err_msg = "out of memory";
        free(reader);
        free(ctx);
        close(fd);
        return NULL;
    }

    ctx->fd = fd;
    ctx->file_size = (int64_t)st.st_size;
    ctx->offset = 0;
    snprintf(ctx->source, sizeof(ctx->source), "%s", path);

    reader->ctx = ctx;
    reader->source_name = ctx->source;
    reader->get_size = file_get_size;

    /* Try mmap for non-empty files */
    if (st.st_size > 0) {
        void *mapped = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
        if (mapped != MAP_FAILED) {
            /* Advise sequential access */
            madvise(mapped, (size_t)st.st_size, MADV_SEQUENTIAL);
            ctx->mapped = mapped;
            reader->read = file_read_mmap;
            reader->seek = file_seek;
            reader->close = file_close_mmap;
            return reader;
        }
        /* mmap failed — fall through to read() */
    }

    /* Fallback: buffered read() */
    ctx->mapped = NULL;
    reader->read = file_read_fallback;
    reader->seek = file_seek_fallback;
    reader->close = file_close_fallback;
    return reader;
}

#else /* KOMPARU_WINDOWS */

/* =========================================================================
 * Windows implementation using ReadFile + CreateFileMapping
 * ========================================================================= */

typedef struct {
    HANDLE hFile;
    HANDLE hMapping;
    void *mapped;
    int64_t file_size;
    int64_t offset;
    char source[1024];
} file_ctx_win_t;

static int64_t file_read_win(komparu_reader_t *self, void *buf, size_t size) {
    file_ctx_win_t *ctx = (file_ctx_win_t *)self->ctx;

    if (ctx->mapped) {
        /* Memory-mapped read */
        if (ctx->offset >= ctx->file_size) return 0;

        size_t remaining = (size_t)(ctx->file_size - ctx->offset);
        size_t to_read = (size < remaining) ? size : remaining;

        __try {
            memcpy(buf, (const char *)ctx->mapped + ctx->offset, to_read);
        } __except (GetExceptionCode() == EXCEPTION_IN_PAGE_ERROR
                        ? EXCEPTION_EXECUTE_HANDLER
                        : EXCEPTION_CONTINUE_SEARCH) {
            return -1;  /* File truncated — equivalent to SIGBUS */
        }

        ctx->offset += (int64_t)to_read;
        return (int64_t)to_read;
    } else {
        /* ReadFile fallback */
        DWORD to_read = (size > MAXDWORD) ? MAXDWORD : (DWORD)size;
        DWORD bytes_read = 0;
        if (!ReadFile(ctx->hFile, buf, to_read, &bytes_read, NULL)) {
            return -1;
        }
        ctx->offset += bytes_read;
        return (int64_t)bytes_read;
    }
}

static int64_t file_get_size_win(komparu_reader_t *self) {
    file_ctx_win_t *ctx = (file_ctx_win_t *)self->ctx;
    return ctx->file_size;
}

static int file_seek_win(komparu_reader_t *self, int64_t offset) {
    file_ctx_win_t *ctx = (file_ctx_win_t *)self->ctx;

    if (ctx->mapped) {
        if (offset < 0 || offset > ctx->file_size) return -1;
        ctx->offset = offset;
        return 0;
    }

    LARGE_INTEGER li;
    li.QuadPart = offset;
    if (!SetFilePointerEx(ctx->hFile, li, NULL, FILE_BEGIN)) {
        return -1;
    }
    ctx->offset = offset;
    return 0;
}

static void file_close_win(komparu_reader_t *self) {
    file_ctx_win_t *ctx = (file_ctx_win_t *)self->ctx;
    if (ctx->mapped) UnmapViewOfFile(ctx->mapped);
    if (ctx->hMapping) CloseHandle(ctx->hMapping);
    if (ctx->hFile != INVALID_HANDLE_VALUE) CloseHandle(ctx->hFile);
    free(ctx);
    free(self);
}

komparu_reader_t *komparu_reader_file_open(const char *path, const char **err_msg) {
    HANDLE hFile = CreateFileA(
        path, GENERIC_READ, FILE_SHARE_READ, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL
    );
    if (hFile == INVALID_HANDLE_VALUE) {
        *err_msg = "cannot open file";
        return NULL;
    }

    LARGE_INTEGER size;
    if (!GetFileSizeEx(hFile, &size)) {
        *err_msg = "cannot get file size";
        CloseHandle(hFile);
        return NULL;
    }

    komparu_reader_t *reader = calloc(1, sizeof(komparu_reader_t));
    file_ctx_win_t *ctx = calloc(1, sizeof(file_ctx_win_t));
    if (!reader || !ctx) {
        *err_msg = "out of memory";
        free(reader); free(ctx);
        CloseHandle(hFile);
        return NULL;
    }

    ctx->hFile = hFile;
    ctx->file_size = size.QuadPart;
    ctx->offset = 0;
    snprintf(ctx->source, sizeof(ctx->source), "%s", path);

    reader->ctx = ctx;
    reader->source_name = ctx->source;
    reader->get_size = file_get_size_win;
    reader->read = file_read_win;
    reader->seek = file_seek_win;
    reader->close = file_close_win;

    /* Try memory mapping for non-empty files */
    if (size.QuadPart > 0) {
        HANDLE hMapping = CreateFileMappingA(hFile, NULL, PAGE_READONLY, 0, 0, NULL);
        if (hMapping) {
            void *mapped = MapViewOfFile(hMapping, FILE_MAP_READ, 0, 0, 0);
            if (mapped) {
                ctx->hMapping = hMapping;
                ctx->mapped = mapped;
                return reader;
            }
            CloseHandle(hMapping);
        }
    }

    /* Fallback: ReadFile */
    ctx->hMapping = NULL;
    ctx->mapped = NULL;
    return reader;
}

#endif /* KOMPARU_WINDOWS */
