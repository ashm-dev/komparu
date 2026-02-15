# komparu — Security: Archive & Resource Limits

## Attack Vectors

### 1. Classic Zip Bomb

Small compressed file → massive decompressed output.
Example: 42.zip — 42 KB compressed → 4.5 PB decompressed.

**Our defense:** `max_decompressed_size` + `max_compression_ratio`.
Streaming read means memory is always O(chunk_size), but CPU time grows with decompressed size.

### 2. Recursive Bomb

Archive inside archive inside archive. Each level multiplies decompression work.

**Our defense:** Nested archives are **never recursively decompressed**. An entry that is itself an archive is compared as a binary blob. This is a hard rule, not configurable.

### 3. Entry Flood

Archive with millions of tiny files. Kills time on entry enumeration and path matching.

**Our defense:** `max_archive_entries`.

### 4. Path Traversal

Entry paths like `../../etc/passwd`. We don't extract to disk, but paths are used for matching between archives.

**Our defense:** Path sanitization — always on, not configurable:
- Strip leading `/`
- Resolve and reject `..` components
- Normalize separators to `/`
- Reject entries with null bytes in names

### 5. Entry Name Bomb

Extremely long filenames consuming memory during path matching.

**Our defense:** `max_entry_name_length`.

### 6. Slow Decompression (Algorithmic Bomb)

Crafted data that is technically within size limits but maximizes decompression CPU time.

**Our defense:** `comparison_timeout` — wall-clock time limit per comparison call.

### 7. Corrupted/Malformed Archives

Truncated headers, invalid checksums, broken streams.

**Our defense:** libarchive returns errors, we surface as `ArchiveError` with details.

## Limit Configuration

### Defaults — Secure by Default

Limits are **enabled by default** with generous but safe values.
Users who compare large legitimate archives raise limits explicitly.

```python
komparu.configure(
    # Archive limits
    max_decompressed_size=1 * 1024**3,    # 1 GB per archive
    max_compression_ratio=200,             # max ratio decompressed/compressed
    max_archive_entries=100_000,           # max files per archive
    max_entry_name_length=4096,            # max path length per entry (bytes)

    # General limits
    comparison_timeout=300.0,              # 5 min wall-clock per comparison call
)
```

### Disabling Limits

For trusted environments (internal tools, CI):

```python
komparu.configure(
    max_decompressed_size=None,    # no limit
    max_compression_ratio=None,    # no limit
    max_archive_entries=None,      # no limit
    comparison_timeout=None,       # no limit
)
```

### Per-Call Override

```python
# This specific comparison allows larger archives
result = komparu.compare_archive(
    "huge_backup_a.tar.gz",
    "huge_backup_b.tar.gz",
    max_decompressed_size=50 * 1024**3,   # 50 GB for this call
    comparison_timeout=3600.0,             # 1 hour
)
```

## Limit Behavior

| Limit | Scope | On Exceed |
|-------|-------|-----------|
| `max_decompressed_size` | Per archive | `ArchiveBombError("decompressed size 1.2 GB exceeds limit 1 GB")` |
| `max_compression_ratio` | Per archive, checked after each entry | `ArchiveBombError("compression ratio 350:1 exceeds limit 200:1")` |
| `max_archive_entries` | Per archive | `ArchiveBombError("entry count 150000 exceeds limit 100000")` |
| `max_entry_name_length` | Per entry | `ArchiveBombError("entry name 8500 bytes exceeds limit 4096")` |
| `comparison_timeout` | Per compare call (wall-clock) | `TimeoutError("comparison exceeded 300s timeout")` |

All limit errors are subclasses of `ArchiveBombError(ArchiveError)` (except timeout).
Comparison stops immediately. No partial results.

## SSRF Protection

HTTP redirects can be abused to access internal services.
Attacker scenario: `https://attacker.com/file` redirects to `http://localhost:8080/admin`.

**Default behavior:** Block redirects to private/internal networks:
- `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- `::1`, `fe80::/10`
- `localhost`, `*.local`

**Implementation:**
- `CURLOPT_REDIR_PROTOCOLS` — restrict to HTTP/HTTPS only (no `file://`, `gopher://`, etc.)
- Redirect callback validates target IP against blocklist before following
- Configurable: `allow_private_redirects=False` (default)

```python
# For internal/trusted networks where redirects to private IPs are expected
komparu.configure(allow_private_redirects=True)
```

## SIGBUS Protection (mmap)

When a file is truncated while memory-mapped, accessing beyond the new size
causes `SIGBUS` — a hardware signal that crashes the Python interpreter.

**Implementation:**
- Install `sigaction` handler for `SIGBUS` in C init
- Use `sigsetjmp`/`siglongjmp` to catch and convert to `SourceReadError`
- Handler is per-thread (thread-safe)
- Fallback: if SIGBUS handling is unreliable on platform, use buffered `read()` instead of `mmap`

## Hard Rules (Always On, Not Configurable)

| Rule | Rationale |
|------|-----------|
| Streaming only — never write to disk | Memory safety |
| No recursive archive decompression | Prevents exponential bombs |
| Path sanitization (strip `..`, leading `/`, null bytes) | Prevents path confusion in matching |
| Memory = O(chunk_size) per active comparison | Predictable resource usage |

## Resource Awareness

### Thread Pool + Archives

When comparing directories/archives in parallel:
- Each worker holds 2 * chunk_size memory (two read buffers)
- Max memory from workers: `max_workers * 2 * chunk_size`
- Default: 8 * 2 * 64 KB = 1 MB — negligible
- File descriptors: limited by `max_workers` (each worker opens at most 2 FDs at a time)

### HTTP + Archives

Remote archive (URL) comparison:
- Archive is streamed via HTTP Range requests
- Decompressed on the fly — never fully downloaded
- Limits apply to decompressed output, not download size
- `timeout` (HTTP) and `comparison_timeout` work independently

## Error Hierarchy

```python
class KomparuError(Exception): ...
class ArchiveError(KomparuError): ...           # General archive errors
class ArchiveBombError(ArchiveError): ...       # Bomb/limit violations
class TimeoutError(KomparuError): ...           # Comparison timeout
```

## Recommendations by Use Case

### Public API (untrusted input)

```python
komparu.configure(
    max_decompressed_size=100 * 1024**2,   # 100 MB
    max_compression_ratio=50,
    max_archive_entries=10_000,
    max_entry_name_length=1024,
    comparison_timeout=60.0,
)
```

### Internal CI/CD

```python
komparu.configure(
    max_decompressed_size=10 * 1024**3,    # 10 GB
    max_compression_ratio=200,
    max_archive_entries=100_000,
    comparison_timeout=600.0,
)
```

### Trusted Environment

```python
komparu.configure(
    max_decompressed_size=None,
    max_compression_ratio=None,
    max_archive_entries=None,
    comparison_timeout=None,
)
```
