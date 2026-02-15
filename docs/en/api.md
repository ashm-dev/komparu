# komparu — API Reference

## Installation

```bash
pip install komparu
```

## Source Type

Sources can be passed as plain strings or as `Source` objects.

- **Plain string** — uses global HTTP options from function parameters
- **`Source()` object** — per-source HTTP config, overrides global

```python
from komparu import Source

# Plain strings use global headers
komparu.compare("https://a.com/f", "https://b.com/f", headers={"Auth": "token"})

# Source() overrides global config for that specific URL
komparu.compare(
    Source("https://s3.aws.com/file", headers={"Authorization": "Bearer aws_token"}),
    Source("https://other.cdn.com/file", headers={"X-Api-Key": "key123"}),
)

# Mix: plain strings get global config, Source() gets its own
komparu.compare_all(
    [
        "https://a.com/f",                                                  # global headers
        "https://b.com/f",                                                  # global headers
        Source("https://special.com/f", headers={"X-Key": "other_key"}),    # own headers
    ],
    headers={"Authorization": "Bearer token"},
)
```

### Source

```python
@dataclass(frozen=True, slots=True)
class Source:
    url: str
    headers: dict[str, str] | None = None
    timeout: float | None = None
    follow_redirects: bool | None = None
    verify_ssl: bool | None = None
    proxy: str | None = None
```

Fields set to `None` fall back to global options. Local paths can also be wrapped in `Source()` but HTTP options are ignored for them.

## Sync API

```python
import komparu
```

### komparu.compare(source_a, source_b, **options) -> bool

Compare two sources byte-by-byte.

```python
# Local files
komparu.compare("/path/to/file_a", "/path/to/file_b")

# Remote files
komparu.compare("https://s3.example.com/a.bin", "https://s3.example.com/b.bin")

# Mixed
komparu.compare("/local/file", "https://cdn.example.com/file")

# Global HTTP headers (applied to all URL sources)
komparu.compare(
    "/local/file",
    "https://s3.example.com/file",
    headers={"Authorization": "Bearer token123"},
)

# Per-source headers
komparu.compare(
    Source("https://s3.aws.com/file", headers={"Authorization": "Bearer aws"}),
    Source("https://gcs.google.com/file", headers={"Authorization": "Bearer gcp"}),
)

# Custom chunk size
komparu.compare("file_a", "file_b", chunk_size=131072)  # 128 KB
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `source_a` | `str \| Source` | required | Path, URL, or Source object |
| `source_b` | `str \| Source` | required | Path, URL, or Source object |
| `chunk_size` | `int` | `65536` | Chunk size in bytes |
| `headers` | `dict[str, str]` | `None` | Global HTTP headers (applied to all URL sources without own config) |
| `timeout` | `float` | `30.0` | Global HTTP timeout in seconds |
| `size_precheck` | `bool` | `True` | Compare sizes before content |
| `follow_redirects` | `bool` | `True` | Follow HTTP redirects |
| `verify_ssl` | `bool` | `True` | Verify SSL certificates |
| `quick_check` | `bool` | `True` | Sample first/last/middle chunks before full comparison (seekable sources only) |
| `proxy` | `str` | `None` | Proxy URL (e.g. `http://host:port`, `socks5://host:port`) |

**Priority:** Function parameters are the defaults. `Source().headers` override the `headers` parameter. `configure()` sets fallback `headers` and SSRF protection (`allow_private_redirects`).

### komparu.compare_dir(dir_a, dir_b, **options) -> DirResult

Compare two directories recursively.

```python
result = komparu.compare_dir("/dir_a", "/dir_b")

if result.equal:
    print("Directories are identical")
else:
    print("Only in left:", result.only_left)
    print("Only in right:", result.only_right)
    print("Content differs:", result.diff)
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `dir_a` | `str` | required | First directory path |
| `dir_b` | `str` | required | Second directory path |
| `chunk_size` | `int` | `65536` | Chunk size in bytes |
| `size_precheck` | `bool` | `True` | Compare sizes before content |
| `quick_check` | `bool` | `True` | Sample first/last/middle before full scan |
| `follow_symlinks` | `bool` | `True` | Follow symbolic links |
| `max_workers` | `int` | `0` (auto) | Thread pool size (0=auto, 1=sequential) |

### komparu.compare_archive(archive_a, archive_b, **options) -> DirResult

Compare two archives as virtual directories.

```python
result = komparu.compare_archive("backup_v1.tar.gz", "backup_v2.zip")
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `path_a` | `str` | required | First archive path |
| `path_b` | `str` | required | Second archive path |
| `chunk_size` | `int` | `65536` | Chunk size in bytes |
| `max_decompressed_size` | `int` | `1 GB` | Max total decompressed bytes |
| `max_compression_ratio` | `int` | `200` | Max compression ratio |
| `max_archive_entries` | `int` | `100000` | Max number of entries |
| `max_entry_name_length` | `int` | `4096` | Max entry path length |

### komparu.compare_all(sources, **options) -> bool

Check if all sources are identical.

```python
all_same = komparu.compare_all([
    "/local/copy",
    "https://cdn1.example.com/file",
    "https://cdn2.example.com/file",
])
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `sources` | `list[str \| Source]` | required | List of file paths, URLs, or Source objects |
| `chunk_size` | `int` | `65536` | Chunk size in bytes |
| `size_precheck` | `bool` | `True` | Compare sizes before content |
| `quick_check` | `bool` | `True` | Sample first/last/middle before full scan |
| `headers` | `dict[str, str]` | `None` | Global HTTP headers |
| `timeout` | `float` | `30.0` | HTTP timeout in seconds |
| `follow_redirects` | `bool` | `True` | Follow HTTP redirects |
| `verify_ssl` | `bool` | `True` | Verify SSL certificates |
| `max_workers` | `int` | `0` (auto) | Thread pool size (0=auto, 1=sequential). Sync only. |
| `proxy` | `str` | `None` | Proxy URL (e.g. `http://host:port`, `socks5://host:port`) |

### komparu.compare_many(sources, **options) -> CompareResult

Detailed comparison of multiple sources.

```python
result = komparu.compare_many(["file_a", "file_b", "file_c"])

result.all_equal          # bool
result.groups             # list[set[str]] — groups of identical sources
result.diff               # dict[tuple[str, str], bool] — pairwise results
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `sources` | `list[str \| Source]` | required | List of file paths, URLs, or Source objects |
| `chunk_size` | `int` | `65536` | Chunk size in bytes |
| `size_precheck` | `bool` | `True` | Compare sizes before content |
| `quick_check` | `bool` | `True` | Sample first/last/middle before full scan |
| `headers` | `dict[str, str]` | `None` | Global HTTP headers |
| `timeout` | `float` | `30.0` | HTTP timeout in seconds |
| `follow_redirects` | `bool` | `True` | Follow HTTP redirects |
| `verify_ssl` | `bool` | `True` | Verify SSL certificates |
| `max_workers` | `int` | `0` (auto) | Thread pool size (0=auto, 1=sequential). Sync only. |
| `proxy` | `str` | `None` | Proxy URL (e.g. `http://host:port`, `socks5://host:port`) |

### komparu.compare_dir_urls(directory, url_map, **options) -> DirResult

Compare local directory against URL mapping.

```python
result = komparu.compare_dir_urls(
    "/local/assets",
    {
        "logo.png": "https://cdn.example.com/logo.png",
        "style.css": "https://cdn.example.com/style.css",
    },
    headers={"Authorization": "Bearer token"},
)
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `dir_path` | `str` | required | Path to local directory |
| `url_map` | `dict[str, str]` | required | Mapping of relative_path to URL |
| `chunk_size` | `int` | `65536` | Chunk size in bytes |
| `size_precheck` | `bool` | `True` | Compare sizes before content |
| `quick_check` | `bool` | `True` | Sample first/last/middle before full scan |
| `headers` | `dict[str, str]` | `None` | Global HTTP headers |
| `timeout` | `float` | `30.0` | HTTP timeout in seconds |
| `follow_redirects` | `bool` | `True` | Follow HTTP redirects |
| `verify_ssl` | `bool` | `True` | Verify SSL certificates |
| `max_workers` | `int` | `0` (auto) | Thread pool size (0=auto, 1=sequential). Sync only. |
| `proxy` | `str` | `None` | Proxy URL (e.g. `http://host:port`, `socks5://host:port`) |

## Async API

```python
import komparu.aio
```

Same interface, all functions are coroutines.

```python
result = await komparu.aio.compare("/path/a", "https://example.com/b")
result = await komparu.aio.compare_dir("/dir_a", "/dir_b")
result = await komparu.aio.compare_archive("a.zip", "b.tar.gz")
result = await komparu.aio.compare_all([...])
result = await komparu.aio.compare_many([...])
result = await komparu.aio.compare_dir_urls("/dir", {...})
```

## Result Types

### DirResult

```python
@dataclass(frozen=True, slots=True)
class DirResult:
    equal: bool                     # All files identical
    diff: dict[str, DiffReason]     # Files with different content
    only_left: set[str]             # Files only in first source
    only_right: set[str]            # Files only in second source
```

### CompareResult

```python
@dataclass(frozen=True, slots=True)
class CompareResult:
    all_equal: bool                         # All sources identical
    groups: list[set[str]]                  # Groups of identical sources
    diff: dict[tuple[str, str], bool]       # Pairwise results
```

### DiffReason (enum)

```python
class DiffReason(str, Enum):
    CONTENT_MISMATCH = "content_mismatch"   # Content differs
    SIZE_MISMATCH = "size_mismatch"         # Size differs
    MISSING = "missing"                     # File missing in one side
    TYPE_MISMATCH = "type_mismatch"         # File vs directory
    READ_ERROR = "read_error"               # Could not read one side
```

## Configuration

### Global defaults

```python
komparu.configure(
    # I/O
    chunk_size=65536,
    max_workers=0,                         # 0 = auto (min(cpu, 8))
    timeout=30.0,
    follow_redirects=True,
    verify_ssl=True,
    size_precheck=True,
    quick_check=True,

    # HTTP
    headers={},

    # Archive safety limits
    max_decompressed_size=1 * 1024**3,    # 1 GB per archive
    max_compression_ratio=200,             # abort if ratio exceeds this
    max_archive_entries=100_000,           # max files per archive
    max_entry_name_length=4096,            # max path length per entry

    # General limits
    comparison_timeout=300.0,              # 5 min wall-clock per call

    # Proxy
    proxy=None,                            # None = direct connection

    # SSRF protection
    allow_private_redirects=False,         # block redirects to private networks
)
```

All function parameters have explicit defaults. `configure()` sets fallback `headers` and `allow_private_redirects` (SSRF protection). Archive safety limits can be adjusted per-call.

## Errors

```python
class KomparuError(Exception): ...           # Base
class SourceNotFoundError(KomparuError): ...  # File/URL not found
class SourceReadError(KomparuError): ...      # I/O or HTTP error
class ArchiveError(KomparuError): ...         # Cannot read archive
class ArchiveBombError(ArchiveError): ...     # Decompression bomb / limit exceeded
class ConfigError(KomparuError): ...          # Invalid configuration
class ComparisonTimeoutError(KomparuError):.. # Wall-clock timeout exceeded
```
