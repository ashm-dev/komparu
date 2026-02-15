"""komparu — ultra-fast file comparison library.

:func:`compare` — compare two files byte-by-byte.
:func:`compare_dir` — compare two directories recursively.
:func:`compare_archive` — compare two archives as virtual directories.
:func:`compare_all` — check if all sources are identical.
:func:`compare_many` — detailed comparison of multiple sources.
:func:`compare_dir_urls` — compare directory against URL mapping.
:func:`configure` — set global defaults.
"""

from __future__ import annotations

__version__ = "0.1.0"

from komparu._types import (
    Source,
    DirResult,
    CompareResult,
    DiffReason,
    KomparuError,
    SourceNotFoundError,
    SourceReadError,
    ArchiveError,
    ArchiveBombError,
    ConfigError,
    ComparisonTimeoutError,
)
from komparu._config import configure, get_config, reset_config

# Import C extension
from komparu._core import compare as _compare_c
from komparu._core import compare_dir as _compare_dir_c
from komparu._core import compare_archive as _compare_archive_c


def _resolve_headers(source: str | Source, global_headers: dict[str, str] | None) -> dict[str, str] | None:
    """Merge per-source headers with global headers. Source wins."""
    if isinstance(source, Source) and source.headers:
        if global_headers:
            merged = dict(global_headers)
            merged.update(source.headers)
            return merged
        return source.headers
    return global_headers


def compare(
    source_a: str | Source,
    source_b: str | Source,
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    proxy: str | None = None,
) -> bool:
    """Compare two sources byte-by-byte.

    :param source_a: File path, URL, or Source object.
    :param source_b: File path, URL, or Source object.
    :param chunk_size: Chunk size in bytes.
    :param size_precheck: Compare sizes before content.
    :param quick_check: Sample key offsets before full scan.
    :param headers: Global HTTP headers for URL sources.
    :param timeout: HTTP timeout in seconds.
    :param follow_redirects: Follow HTTP redirects.
    :param verify_ssl: Verify SSL certificates.
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    :returns: True if sources are byte-identical.
    """
    cfg = get_config()

    path_a = source_a.url if isinstance(source_a, Source) else source_a
    path_b = source_b.url if isinstance(source_b, Source) else source_b

    global_h = headers if headers is not None else (cfg.headers or None)
    # Per-source headers override global headers (Source.headers wins)
    h_a = _resolve_headers(source_a, global_h)
    h_b = _resolve_headers(source_b, global_h)
    # Use merged headers if both sources have the same resolved headers,
    # otherwise use the first non-None set (C API takes a single headers dict)
    h = h_a or h_b or global_h

    p = proxy if proxy is not None else cfg.proxy

    return _compare_c(
        path_a, path_b,
        chunk_size=chunk_size,
        size_precheck=size_precheck,
        quick_check=quick_check,
        headers=h if h else None,
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify_ssl=verify_ssl,
        allow_private=cfg.allow_private_redirects,
        proxy=p,
    )


def _build_dir_result(raw: dict) -> DirResult:
    """Convert C extension dict to DirResult."""
    diff = {k: DiffReason(v) for k, v in raw["diff"].items()}
    return DirResult(
        equal=raw["equal"],
        diff=diff,
        only_left=raw["only_left"],
        only_right=raw["only_right"],
    )


def compare_dir(
    dir_a: str,
    dir_b: str,
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    follow_symlinks: bool = True,
    max_workers: int = 0,
) -> DirResult:
    """Compare two directories recursively.

    :param dir_a: Path to first directory.
    :param dir_b: Path to second directory.
    :param chunk_size: Chunk size for file comparison.
    :param size_precheck: Compare file sizes before content.
    :param quick_check: Sample key offsets before full scan.
    :param follow_symlinks: Follow symbolic links during traversal.
    :param max_workers: Thread pool size (0=auto, 1=sequential).
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    raw = _compare_dir_c(
        dir_a, dir_b,
        chunk_size=chunk_size,
        size_precheck=size_precheck,
        quick_check=quick_check,
        follow_symlinks=follow_symlinks,
        max_workers=max_workers,
    )
    return _build_dir_result(raw)


def compare_archive(
    path_a: str,
    path_b: str,
    *,
    chunk_size: int = 65536,
    max_decompressed_size: int = 1073741824,
    max_compression_ratio: int = 200,
    max_archive_entries: int = 100_000,
    max_entry_name_length: int = 4096,
    hash_compare: bool = False,
) -> DirResult:
    """Compare two archive files entry-by-entry.

    :param path_a: Path to first archive file.
    :param path_b: Path to second archive file.
    :param chunk_size: Chunk size in bytes.
    :param max_decompressed_size: Max total decompressed bytes (bomb limit).
    :param max_compression_ratio: Max compression ratio (bomb limit).
    :param max_archive_entries: Max number of archive entries (bomb limit).
    :param max_entry_name_length: Max entry path length (bomb limit).
    :param hash_compare: Use hash-based comparison (O(entries) memory instead
        of O(total_decompressed)). Computes streaming FNV-1a 128-bit fingerprint
        of each entry instead of storing full content.
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    raw = _compare_archive_c(
        path_a, path_b,
        chunk_size=chunk_size,
        max_decompressed_size=max_decompressed_size,
        max_compression_ratio=max_compression_ratio,
        max_entries=max_archive_entries,
        max_entry_name_length=max_entry_name_length,
        hash_compare=hash_compare,
    )
    return _build_dir_result(raw)


def compare_all(
    sources: list[str | Source],
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    max_workers: int = 0,
    proxy: str | None = None,
) -> bool:
    """Check if all sources are byte-identical.

    Compares source[0] against all others in parallel.

    :param sources: List of file paths, URLs, or Source objects.
    :param max_workers: Thread pool size (0=auto, 1=sequential).
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    :returns: True if all sources are identical.
    """
    if len(sources) < 2:
        return True

    kwargs: dict = {
        "chunk_size": chunk_size,
        "size_precheck": size_precheck,
        "quick_check": quick_check,
        "headers": headers,
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "verify_ssl": verify_ssl,
        "proxy": proxy,
    }

    ref = sources[0]
    others = sources[1:]

    if max_workers == 1 or len(others) == 1:
        return all(compare(ref, s, **kwargs) for s in others)

    from concurrent.futures import ThreadPoolExecutor

    pool_size = max_workers if max_workers > 0 else min(len(others), 8)
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = [pool.submit(compare, ref, s, **kwargs) for s in others]
        return all(f.result() for f in futures)


def compare_many(
    sources: list[str | Source],
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    max_workers: int = 0,
    proxy: str | None = None,
) -> CompareResult:
    """Detailed pairwise comparison of multiple sources.

    :param sources: List of file paths, URLs, or Source objects.
    :param max_workers: Thread pool size (0=auto, 1=sequential).
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    :returns: CompareResult with all_equal, groups, diff.
    """
    kwargs: dict = {
        "chunk_size": chunk_size,
        "size_precheck": size_precheck,
        "quick_check": quick_check,
        "headers": headers,
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "verify_ssl": verify_ssl,
        "proxy": proxy,
    }

    n = len(sources)
    if n < 2:
        names = [s.url if isinstance(s, Source) else s for s in sources]
        return CompareResult(all_equal=True, groups=[set(names)], diff={})

    # Generate all pairs
    pairs: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((i, j))

    def _cmp_pair(pair: tuple[int, int]) -> tuple[int, int, bool]:
        i, j = pair
        return i, j, compare(sources[i], sources[j], **kwargs)

    if max_workers == 1 or len(pairs) == 1:
        results = [_cmp_pair(p) for p in pairs]
    else:
        from concurrent.futures import ThreadPoolExecutor

        pool_size = max_workers if max_workers > 0 else min(len(pairs), 8)
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            results = list(pool.map(_cmp_pair, pairs))

    # Build diff dict
    names = [s.url if isinstance(s, Source) else s for s in sources]
    diff: dict[tuple[str, str], bool] = {}
    for i, j, eq in results:
        diff[(names[i], names[j])] = eq

    all_equal = all(eq for _, _, eq in results)

    # Build groups via union-find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i, j, eq in results:
        if eq:
            union(i, j)

    group_map: dict[int, set[str]] = {}
    for i in range(n):
        root = find(i)
        if root not in group_map:
            group_map[root] = set()
        group_map[root].add(names[i])

    return CompareResult(
        all_equal=all_equal,
        groups=list(group_map.values()),
        diff=diff,
    )


def compare_dir_urls(
    dir_path: str,
    url_map: dict[str, str],
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    max_workers: int = 0,
    proxy: str | None = None,
) -> DirResult:
    """Compare directory files against URL mapping.

    :param dir_path: Path to local directory.
    :param url_map: Mapping of relative_path -> URL.
    :param max_workers: Thread pool size (0=auto, 1=sequential).
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    import os

    kwargs: dict = {
        "chunk_size": chunk_size,
        "size_precheck": size_precheck,
        "quick_check": quick_check,
        "headers": headers,
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "verify_ssl": verify_ssl,
        "proxy": proxy,
    }

    # Walk local directory for relative paths
    local_files: set[str] = set()
    for root, _dirs, files in os.walk(dir_path):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), dir_path)
            local_files.add(rel)

    url_keys = set(url_map.keys())
    only_left = local_files - url_keys
    only_right = url_keys - local_files
    common = local_files & url_keys

    diff: dict[str, DiffReason] = {}

    if common:
        def _cmp_entry(rel: str) -> tuple[str, bool]:
            local_path = os.path.join(dir_path, rel)
            return rel, compare(local_path, url_map[rel], **kwargs)

        if max_workers == 1 or len(common) == 1:
            results = [_cmp_entry(r) for r in sorted(common)]
        else:
            from concurrent.futures import ThreadPoolExecutor

            pool_size = max_workers if max_workers > 0 else min(len(common), 8)
            with ThreadPoolExecutor(max_workers=pool_size) as pool:
                results = list(pool.map(_cmp_entry, sorted(common)))

        for rel, eq in results:
            if not eq:
                diff[rel] = DiffReason.CONTENT_MISMATCH

    equal = len(only_left) == 0 and len(only_right) == 0 and len(diff) == 0
    return DirResult(
        equal=equal,
        diff=diff,
        only_left=only_left,
        only_right=only_right,
    )


__all__ = [
    "__version__",
    "compare",
    "compare_dir",
    "compare_archive",
    "compare_all",
    "compare_many",
    "compare_dir_urls",
    "configure",
    "get_config",
    "reset_config",
    "Source",
    "DirResult",
    "CompareResult",
    "DiffReason",
    "KomparuError",
    "SourceNotFoundError",
    "SourceReadError",
    "ArchiveError",
    "ArchiveBombError",
    "ConfigError",
    "ComparisonTimeoutError",
]
