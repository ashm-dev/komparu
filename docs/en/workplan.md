# komparu — Work Plan

## Phase 1: Foundation

**Goal:** Local file comparison works end-to-end.

- [x] Project structure: `CMakeLists.txt`, `pyproject.toml`
- [x] C23 core: `reader.h` interface, `reader_file.c` (mmap)
- [x] C23 core: `compare.c` — chunk-based comparison engine
- [x] C23 core: `module.c` — CPython extension, GIL handling
- [x] Python sync API: `komparu.compare()` for local files
- [x] `compat.h` — version/platform macros
- [x] Tests: local file comparison (equal, different, empty, large)
- [x] CI: GitHub Actions, Python 3.12 on Linux

**Result:** `komparu.compare("/a", "/b")` works.

## Phase 2: HTTP Support

**Goal:** Remote URL comparison via Range requests.

- [x] C23 core: `reader_http.c` — libcurl, Range requests, connection reuse
- [x] HTTP options: headers, timeout, redirects, SSL
- [x] Mixed comparison: local + remote
- [x] Size pre-check via HEAD / Content-Length
- [x] Tests: mock HTTP server (pytest-httpserver), Range verification
- [x] Early termination test: large remote file, difference in first chunk

**Result:** `komparu.compare("/local", "https://remote")` works.

## Phase 3: Directories & Archives

**Goal:** Recursive directory and archive comparison.

- [x] C23 core: `dirwalk.c` — recursive traversal, relative paths
- [x] Python: `compare_dir()` — directory comparison
- [x] C23 core: `reader_archive.c` — libarchive streaming
- [x] Python: `compare_archive()` — archive comparison
- [x] Python: `compare_dir_urls()` — directory vs URL mapping
- [x] Result types: `DirResult`, `DiffReason`
- [x] Tests: directories (nested, symlinks, empty), archives (zip, tar.gz, mixed)

**Result:** `komparu.compare_dir()`, `compare_archive()`, `compare_dir_urls()` work.

## Phase 4: Multiple Comparison & Parallelism

**Goal:** Batch comparison with thread pool.

- [x] C23 core: `pool.c` — thread pool, task queue
- [x] Python: `compare_all()`, `compare_many()`, `CompareResult`
- [x] Parallel directory comparison (file pairs compared concurrently)
- [x] Configurable `max_workers`
- [x] Tests: parallel correctness, resource limits
- [x] Benchmarks: parallel vs sequential

**Result:** Multi-file and multi-directory comparison with parallelism.

## Phase 5: Async API

**Goal:** Native async API without wrapping sync.

- [x] `komparu/aio.py` — async versions of all public functions
- [x] C pool thread infrastructure: `async_task.c` — task lifecycle with CAS, eventfd/pipe notification
- [x] Async compare and compare_dir via C pool + `asyncio.loop.add_reader()`
- [x] Async compare_archive and compare_dir_urls via C pool (no wrapping)
- [x] libcurl multi building blocks: `async_curl.c` for future non-blocking HTTP
- [x] Tests: async equivalents of all sync tests
- [x] Tests: concurrent async operations

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

- [x] README.md (English), README.ru.md (Russian)
- [x] CLAUDE.md
- [ ] reST docstrings on all public API
- [ ] Type stubs / py.typed
- [x] Benchmark suite with charts (Go, Rust, filecmp, cmp, hashlib)
- [ ] Dockerfile
- [ ] LICENSE (MIT)
- [ ] PyPI publish workflow
- [ ] v0.1.0 release

**Result:** `pip install komparu` works. Documentation complete.
