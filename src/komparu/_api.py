"""komparu public API implementation."""

from __future__ import annotations

from komparu._types import Source, CompareResult
from komparu._config import get_config
from komparu._core import compare as _compare_c
from komparu._core import compare_dir as _compare_dir_c
from komparu._core import compare_archive as _compare_archive_c
from komparu._core import compare_dir_urls as _compare_dir_urls_c
from komparu._validate import validate_path, validate_chunk_size, validate_timeout, validate_max_workers
from komparu._helpers import resolve_headers, build_dir_result

from komparu._types import DirResult  # noqa: F401 — re-export for type annotations


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
    validate_path(source_a, "source_a")
    validate_path(source_b, "source_b")
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)

    cfg = get_config()

    path_a = source_a.url if isinstance(source_a, Source) else source_a
    path_b = source_b.url if isinstance(source_b, Source) else source_b

    global_h = headers if headers is not None else (cfg.headers or None)
    h_a = resolve_headers(source_a, global_h)
    h_b = resolve_headers(source_b, global_h)
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
    validate_path(dir_a, "dir_a")
    validate_path(dir_b, "dir_b")
    validate_chunk_size(chunk_size)
    validate_max_workers(max_workers)

    raw = _compare_dir_c(
        dir_a, dir_b,
        chunk_size=chunk_size,
        size_precheck=size_precheck,
        quick_check=quick_check,
        follow_symlinks=follow_symlinks,
        max_workers=max_workers,
    )
    return build_dir_result(raw)


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
    validate_path(path_a, "path_a")
    validate_path(path_b, "path_b")
    validate_chunk_size(chunk_size)

    raw = _compare_archive_c(
        path_a, path_b,
        chunk_size=chunk_size,
        max_decompressed_size=max_decompressed_size,
        max_compression_ratio=max_compression_ratio,
        max_entries=max_archive_entries,
        max_entry_name_length=max_entry_name_length,
        hash_compare=hash_compare,
    )
    return build_dir_result(raw)


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
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)
    validate_max_workers(max_workers)

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

    from concurrent.futures import ThreadPoolExecutor, as_completed

    pool_size = max_workers if max_workers > 0 else min(len(others), 8)
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = [pool.submit(compare, ref, s, **kwargs) for s in others]
        try:
            for f in as_completed(futures):
                if not f.result():
                    return False
        finally:
            for f in futures:
                f.cancel()
        return True


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
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)
    validate_max_workers(max_workers)

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

    names = [s.url if isinstance(s, Source) else s for s in sources]
    diff: dict[tuple[str, str], bool] = {}
    for i, j, eq in results:
        diff[(names[i], names[j])] = eq

    all_equal = all(eq for _, _, eq in results)

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

    All I/O runs in C: dirwalk via openat/fstatat, HTTP via libcurl,
    file comparison via mmap. GIL is released for the entire operation.

    :param dir_path: Path to local directory.
    :param url_map: Mapping of relative_path -> URL.
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    validate_path(dir_path, "dir_path")
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)

    cfg = get_config()

    h = headers if headers is not None else (cfg.headers or None)
    p = proxy if proxy is not None else cfg.proxy

    raw = _compare_dir_urls_c(
        dir_path, url_map,
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
    return build_dir_result(raw)
