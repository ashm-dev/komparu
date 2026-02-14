# komparu — Work Plan

## Phase 1: Foundation

**Goal:** Local file comparison works end-to-end.

- [ ] Project structure: `meson.build`, `pyproject.toml`
- [ ] C23 core: `reader.h` interface, `reader_file.c` (mmap)
- [ ] C23 core: `compare.c` — chunk-based comparison engine
- [ ] C23 core: `module.c` — CPython extension, GIL handling
- [ ] Python sync API: `komparu.compare()` for local files
- [ ] `compat.h` — version/platform macros
- [ ] Tests: local file comparison (equal, different, empty, large)
- [ ] CI: GitHub Actions, Python 3.12 on Linux

**Result:** `komparu.compare("/a", "/b")` works.

## Phase 2: HTTP Support

**Goal:** Remote URL comparison via Range requests.

- [ ] C23 core: `reader_http.c` — libcurl, Range requests, connection reuse
- [ ] HTTP options: headers, timeout, redirects, SSL
- [ ] Mixed comparison: local + remote
- [ ] Size pre-check via HEAD / Content-Length
- [ ] Tests: mock HTTP server (pytest-httpserver), Range verification
- [ ] Early termination test: large remote file, difference in first chunk

**Result:** `komparu.compare("/local", "https://remote")` works.

## Phase 3: Directories & Archives

**Goal:** Recursive directory and archive comparison.

- [ ] C23 core: `dirwalk.c` — recursive traversal, relative paths
- [ ] Python: `compare_dir()` — directory comparison
- [ ] C23 core: `reader_archive.c` — libarchive streaming
- [ ] Python: `compare_archive()` — archive comparison
- [ ] Python: `compare_dir_urls()` — directory vs URL mapping
- [ ] Result types: `DirResult`, `DiffReason`
- [ ] Tests: directories (nested, symlinks, empty), archives (zip, tar.gz, mixed)

**Result:** `komparu.compare_dir()`, `compare_archive()`, `compare_dir_urls()` work.

## Phase 4: Multiple Comparison & Parallelism

**Goal:** Batch comparison with thread pool.

- [ ] C23 core: `pool.c` — thread pool, task queue
- [ ] Python: `compare_all()`, `compare_many()`, `CompareResult`
- [ ] Parallel directory comparison (file pairs compared concurrently)
- [ ] Configurable `max_workers`
- [ ] Tests: parallel correctness, resource limits
- [ ] Benchmarks: parallel vs sequential

**Result:** Multi-file and multi-directory comparison with parallelism.

## Phase 5: Async API

**Goal:** Native async API without wrapping sync.

- [ ] `komparu/aio.py` — async versions of all public functions
- [ ] Async HTTP via aiohttp
- [ ] Async file I/O via aiofiles
- [ ] C extension: `compare_buffers()` for async path
- [ ] Tests: async equivalents of all sync tests
- [ ] Tests: concurrent async operations

**Result:** `await komparu.aio.compare()` and all async variants work.

## Phase 6: Multi-Version & Free-Threading

**Goal:** Full Python version matrix, free-threaded builds.

- [ ] CI matrix: Python 3.12, 3.13, 3.14, main
- [ ] Free-threaded builds: 3.13t, 3.14t
- [ ] `Py_mod_gil` slot, `Py_GIL_DISABLED` conditionals
- [ ] Thread safety audit of C code
- [ ] JIT build testing
- [ ] Platform matrix: Linux, macOS, Windows
- [ ] cibuildwheel configuration for all variants

**Result:** All tests pass on all Python versions and platforms.

## Phase 7: Release

**Goal:** Production-ready release on PyPI.

- [ ] README.md (English), README.ru.md (Russian)
- [ ] reST docstrings on all public API
- [ ] Type stubs / py.typed
- [ ] Benchmark suite: local, HTTP, parallel
- [ ] Dockerfile
- [ ] LICENSE (MIT)
- [ ] PyPI publish workflow
- [ ] v0.1.0 release

**Result:** `pip install komparu` works. Documentation complete.
