"""komparu.aio — native async API.

All I/O runs in C threads (pool + libcurl/mmap). No Python HTTP
libraries. Completion notification via eventfd/pipe integrated
with asyncio.loop.add_reader(). Event loop never blocks.

Usage::

    import komparu.aio

    result = await komparu.aio.compare("/path/a", "/path/b")
    result = await komparu.aio.compare("https://a.com/f", "https://b.com/f")
    dir_result = await komparu.aio.compare_dir("/dir_a", "/dir_b")
    all_same = await komparu.aio.compare_all(["/a", "/b", "/c"])
"""

from __future__ import annotations

import asyncio
from typing import Any

from komparu._config import get_config
from komparu._core import (
    async_compare_start,
    async_compare_result,
    async_compare_dir_start,
    async_compare_dir_result,
    async_compare_archive_start,
    async_compare_archive_result,
    async_compare_dir_urls_start,
    async_compare_dir_urls_result,
)
from komparu._types import CompareResult, DirResult, Source
from komparu._validate import validate_path, validate_chunk_size, validate_timeout, validate_max_workers
from komparu._helpers import build_dir_result, filter_dir_result


def _source_path(source: str | Source) -> str:
    return source.url if isinstance(source, Source) else source


async def _await_task(fd: int, get_result):
    """Register notification fd with asyncio and await completion."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def _on_ready():
        loop.remove_reader(fd)
        if future.done():
            return
        try:
            result = get_result()
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)

    loop.add_reader(fd, _on_ready)
    try:
        return await future
    finally:
        # Ensure reader is removed even if the coroutine is cancelled
        loop.remove_reader(fd)


# =========================================================================
# Public async API
# =========================================================================


async def compare(
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
    """Compare two sources byte-by-byte (async).

    All I/O runs in C threads. Event loop never blocks.

    :param source_a: File path, URL, or Source object.
    :param source_b: File path, URL, or Source object.
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    :returns: True if sources are byte-identical.
    """
    validate_path(source_a, "source_a")
    validate_path(source_b, "source_b")
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)

    cfg = get_config()

    path_a = _source_path(source_a)
    path_b = _source_path(source_b)

    h = headers if headers is not None else (cfg.headers or None)
    p = proxy if proxy is not None else cfg.proxy

    fd, task = async_compare_start(
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

    return await _await_task(fd, lambda: async_compare_result(task))


async def compare_dir(
    dir_a: str,
    dir_b: str,
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    follow_symlinks: bool = True,
    max_workers: int = 0,
    ignore: list[str] | None = None,
) -> DirResult:
    """Compare two directories recursively (async).

    Directory walk and file comparisons run in C threads.

    :param dir_a: Path to first directory.
    :param dir_b: Path to second directory.
    :param ignore: Glob patterns to exclude (matched per path component).
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    validate_path(dir_a, "dir_a")
    validate_path(dir_b, "dir_b")
    validate_chunk_size(chunk_size)
    validate_max_workers(max_workers)

    fd, task = async_compare_dir_start(
        dir_a, dir_b,
        chunk_size=chunk_size,
        size_precheck=size_precheck,
        quick_check=quick_check,
        follow_symlinks=follow_symlinks,
        max_workers=max_workers,
    )

    raw = await _await_task(fd, lambda: async_compare_dir_result(task))
    result = build_dir_result(raw)
    if ignore:
        result = filter_dir_result(result, ignore)
    return result


async def compare_archive(
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
    """Compare two archive files entry-by-entry (async).

    Archive I/O runs in a C thread via libarchive. Completion
    notification via eventfd integrated with asyncio.

    :param hash_compare: Use hash-based comparison (O(entries) memory
        instead of O(total_decompressed)).
    """
    validate_path(path_a, "path_a")
    validate_path(path_b, "path_b")
    validate_chunk_size(chunk_size)

    fd, task = async_compare_archive_start(
        path_a, path_b,
        chunk_size=chunk_size,
        max_decompressed_size=max_decompressed_size,
        max_compression_ratio=max_compression_ratio,
        max_entries=max_archive_entries,
        max_entry_name_length=max_entry_name_length,
        hash_compare=hash_compare,
    )

    raw = await _await_task(fd, lambda: async_compare_archive_result(task))
    return build_dir_result(raw)


async def compare_all(
    sources: list[str | Source],
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
    """Check if all sources are identical (async).

    Compares source[0] against all others concurrently.
    """
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)

    if len(sources) < 2:
        return True

    kwargs: dict[str, Any] = {
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
    coros = [compare(ref, s, **kwargs) for s in sources[1:]]
    results = await asyncio.gather(*coros)
    return all(results)


async def compare_many(
    sources: list[str | Source],
    *,
    chunk_size: int = 65536,
    size_precheck: bool = True,
    quick_check: bool = True,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    proxy: str | None = None,
) -> CompareResult:
    """Detailed pairwise comparison of multiple sources (async).

    All pairs compared concurrently via asyncio.gather().
    """
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)

    kwargs: dict[str, Any] = {
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
    names = [_source_path(s) for s in sources]

    if n < 2:
        return CompareResult(all_equal=True, groups=[set(names)], diff={})

    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]

    async def _cmp(i: int, j: int) -> tuple[int, int, bool]:
        return i, j, await compare(sources[i], sources[j], **kwargs)

    results = await asyncio.gather(*[_cmp(i, j) for i, j in pairs])

    diff: dict[tuple[str, str], bool] = {}
    for i, j, eq in results:
        diff[(names[i], names[j])] = eq

    all_equal = all(eq for _, _, eq in results)

    # Union-find for grouping
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j, eq in results:
        if eq:
            pi, pj = find(i), find(j)
            if pi != pj:
                parent[pi] = pj

    group_map: dict[int, set[str]] = {}
    for i in range(n):
        root = find(i)
        group_map.setdefault(root, set()).add(names[i])

    return CompareResult(all_equal=all_equal, groups=list(group_map.values()), diff=diff)


async def compare_dir_urls(
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
    proxy: str | None = None,
) -> DirResult:
    """Compare directory files against URL mapping (async).

    Directory walk, HTTP fetches, and comparisons all run in C threads.
    Completion notification via eventfd integrated with asyncio.
    """
    validate_path(dir_path, "dir_path")
    validate_chunk_size(chunk_size)
    validate_timeout(timeout)

    cfg = get_config()

    h = headers if headers is not None else (cfg.headers or None)
    p = proxy if proxy is not None else cfg.proxy

    fd, task = async_compare_dir_urls_start(
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

    raw = await _await_task(fd, lambda: async_compare_dir_urls_result(task))
    return build_dir_result(raw)


__all__ = [
    "compare",
    "compare_dir",
    "compare_archive",
    "compare_all",
    "compare_many",
    "compare_dir_urls",
]
