# komparu — Requirements Specification

## 1. Overview

Ultra-fast file comparison library. C23 core, Python bindings.
Compares content of local files, remote URLs, directories, and archives.
Chunk-based processing — constant memory regardless of file size.

**License:** MIT
**Platforms:** Linux, macOS, Windows, Docker
**Python:** 3.12, 3.13, 3.14, main (incl. free-threaded builds)

## 2. Functional Requirements

### FR-1: Pairwise Comparison

Compare two sources byte-by-byte. Return `bool`.

Sources:
- Local file path (`/path/to/file`)
- HTTP/HTTPS URL (`https://s3.example.com/file`)

All combinations supported: local-local, local-remote, remote-remote.

### FR-2: Directory Comparison

Recursively compare two directories.
Match files by relative path.

Return:
- `equal: bool` — all files identical
- `diff: dict[str, DiffReason]` — files with different content
- `only_left: set[str]` — files only in first directory
- `only_right: set[str]` — files only in second directory

### FR-3: Archive Comparison

Compare contents of two archives as virtual directories.
Formats (via libarchive): zip, tar, tar.gz, tar.bz2, tar.xz, 7z, rar.

Return type: same as directory comparison (FR-2).

### FR-4: Multiple Source Comparison

Compare N sources (files, URLs, mixed).

Modes:
- `compare_all([...]) -> bool` — all identical?
- `compare_many([...]) -> CompareResult` — detailed grouping

### FR-5: Directory vs URL Mapping

Compare local directory against a mapping of relative paths to URLs.

```python
komparu.compare_dir_urls(
    "/local/dir",
    {"file1.txt": "https://cdn.example.com/file1.txt", ...}
)
```

### FR-6: HTTP Configuration

Per-source and global:
- Custom headers (Authorization, etc.)
- Request body (for POST-based storage APIs)
- Timeout
- Redirect policy
- SSL verification toggle

### FR-7: Chunk-Based Processing

- Configurable chunk size (default: 64 KB)
- Read and compare incrementally
- Early termination on first difference — no further I/O

### FR-8: Size Pre-Check

Before content comparison:
1. Local files: `stat()` for size
2. Remote files: `HEAD` request / `Content-Length`
3. Size mismatch → instant `False` (configurable, can be disabled)

### FR-9: Thread Pool

Parallel comparison for directory/multiple comparisons.
- Configurable worker count (default: `min(cpu_count, 8)`)
- GIL released during all C operations
- No excessive resource consumption

### FR-10: Free-Threading Support (3.13t, 3.14t)

- `Py_mod_gil = Py_MOD_GIL_NOT_USED`
- Thread-safe C code: no shared mutable global state
- Atomic operations where needed
- Conditional compilation: `#ifdef Py_GIL_DISABLED`

### FR-11: JIT Compatibility (3.13+)

No special C-extension handling required.
Must be tested in JIT-enabled builds to confirm no interference.

### FR-12: Archive Safety Limits

Protection against decompression bombs and resource exhaustion.
Secure by default, configurable per-call or globally.

Limits:
- `max_decompressed_size` — max decompressed bytes per archive (default: 1 GB)
- `max_compression_ratio` — max ratio decompressed/compressed (default: 200)
- `max_archive_entries` — max files per archive (default: 100,000)
- `max_entry_name_length` — max entry path length (default: 4096 bytes)
- `comparison_timeout` — wall-clock time per comparison call (default: 300s) *[planned — not yet enforced in C]*

Hard rules (always on):
- Streaming only — never extract to disk
- No recursive archive decompression
- Path sanitization (reject `..`, leading `/`, null bytes)

See `docs/en/security.md` for full details.

## 3. Non-Functional Requirements

### NFR-1: Performance

- Local comparison: near disk I/O speed
- HTTP comparison: limited only by network bandwidth
- Memory: O(chunk_size) per active comparison, not O(file_size)
- Thread pool overhead: negligible

### NFR-2: Correctness

- Byte-perfect comparison
- 1 bit difference in 1 TB file → detected, no false results
- No false positives, no false negatives

### NFR-3: Code Quality

- Clean, idiomatic C23
- Full reST docstrings in English
- Type annotations, `py.typed` marker (PEP 561)
- Test coverage > 90%

### NFR-4: Distribution

- PyPI wheels: manylinux (x86_64, aarch64), macOS (x86_64, arm64), Windows (x86_64)
- Free-threaded wheels (3.13t, 3.14t)
- Source distribution (sdist)
- Docker base image for CI usage

### NFR-5: Documentation

- README in English and Russian
- API reference with examples
- reST docstrings on all public API
