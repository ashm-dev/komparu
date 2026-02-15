# komparu — Complete Edge Cases Registry

Three-pass analysis. Every case has a status:
- **HANDLE** — handled in code
- **PLANNED** — planned for future implementation
- **DETECT** — detect and report clearly (error/warning)
- **DOCUMENT** — expected behavior, document for users
- **N/A** — not applicable to our design

---

## I. Source / Input

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 1 | Both files 0 bytes | DOCUMENT | `True`. Empty equals empty. |
| 2 | One file 0 bytes, other not | HANDLE | Size pre-check → instant `False`. |
| 3 | Same file path (`compare("/a", "/a")`) | PLANNED | Detect via `(dev, ino)` → instant `True`, no I/O. |
| 4 | Same URL string | DOCUMENT | **No shortcut.** Same URL can return different content (dynamic, CDN nodes, cache). Always compare. Only local files get inode-based shortcut. |
| 4a | URL with different query params | DOCUMENT | Different resources. `?v=1` ≠ `?v=2`. No normalization of query params. |
| 5 | Source doesn't exist (local) | HANDLE | `SourceNotFoundError` with path. |
| 6 | Source is a directory, not a file | HANDLE | `SourceReadError("'/path' is a directory, not a file")`. |
| 7 | Source is a symlink | HANDLE | Follow by default (read target). `follow_symlinks` controls dir behavior. |
| 8 | Source is a special file (device, pipe, socket, FIFO) | HANDLE | `SourceReadError("'/dev/sda' is not a regular file")`. Reject. |
| 9 | Source is `/dev/null` | HANDLE | Treated as 0-byte file. Same as case #1. |
| 10 | Source is `/dev/zero` or `/dev/urandom` | HANDLE | Rejected by case #8 (not a regular file). |
| 11 | Path with spaces, unicode chars | HANDLE | Passed as-is to OS. Works on all platforms. |
| 12 | Path exceeds PATH_MAX | HANDLE | OS returns error → `SourceNotFoundError`. |
| 13 | Very large file (>4 GB) | HANDLE | 64-bit offsets (`int64_t`), `mmap` with `MAP_NORESERVE`. |
| 14 | Very large file (>2 TB) | HANDLE | Same as above. `off_t` is 64-bit on 64-bit systems. Chunk-based, no full mapping. |
| 15 | Relative path | HANDLE | Resolve to absolute via `realpath()` before comparison. |
| 16 | Trailing slashes in path | HANDLE | Normalize: strip trailing slashes for files. |
| 17 | File on NFS/SMB (network filesystem) | DOCUMENT | Works normally. Performance depends on network. `mmap` may behave differently. |
| 18 | File on read-only filesystem | DOCUMENT | Read-only is fine — we only read. |
| 19 | Hard links (same inode, different paths) | PLANNED | Detect via `(dev, ino)` match → instant `True`. Depends on #3. |
| 20 | `str` vs `bytes` path in Python | HANDLE | Accept both. Encode `str` via `os.fsencode()`. |
| 21 | Path with null byte | HANDLE | Reject: `ConfigError("path contains null byte")`. |

## II. HTTP / Network

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 22 | HTTP 200 instead of 206 (no Range support) | HANDLE | Detect on first request. Fall back to sequential streaming. Disable `quick_check` for this source. |
| 23 | HTTP 301/302 redirect | HANDLE | Follow by default. `follow_redirects=False` to disable. |
| 24 | Redirect chain (A→B→C→D) | HANDLE | libcurl `MAXREDIRS=10`. Exceeds → `SourceReadError`. |
| 25 | Redirect loop (A→B→A) | HANDLE | libcurl detects → `SourceReadError("redirect loop")`. |
| 25a | **SSRF via redirect** | HANDLE | Attacker redirects to `http://localhost/admin`. Must validate redirect targets: block `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1`, `localhost`. Use libcurl `CURLOPT_REDIR_PROTOCOLS` to restrict to HTTP/HTTPS only. Configurable whitelist/blacklist. |
| 26 | HTTP 403 Forbidden | HANDLE | `SourceReadError("HTTP 403 for 'url'")`. |
| 27 | HTTP 404 Not Found | HANDLE | `SourceNotFoundError("HTTP 404 for 'url'")`. |
| 28 | HTTP 429 Too Many Requests | HANDLE | `SourceReadError` with status code. **No auto-retry** — user's server may have strict rate limits, retries would make it worse. User opts-in to retries explicitly. |
| 29 | HTTP 5xx server errors | HANDLE | `SourceReadError` with status code. No auto-retry. |
| 30 | Connection timeout | HANDLE | `SourceReadError`. No auto-retry. |
| 31 | Connection reset mid-transfer | HANDLE | `SourceReadError`. No auto-retry. |
| 32 | DNS resolution failure | HANDLE | `SourceReadError("DNS resolution failed for 'host'")`. |
| 33 | SSL certificate invalid/expired | HANDLE | Error by default. `verify_ssl=False` to skip. |
| 34 | Self-signed certificate | HANDLE | Same as #33. |
| 35 | `Content-Encoding: gzip` on Range response | HANDLE | Send `Accept-Encoding: identity`. If server ignores: decompress via libcurl. |
| 36 | `Transfer-Encoding: chunked` | HANDLE | libcurl handles transparently. |
| 37 | `Content-Length` header lies (smaller or larger than body) | HANDLE | Size pre-check is advisory. Chunk comparison catches actual EOF mismatch. |
| 38 | No `Content-Length` header | HANDLE | Skip size pre-check for this source. Chunk comparison works without it. |
| 39 | Server returns wrong bytes for Range request | PLANNED | Verify `Content-Range` response header matches request. Mismatch → `SourceReadError`. |
| 40 | Presigned URL expires mid-comparison | DETECT | HTTP 403 mid-stream → `SourceReadError` with context. Document: use sufficient TTL. |
| 41 | Very slow server (trickle: 1 byte/sec) | HANDLE | `timeout` covers per-request time. `comparison_timeout` planned for total wall-clock. |
| 42 | Server hangs (no response at all) | HANDLE | `timeout` → `SourceReadError`. |
| 43 | Server closes connection after N requests | HANDLE | libcurl reconnects automatically. Connection pooling handles this. |
| 44 | CDN returns different content from different edge nodes | DOCUMENT | Not detectable at our level. User responsibility. Can be mitigated with `quick_check=False` and pinning DNS, but outside our scope. |
| 45 | Content varies by User-Agent or Referer | DOCUMENT | User sets custom `headers` if needed. We don't set User-Agent by default (libcurl default). |
| 46 | URL with query parameters | HANDLE | Passed as-is. No stripping. `?v=2` is a different URL. |
| 47 | URL with fragment (#) | HANDLE | Strip fragment before request (fragments are client-side). |
| 48 | URL with `user:pass@host` | HANDLE | libcurl supports this. Extract and pass as auth. |
| 49 | URL encoding issues (%20 vs space) | HANDLE | Normalize URL before same-source detection. Don't double-encode. |
| 50 | IPv6 URLs (`http://[::1]/file`) | HANDLE | libcurl supports. Pass as-is. |
| 51 | Non-standard ports | HANDLE | libcurl supports. Pass as-is. |
| 52 | HTTP proxy required | HANDLE | Respect `HTTP_PROXY`/`HTTPS_PROXY` env vars. libcurl does this by default. |
| 52a | **Synchronous DNS blocks thread pool** | HANDLE | Standard libcurl uses blocking DNS resolver. In thread pool, blocks workers. Build/require libcurl with c-ares or threaded resolver backend. |
| 53 | HTTPS with client certificate | DOCUMENT | Not supported in v1. User can configure libcurl options in future. |
| 54 | Punycode / internationalized domain names | HANDLE | libcurl handles IDN conversion. |
| 55 | `file://` URLs | HANDLE | Treat as local file path. Strip scheme, use file reader. |
| 56 | `ftp://`, `data:`, `ws://` URLs | HANDLE | `ConfigError("unsupported URL scheme 'ftp'")`. Only `http`, `https`, `file` supported. |
| 57 | HTTP/2 vs HTTP/1.1 | HANDLE | libcurl negotiates automatically. No special handling. |
| 58 | Server returns 0 bytes with 200 OK | DOCUMENT | Treated as empty file. See case #1. |
| 59 | ETag changes between Range requests (content changed on server) | PLANNED | Store ETag from first request. Verify on subsequent requests. Mismatch → `SourceReadError("source content changed during comparison")`. |
| 60a | Server only serves whole files (no Range, no HEAD) | HANDLE | Detect on first request (200 instead of 206). Switch to full sequential download + compare. `quick_check` auto-disabled. Documented: works but slow for large files. |
| 60b | Server rate-limits Range requests | DOCUMENT | Multiple Range requests per file may trigger rate limits. With `quick_check`, up to 4 requests before full comparison. User can disable: `quick_check=False` → single sequential request. |
| 60c | Retry makes rate limit worse | DOCUMENT | `retries=0` (default). Retries are opt-in. User enables only if they know server tolerates retries. |

## III. Local File System

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 60 | File modified during comparison | PLANNED | Record `mtime`+`size` before comparison, verify after. Changed → `SourceReadError`. |
| 61 | File deleted during comparison | HANDLE | OS returns error on next read → `SourceReadError`. |
| 62 | File replaced (deleted + created) during comparison | PLANNED | Detect via inode change or mtime change. |
| 63 | File truncated during comparison | HANDLE | Read returns fewer bytes than expected → caught by chunk comparison. |
| 64 | File appended during comparison | PLANNED | Detect via size/mtime change after comparison. |
| 65 | Sparse files | DOCUMENT | `mmap` reads holes as zeros. Two sparse files with same logical content compare as equal. Correct behavior. |
| 66 | File with extended attributes (xattr) | DOCUMENT | Ignored. We compare content only, not metadata. |
| 67 | File with ACLs | DOCUMENT | Ignored. ACLs affect access, not content. If readable, we read it. |
| 68 | Files with different permissions but same content | DOCUMENT | `True`. We compare content, not metadata. |
| 69 | Files with different timestamps but same content | DOCUMENT | `True`. We compare content, not metadata. |
| 70 | File descriptor limit reached (ulimit) | HANDLE | `open()` returns `EMFILE` → `SourceReadError("too many open files")`. Thread pool limits concurrent FDs. |
| 71 | Disk I/O error (bad sector) | HANDLE | OS returns `EIO` → `SourceReadError` with details. |
| 72 | File locked by another process | HANDLE | On Linux/macOS: advisory locks don't prevent reading. On Windows: mandatory locks → `SourceReadError`. |
| 73 | `mmap` fails (address space exhaustion) | HANDLE | Fall back to buffered `read()`. Log warning. |
| 73a | **SIGBUS on mmap after file truncation** | HANDLE | If file is truncated by another process while mmap'd, accessing beyond new size causes SIGBUS — crashes Python. Must install `sigaction` handler with `sigsetjmp`/`siglongjmp` to catch SIGBUS in C, convert to `SourceReadError`. Critical for library safety. |
| 74 | File on FUSE filesystem with unusual behavior | DOCUMENT | Works if FUSE implements standard POSIX read. Edge cases possible. |
| 75 | File on proc/sys filesystem (dynamic content) | HANDLE | Rejected if not a regular file (case #8). If regular file in /proc: works but content may change between reads. |

## IV. Directory Comparison

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 76 | Both directories empty | HANDLE | `DirResult(equal=True, diff={}, only_left=set(), only_right=set())`. |
| 77 | One directory empty, other not | HANDLE | All files in `only_left` or `only_right`. `equal=False`. |
| 78 | Directory doesn't exist | HANDLE | `SourceNotFoundError`. |
| 79 | Path is a file, not a directory | HANDLE | `SourceReadError("'/path' is a file, not a directory")`. |
| 80 | Hidden files (dotfiles) | HANDLE | Included by default. `exclude_hidden=True` option to skip. |
| 81 | Deeply nested structure (>100 levels) | HANDLE | Iterative traversal (not recursive in stack). No stack overflow. |
| 82 | Directory with 1M+ files | HANDLE | Streaming traversal in C. Memory = O(tree_depth), not O(file_count). |
| 83 | Symlink loop (`/dir/link → /dir`) | PLANNED | Track visited `(dev, ino)`. Skip visited. Report as warning in result. |
| 84 | Dangling symlink (target doesn't exist) | HANDLE | `on_error="report"`: `DiffReason.READ_ERROR`. `on_error="raise"`: `SourceReadError`. |
| 85 | Permission denied on subdirectory | HANDLE | Same as #84. |
| 86 | Permission denied on individual file | HANDLE | Same as #84. |
| 87 | Cannot list directory at all | HANDLE | `SourceReadError("permission denied for '/path'")`. |
| 88 | Unicode filename normalization (NFC vs NFD) | HANDLE | `normalize_unicode=True` (default): NFC normalization for matching. |
| 89 | Case sensitivity (macOS/Windows vs Linux) | HANDLE | `case_sensitive=None` (default): auto-detect from filesystem. |
| 90 | macOS `.DS_Store` / `Thumbs.db` | DOCUMENT | Included by default. User can pass `exclude_patterns=[".DS_Store", "Thumbs.db"]`. |
| 91 | Mount points inside directory | DOCUMENT | Traversed by default. Different filesystem = different device, still traversed. |
| 92 | One entry is a file in dir_a, directory in dir_b | HANDLE | `DiffReason.TYPE_MISMATCH`. |
| 93 | Trailing slash inconsistency in dir paths | HANDLE | Normalize: strip trailing slashes. |
| 94 | Both dirs are same path | PLANNED | Detect via `(dev, ino)` of root → instant `DirResult(equal=True)`. |

## V. Archive Comparison

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 95 | Empty archive (no entries) | HANDLE | Both empty → `DirResult(equal=True)`. One empty → `only_left`/`only_right`. |
| 96 | Archive with only directory entries | HANDLE | Skip directory-only entries. Compare files only. |
| 97 | Zip bomb (classic) | HANDLE | `max_decompressed_size`, `max_compression_ratio`. See `security.md`. |
| 98 | Recursive bomb (archive in archive) | HANDLE | Never recursively decompress. Nested archive = binary blob. Hard rule. |
| 99 | Quine bomb (archive contains itself) | HANDLE | Same as #98. Compared as binary blob. |
| 100 | Archive with path traversal (`../`) | HANDLE | Path sanitization always on. Reject `..` components. |
| 101 | Archive with duplicate entry names | HANDLE | Last entry wins (consistent with most unzip tools). Document behavior. |
| 102 | Entries in different order between two archives | HANDLE | Sort entries by path before matching. Order doesn't matter. |
| 103 | Very long entry name | HANDLE | `max_entry_name_length` limit. |
| 104 | Entry name with null bytes | HANDLE | Reject entry: path sanitization. |
| 105 | Archive with symlinks inside | HANDLE | Skip symlink entries. Compare regular files only. |
| 106 | Archive with hard links inside | HANDLE | Resolve to target entry content. Compare content. |
| 107 | Archive with special files (devices) | HANDLE | Skip. Not regular files. |
| 108 | Corrupted / truncated archive | HANDLE | libarchive error → `ArchiveError` with details. |
| 109 | Password-protected archive | HANDLE | `ArchiveError("archive is password-protected")`. Not supported in v1. |
| 110 | Different archive formats with same content (zip vs tar.gz) | HANDLE | Works. We compare by entry content, not archive format. |
| 111 | Split / multi-volume archive | HANDLE | `ArchiveError("multi-volume archives not supported")`. |
| 112 | Self-extracting archive (SFX) | HANDLE | libarchive may or may not recognize. If it does: works. If not: `ArchiveError`. |
| 113 | Remote archive (URL) | HANDLE | HTTP reader feeds libarchive. Sequential streaming. `quick_check` disabled. |
| 114 | Archive with entries of different encodings (CP866, Shift-JIS) | HANDLE | libarchive handles encoding detection. Fall back to raw bytes for path matching if detection fails. |
| 115 | Tar GNU vs POSIX (pax) header format differences | HANDLE | libarchive abstracts this. Same content = same result regardless of tar flavor. |
| 116 | Zip64 (entries > 4 GB) | HANDLE | libarchive supports Zip64. No special handling needed. |
| 117 | Archive entry is itself an archive format (but not nested decompression) | HANDLE | Compared as binary blob. Case #98. |
| 118 | Archive with comments | DOCUMENT | Comments ignored. We compare entry content only. |

## VI. Comparison Logic

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 119 | Identical content | HANDLE | Full comparison → `True`. |
| 120 | Difference at byte 0 | HANDLE | First chunk comparison → instant `False`. |
| 121 | Difference at last byte | HANDLE | `quick_check` catches via last-chunk sample. Without it: full read. |
| 122 | Same content, one has trailing null bytes | HANDLE | Different size → `False` (size pre-check). If sizes are same but content differs → `False`. |
| 123 | Very small file (1 byte) | HANDLE | One chunk, one comparison. Works. |
| 124 | File exactly `chunk_size` bytes | HANDLE | One full chunk + one empty read (EOF). Works. |
| 125 | File `chunk_size + 1` bytes | HANDLE | Two chunks. Works. |
| 126 | File `chunk_size - 1` bytes | HANDLE | One partial chunk. Works. |
| 127 | `chunk_size` > file size | HANDLE | One partial chunk. Works. |
| 128 | `quick_check` on non-seekable source | HANDLE | Auto-disable `quick_check`. Fall back to sequential. |
| 129 | `quick_check` finds match but full comparison finds diff | HANDLE | Correct by design. Samples matching ≠ fully equal. Full comparison always follows. |
| 130 | `compare_all([])` — empty list | HANDLE | `ConfigError("at least 2 sources required")`. |
| 131 | `compare_all([single])` — one source | HANDLE | `ConfigError("at least 2 sources required")`. |
| 132 | `compare_many` with 100+ sources | HANDLE | O(n) comparisons with first source as reference. Not O(n²). |
| 133 | `compare_dir_urls` with empty mapping | HANDLE | All local files in `only_left`. |
| 134 | `compare_dir_urls` with URL that 404s | HANDLE | `on_error="report"` → `DiffReason.READ_ERROR`. `on_error="raise"` → `SourceNotFoundError`. |

## VII. Concurrency / Threading

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 135 | `max_workers=0` | HANDLE | Auto-detect: `min(cpu_count, 8)`. |
| 136 | `max_workers=1` | HANDLE | Sequential execution. Valid. |
| 137 | `max_workers` > CPU count | HANDLE | Allowed. User's choice. Document that oversubscription may hurt performance. |
| 138 | `max_workers` > number of file pairs | HANDLE | Extra workers idle. No harm. |
| 139 | Two parallel comparisons using same source | HANDLE | Each opens own file descriptor / HTTP connection. No shared state. |
| 140 | File descriptor exhaustion under parallelism | HANDLE | Each worker uses ≤2 FDs. Max FDs = `max_workers * 2`. Default 16. Manageable. |
| 141 | Signal (SIGINT/SIGTERM) during comparison | HANDLE | C code checks for `PyErr_CheckSignals()` between chunks. Clean shutdown. |
| 142 | `KeyboardInterrupt` in Python | HANDLE | GIL acquire → `PyErr_CheckSignals()` → `KeyboardInterrupt` propagates. Thread pool cleans up. |
| 143 | Exception in one worker thread | HANDLE | Collect exception. Cancel remaining tasks. Report first error. |
| 144 | Thread safety of libcurl handles | HANDLE | Each thread gets own `CURL*` handle. No sharing. |
| 145 | Thread safety of libarchive | HANDLE | Each thread gets own `archive*` handle. No sharing. |
| 146 | Free-threaded Python: race conditions | HANDLE | No shared mutable state in C. All state is per-call or per-thread. Atomic ops for counters. |
| 147 | Thread pool shutdown while tasks running | HANDLE | Set `shutdown` flag. Workers finish current chunk, then exit. Bounded cleanup time. |
| 148 | Memory pressure under high parallelism | DOCUMENT | Max memory = `max_workers * 2 * chunk_size`. Default: 1 MB. Negligible. |

## VIII. Configuration / Validation

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 149 | `chunk_size=0` | HANDLE | `ConfigError("chunk_size must be > 0")`. |
| 150 | `chunk_size=-1` | HANDLE | `ConfigError("chunk_size must be > 0")`. |
| 151 | `chunk_size` not power of 2 | DOCUMENT | Allowed. Powers of 2 are optimal for alignment but not required. |
| 152 | Very large `chunk_size` (1 GB) | DOCUMENT | Allowed. Memory = `2 * chunk_size * max_workers`. User's choice. |
| 153 | `timeout=0` | HANDLE | `ConfigError("timeout must be > 0 or None")`. |
| 154 | `timeout < 0` | HANDLE | Same as #153. |
| 155 | `comparison_timeout=0` | PLANNED | `ConfigError`. Wall-clock enforcement not yet implemented in C. |
| 156 | Reserved | N/A | — |
| 157 | Reserved | N/A | — |
| 158 | `Source()` with local path | HANDLE | HTTP options ignored. File reader used. No error. |
| 159 | `Source()` with empty headers `{}` | HANDLE | Treated as no custom headers. Falls through to global. |
| 160 | `Source()` with empty URL `""` | HANDLE | `ConfigError("empty source path")`. |
| 161 | `configure()` called from multiple threads | HANDLE | Global config protected by mutex. Last write wins. |
| 162 | Per-call option conflicts with global config | DOCUMENT | Per-call always wins. Three-tier priority: `Source()` > call > `configure()`. |
| 163 | All archive limits set to `None` | DOCUMENT | No limits. Valid. User takes responsibility. |
| 164 | All archive limits set to `0` | HANDLE | `ConfigError("limit must be > 0 or None")`. |

## IX. Platform-Specific

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 165 | Windows: path > 260 chars | HANDLE | Use `\\?\` prefix for long paths on Windows. |
| 166 | Windows: reserved names (CON, PRN, NUL) | HANDLE | OS returns error → `SourceReadError`. |
| 167 | Windows: mandatory file locking | HANDLE | Cannot read locked file → `SourceReadError("file is locked")`. |
| 168 | Windows: backslash vs forward slash | HANDLE | Normalize to OS separator internally. Accept both in API. |
| 169 | Windows: drive letter case (`C:` vs `c:`) | HANDLE | Normalize to uppercase for same-source detection. |
| 170 | macOS: case-insensitive FS (APFS default) | HANDLE | `case_sensitive` auto-detection per filesystem. |
| 171 | macOS: resource forks (`._` files) | DOCUMENT | Included by default. User can exclude via `exclude_patterns`. |
| 172 | macOS: `.DS_Store` files | DOCUMENT | Same as #171. |
| 173 | Linux: files in `/proc`, `/sys` | HANDLE | Rejected if not regular file (#8). |
| 174 | Linux: SELinux/AppArmor denying access | HANDLE | OS returns `EACCES` → `SourceReadError`. |
| 175 | Docker: overlay filesystem | DOCUMENT | Works normally. Overlay is POSIX-compliant. |
| 176 | Cross-platform line endings (CRLF vs LF) | DOCUMENT | Byte comparison. `\r\n` ≠ `\n`. This is correct — we compare content, not text. |

## X. Python Integration

| # | Case | Status | Behavior |
|---|------|--------|----------|
| 177 | Called from multiple Python threads | HANDLE | GIL released during C work. Thread-safe by design. |
| 178 | Sync API called from async context | DOCUMENT | Works but blocks event loop. Document: use `komparu.aio` in async code. |
| 179 | Async API called without event loop | HANDLE | Python raises `RuntimeError`. Standard asyncio behavior. |
| 180 | Memory leak in C extension | HANDLE | Valgrind / ASan testing in CI. Proper cleanup in all error paths. |
| 181 | Garbage collection during comparison | HANDLE | C holds references to Python objects correctly. No dangling pointers. |
| 182 | Subinterpreter safety (3.12+) | HANDLE | Use multi-phase init (`Py_mod_create`). Per-interpreter state, no globals. |
| 183 | `pickle` / `copy` of result objects | HANDLE | `DirResult`, `CompareResult` are frozen dataclasses. Picklable by default. |
| 184 | Python 3.12 vs 3.13 vs 3.14 C API differences | HANDLE | `compat.h` with version conditionals. CI tests all versions. |
| 185 | PyPy compatibility | DOCUMENT | Not supported in v1. C extension uses CPython-specific API. |
