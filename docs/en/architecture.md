# komparu — Architecture

## 1. Project Structure

```
komparu/
├── src/
│   ├── komparu/                  # Python package
│   │   ├── __init__.py           # Public sync API
│   │   ├── aio.py                # Public async API
│   │   ├── _types.py             # Result types, enums
│   │   ├── _config.py            # Configuration
│   │   └── py.typed              # PEP 561 marker
│   └── _core/                    # C23 source
│       ├── module.c              # CPython extension entry point
│       ├── module.h
│       ├── reader.h              # Reader interface (abstract)
│       ├── reader_file.c         # Local file reader
│       ├── reader_file.h
│       ├── reader_http.c         # HTTP Range reader (libcurl)
│       ├── reader_http.h
│       ├── reader_archive.c      # Archive reader (libarchive)
│       ├── reader_archive.h
│       ├── compare.c             # Comparison engine
│       ├── compare.h
│       ├── dirwalk.c             # Directory traversal
│       ├── dirwalk.h
│       ├── pool.c                # Thread pool
│       ├── pool.h
│       └── compat.h              # Python version / platform compat macros
├── tests/
│   ├── conftest.py
│   ├── test_compare_local.py
│   ├── test_compare_http.py
│   ├── test_compare_mixed.py
│   ├── test_compare_dir.py
│   ├── test_compare_archive.py
│   ├── test_compare_many.py
│   ├── test_async.py
│   ├── test_config.py
│   └── fixtures/                 # Test files, archives
├── benchmarks/
│   ├── bench_local.py
│   ├── bench_http.py
│   └── bench_parallel.py
├── docs/
│   ├── en/
│   └── ru/
├── meson.build                   # Build system
├── meson.options
├── pyproject.toml
├── LICENSE
├── README.md
├── README.ru.md
├── Dockerfile
└── .github/
    └── workflows/
        ├── ci.yml                # Test matrix
        ├── wheels.yml            # Build & publish wheels
        └── bench.yml             # Benchmark regression
```

## 2. C23 Core — Module Diagram

```
┌──────────────────────────────────────────────────┐
│                   module.c                        │
│           CPython extension entry point           │
│     GIL handling, free-threading support          │
└──────┬───────────┬──────────────┬────────────────┘
       │           │              │
       v           v              v
┌──────────┐ ┌──────────┐ ┌──────────────┐
│compare.c │ │dirwalk.c │ │   pool.c     │
│comparison│ │directory │ │ thread pool  │
│  engine  │ │traversal │ │ work queue   │
└──────┬───┘ └──────────┘ └──────────────┘
       │
       v
┌──────────────── reader.h (interface) ────────────┐
│                                                   │
│  ┌───────────────┐ ┌──────────────┐ ┌───────────┐│
│  │reader_file.c  │ │reader_http.c │ │reader_    ││
│  │mmap / read()  │ │libcurl       │ │archive.c  ││
│  │               │ │Range requests│ │libarchive ││
│  └───────────────┘ └──────────────┘ └───────────┘│
└──────────────────────────────────────────────────┘
```

## 3. Reader Interface

Abstract reader — uniform API for all source types.

```c
typedef struct komparu_reader {
    // Read up to `size` bytes into `buf`. Return bytes read, 0 = EOF, -1 = error.
    int64_t (*read)(struct komparu_reader *self, void *buf, size_t size);

    // Get total size if known. Return -1 if unknown.
    int64_t (*get_size)(struct komparu_reader *self);

    // Close and free resources.
    void (*close)(struct komparu_reader *self);

    // Opaque state.
    void *ctx;
} komparu_reader_t;
```

### Implementations

| Reader | Backend | Chunk Strategy |
|--------|---------|----------------|
| `reader_file` | `mmap` (Linux/macOS), `ReadFile` (Windows) | Memory-mapped pages, OS manages caching |
| `reader_http` | libcurl | HTTP Range requests, connection reuse |
| `reader_archive` | libarchive | Sequential streaming read |

## 4. Comparison Algorithm

```
compare(reader_a, reader_b, chunk_size):
    1. size_a = reader_a.get_size()
       size_b = reader_b.get_size()
    2. if both known AND size_a != size_b → return false
    3. loop:
         n_a = reader_a.read(buf_a, chunk_size)
         n_b = reader_b.read(buf_b, chunk_size)
         if n_a != n_b → return false
         if n_a == 0   → return true   // both EOF
         if memcmp(buf_a, buf_b, n_a) != 0 → return false
    4. unreachable
```

Key properties:
- Memory: 2 * chunk_size (two buffers)
- I/O: stops at first difference
- Network: only fetches needed chunks via Range

## 5. Directory Comparison

```
compare_dir(dir_a, dir_b):
    1. files_a = dirwalk(dir_a)  → set of relative paths
       files_b = dirwalk(dir_b)  → set of relative paths
    2. only_left  = files_a - files_b
       only_right = files_b - files_a
       common     = files_a & files_b
    3. parallel_for file in common:
         if not compare(dir_a/file, dir_b/file):
             diff[file] = CONTENT_MISMATCH
    4. return DirResult(equal, diff, only_left, only_right)
```

## 6. Thread Pool

```c
typedef struct komparu_pool {
    pthread_t *workers;       // Worker threads
    size_t num_workers;       // Worker count
    komparu_task_t *queue;    // Task queue (lock-free ring buffer)
    atomic_bool shutdown;     // Shutdown flag
} komparu_pool_t;
```

- Default workers: `min(sysconf(_SC_NPROCESSORS_ONLN), 8)`
- GIL released before submitting work to pool
- Each task: one file pair comparison
- Windows: `_beginthreadex` + `CRITICAL_SECTION`

## 7. Python Build Variants

### compat.h — Conditional Compilation

```c
// Python version detection
#if PY_VERSION_HEX >= 0x030E0000    // 3.14+
    #define KOMPARU_PY314 1
#elif PY_VERSION_HEX >= 0x030D0000  // 3.13+
    #define KOMPARU_PY313 1
#endif

// Free-threaded build detection
#ifdef Py_GIL_DISABLED
    #define KOMPARU_FREE_THREADED 1
#endif

// GIL handling
#ifdef KOMPARU_FREE_THREADED
    // No GIL operations needed — it doesn't exist
    #define KOMPARU_GIL_RELEASE()
    #define KOMPARU_GIL_ACQUIRE()
#else
    #define KOMPARU_GIL_RELEASE() Py_BEGIN_ALLOW_THREADS
    #define KOMPARU_GIL_ACQUIRE() Py_END_ALLOW_THREADS
#endif
```

### Module Init

```c
static struct PyModuleDef_Slot module_slots[] = {
#ifdef KOMPARU_FREE_THREADED
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
#endif
    {0, NULL}
};
```

## 8. Sync vs Async Architecture

### Sync (komparu/__init__.py → C extension)

```
Python call → C extension → GIL release → C I/O + compare → GIL acquire → return
```

Full pipeline in C. Maximum performance. Single FFI boundary crossing.

### Async (komparu/aio.py → C extension with libcurl multi)

```
Python call → C extension → libcurl multi (non-blocking) → asyncio event loop integration → return
```

- HTTP I/O: **libcurl multi interface** — `curl_multi_socket_action()` integrated with asyncio via file descriptors
- File I/O: `io_uring` (Linux) / `kqueue` (macOS) via C, non-blocking
- All I/O in C — no Python HTTP libraries (no aiohttp, no aiofiles)
- Event loop never blocked
- C extension exposes Python awaitable objects (`__await__` protocol)

Why separate: sync uses libcurl easy (blocking, GIL released, maximum throughput).
Async uses libcurl multi (non-blocking, event loop integration, maximum concurrency).
Same C core, different I/O strategies. Neither wraps the other.

## 9. External Dependencies

| Library | Purpose | Linking |
|---------|---------|---------|
| libcurl | HTTP/HTTPS — easy (sync) + multi (async) interfaces | Dynamic (system) or static (vendored for wheels). Require c-ares or threaded resolver. |
| libarchive | Archive reading (zip, tar, 7z, etc.) | Dynamic (system) or static (vendored for wheels) |
| pthreads | Thread pool (Linux/macOS) | System |

No Python HTTP/IO dependencies. All I/O handled in C via libcurl and OS-native async (io_uring / kqueue).

## 10. Platform Matrix

| Feature | Linux | macOS | Windows |
|---------|-------|-------|---------|
| File reader | mmap | mmap | ReadFile + CreateFileMapping |
| HTTP reader | libcurl | libcurl | libcurl |
| Archive reader | libarchive | libarchive | libarchive |
| Thread pool | pthreads | pthreads | Windows threads |
| Free-threading | Yes (3.13t+) | Yes (3.13t+) | Yes (3.13t+) |
