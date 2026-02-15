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
│       ├── async_task.c          # Async task lifecycle (CAS, eventfd/pipe)
│       ├── async_task.h
│       ├── async_curl.c          # libcurl multi building blocks
│       ├── async_curl.h
│       ├── curl_share.c          # CURLSH connection/DNS/TLS sharing
│       ├── curl_share.h
│       └── compat.h              # Python version / platform compat macros
├── tests/
│   ├── conftest.py
│   ├── test_compare_local.py
│   ├── test_compare_http.py
│   ├── test_compare_dir.py
│   ├── test_compare_archive.py
│   ├── test_parallel.py
│   ├── test_async.py
│   └── test_config.py
├── benchmarks/                   # Benchmark suite (Go/Rust competitors, charts)
├── docs/
│   ├── en/
│   └── ru/
├── CMakeLists.txt                # Build system
├── pyproject.toml
├── LICENSE
├── README.md
└── .github/
    └── workflows/               # (planned)
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
│  │               │ │+ curl_share  │ │libarchive ││
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
| `reader_http` | libcurl | HTTP Range requests, CURLSH connection/DNS/TLS pooling |
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

### Quick Check (early exit optimization)

Before full sequential scan, `komparu_quick_check` samples up to 5 offsets in O(1):

```
quick_check(reader_a, reader_b, chunk_size):
    offsets = [0, EOF-chunk, 25%, 50%, 75%]
    for each offset:
        seek both readers
        read one chunk each
        if memcmp differs → return DIFFERENT
    return EQUAL (proceed to full scan for confirmation)
```

Catches common difference patterns (truncation, appended data, localized edits) without reading the full file. Uses thread-local buffers to avoid per-call malloc overhead.

### Thread-Local Comparison Buffers

Both `komparu_compare` and `komparu_quick_check` use `_Thread_local` static buffers instead of heap allocation. This eliminates malloc/free overhead on every comparison call while remaining thread-safe for the parallel thread pool.

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

### Arena Allocator for Path Strings

`dirwalk.c` stores all path strings in a contiguous arena (64 KB blocks). The `pathlist_t` array holds pointers into arena memory. This eliminates per-path `malloc` overhead (~16 bytes/alloc) and enables bulk deallocation — a single `arena_free()` instead of thousands of individual `free()` calls.

## 6. Thread Pool

```c
typedef struct komparu_pool {
    pthread_t *threads;
    size_t num_workers;
    pool_task_t *queue;       // Dynamic array (FIFO, head/tail)
    size_t queue_cap;
    size_t queue_head;
    size_t queue_tail;
    size_t queue_count;
    pthread_mutex_t mutex;
    pthread_cond_t task_avail;
    pthread_cond_t all_done;
    size_t active_count;
    bool shutdown;
} komparu_pool_t;
```

- Dynamic array task queue with mutex + condvar synchronization
- Default workers: `min(sysconf(_SC_NPROCESSORS_ONLN), 8)`
- GIL released before submitting work to pool
- Each task: one file pair comparison

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

### Async (komparu/aio.py → C pool + eventfd/pipe + asyncio)

```
Python call → async_compare_start() → C pool submits task → worker runs (GIL-free):
    open_reader (file/HTTP) → komparu_compare → write to eventfd/pipe
Python: asyncio.loop.add_reader(fd) → callback fires → async_compare_result(task)
```

- ALL async functions (compare, compare_dir, compare_archive, compare_dir_urls) use the same pattern: C pool + eventfd/pipe + `asyncio.loop.add_reader()`
- Worker threads use libcurl easy (blocking) -- same I/O as the sync path
- Notification via eventfd (Linux) or pipe (macOS) wakes the asyncio event loop
- CAS-based task lifecycle: RUNNING -> DONE or RUNNING -> ORPHANED
- No `curl_multi_socket_action` integration (async_curl.c exists as building blocks for future non-blocking HTTP, not used by the main async API)
- No io_uring or kqueue for async I/O (workers use mmap same as sync)
- No Python awaitable protocol (`__await__`) -- uses regular `async def` + `add_reader`
- All I/O in C -- no Python HTTP libraries (no aiohttp, no aiofiles)
- No `asyncio.to_thread()` wrapping -- true C pool with event loop notification

Why separate: sync blocks in C with GIL released. Async submits to C pool and
integrates with asyncio via fd notification. Same C core, same I/O (libcurl easy,
mmap), different scheduling strategies.

## 9. External Dependencies

| Library | Purpose | Linking |
|---------|---------|---------|
| libcurl | HTTP/HTTPS — easy interface (sync and async workers) | Dynamic (system) or static (vendored for wheels). Require c-ares or threaded resolver. |
| libarchive | Archive reading (zip, tar, 7z, etc.) | Dynamic (system) or static (vendored for wheels) |
| pthreads | Thread pool (Linux/macOS) | System |

No Python HTTP/IO dependencies. All I/O handled in C via libcurl easy and mmap.

## 10. Platform Matrix

| Feature | Linux | macOS | Windows |
|---------|-------|-------|---------|
| File reader | mmap | mmap | ReadFile + CreateFileMapping |
| HTTP reader | libcurl | libcurl | libcurl |
| Archive reader | libarchive | libarchive | libarchive |
| Thread pool | pthreads | pthreads | Windows threads |
| Free-threading | Yes (3.13t+) | Yes (3.13t+) | Yes (3.13t+) |

## 11. Performance Optimizations

### CURLSH Connection Pooling

`curl_share.c` provides a global `CURLSH*` handle shared by all libcurl easy handles. Shares:
- **DNS cache** — avoids repeated lookups to the same host
- **Connection pool** — reuses TCP/TLS connections across requests
- **TLS session cache** — TLS session resumption, skips full handshake

Thread safety: per-lock-data mutex array (8 mutexes indexed by `curl_lock_data`), allowing maximum concurrency (different data types locked independently). POSIX: `pthread_mutex_t`, Windows: `SRWLOCK`.

Initialized once in `PyInit__core`, cleaned up via `Py_AtExit`.

### Hash-Based Archive Comparison

`compare_archive(hash_compare=True)` computes a streaming FNV-1a 128-bit fingerprint (two 64-bit hashes with different initial bases) of each archive entry. Stores only `name + hash_lo + hash_hi + size` per entry (~40 bytes).

Memory: **O(entries)** instead of **O(total_decompressed)**. For 100,000 entries: ~4 MB vs potentially 50+ GB with the default full-content mode.

Collision probability: ~2^{-64} under birthday attack (128-bit fingerprint from two independent hash streams).

### Arena Allocator for Directory Traversal

`dirwalk.c` allocates path strings in contiguous 64 KB arena blocks instead of individual `malloc` calls. Reduces allocation overhead by ~16 bytes per path and enables O(1) bulk deallocation.

### Thread-Local Comparison Buffers

`compare.c` uses `_Thread_local` static buffers for both `komparu_compare` and `komparu_quick_check`. Eliminates per-call `malloc`/`free` while remaining safe in the parallel thread pool.
