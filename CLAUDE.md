# CLAUDE.md

Project instructions for AI agents working on komparu.

## Project Overview

komparu is an ultra-fast file comparison library with a C23 core. Python package (`komparu`) with C extension module (`komparu._core`). Compares files, directories, archives, and HTTP resources byte-by-byte.

- **Repository**: https://github.com/ashm-dev/komparu
- **Branch model**: trunk-based development on `main`
- **License**: MIT
- **Python**: >=3.12

## Build & Test

```bash
# Build (always use clang)
CC=clang CMAKE_ARGS="-DCMAKE_C_COMPILER=clang" uv pip install -e . --reinstall-package komparu

# Run tests
uv run pytest tests/ -v

# Run benchmarks
cd benchmarks/competitors && make all && cd .. && uv run python run_all.py --fast
```

### Sanitizers

Build with sanitizers (clang only):

```bash
.venv/bin/pip install --no-build-isolation -e . \
  -C cmake.define.KOMPARU_SANITIZER=address \
  -C cmake.define.CMAKE_C_COMPILER=clang
```

Run with preloaded sanitizer runtime:
- **ASAN**: `LD_PRELOAD=$(clang -print-file-name=libclang_rt.asan-x86_64.so) uv run pytest tests/ -v`
- **UBSAN**: `LD_PRELOAD=$(clang -print-file-name=libclang_rt.ubsan_standalone-x86_64.so) uv run pytest tests/ -v`
- **TSAN**: `LD_PRELOAD=$(clang -print-file-name=libclang_rt.tsan-x86_64.so) uv run pytest tests/ -v`

After sanitizer builds, clean up stale symbols:
```bash
rm -rf build && uv cache clean komparu && uv sync --reinstall
```

MSAN does not work with stock CPython (requires fully instrumented interpreter).

## Project Structure

```
src/komparu/          Python package (public API, types, config, async)
src/_core/            C23 extension (mmap, libcurl, libarchive, pthread pool, eventfd)
tests/                pytest tests (145 tests)
benchmarks/           Benchmark suite (Go/Rust competitors, charts)
docs/en/              English documentation
docs/ru/              Russian documentation
```

Key C files:
- `module.c` — CPython C API wrappers
- `compare.c` — core comparison engine (mmap + MADV_SEQUENTIAL, quick_check)
- `reader_file.c` — local file reader (mmap)
- `reader_http.c` — HTTP reader (libcurl, Range requests)
- `reader_archive.c` — archive reader (libarchive streaming)
- `dirwalk.c` — recursive directory traversal
- `pool.c` — pthread thread pool
- `async_task.c` — async task infrastructure (eventfd/pipe, CAS lifecycle)
- `async_curl.c` — libcurl multi building blocks

Key Python files:
- `__init__.py` — public API exports
- `_types.py` — CompareResult, DirResult, Source, DiffReason
- `_config.py` — KomparuConfig, configure(), get_config()
- `aio.py` — async API (C pool + eventfd + asyncio.loop.add_reader)

## Code Style

### C code
- Performance first — all possible optimizations
- C23 standard
- Always use clang (never gcc)
- GIL must be released BEFORE `curl_easy_perform()` — Python-threaded servers need GIL to process requests
- Convert all Python objects to C types before releasing GIL
- `_Thread_local` for error buffers is correct pattern
- `strncasecmp` needs `#include <strings.h>`

### Python code
- Clean and well-typed
- No aiohttp or Python HTTP libraries — all HTTP through C/libcurl
- No `asyncio.to_thread()` wrapping — async must use C pool + eventfd/pipe with `asyncio.loop.add_reader()`
- Type annotations on all public functions

## Git Conventions

- Brief commit messages, no co-authoring lines
- Trunk-based development on `main`
- No feature branches — commit directly to main

## Documentation

All documentation is bilingual (English + Russian):
- `README.md` / `README.ru.md` — project README with language selector
- `docs/en/` — English docs (api, architecture, requirements, security, edge-cases)
- `docs/ru/` — Russian docs (same structure)
- `benchmarks/README.md` — benchmark methodology

When modifying documentation, update both English and Russian versions.

## Architecture Decisions

1. **C23 core** — all I/O in C, Python is just a wrapper
2. **mmap + MADV_SEQUENTIAL** — zero-copy with kernel readahead
3. **Quick check** — samples first/last/middle bytes before full scan
4. **pthread pool** — native threads for parallel comparison
5. **eventfd/pipe + asyncio.loop.add_reader()** — native async without Python threads
6. **CAS-based task lifecycle** — RUNNING -> DONE or RUNNING -> ORPHANED for safe cancellation
7. **libcurl** for HTTP with connection pooling
8. **libarchive** for archive format support
9. **Archive bomb protection** — configurable size/ratio/entry limits
