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
from komparu._types import CompareResult, DiffReason, DirResult, Source


def _source_path(source: str | Source) -> str:
    return source.url if isinstance(source, Source) else source


def _build_dir_result(raw: dict) -> DirResult:
    """Convert C extension dict to DirResult."""
    diff = {k: DiffReason(v) for k, v in raw["diff"].items()}
    return DirResult(
        equal=raw["equal"],
        diff=diff,
        only_left=raw["only_left"],
        only_right=raw["only_right"],
    )


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
    chunk_size: int | None = None,
    size_precheck: bool | None = None,
    quick_check: bool | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    follow_redirects: bool | None = None,
    verify_ssl: bool | None = None,
) -> bool:
    """Compare two sources byte-by-byte (async).

    All I/O runs in C threads. Event loop never blocks.

    :param source_a: File path, URL, or Source object.
    :param source_b: File path, URL, or Source object.
    :returns: True if sources are byte-identical.
    """
    cfg = get_config()

    path_a = _source_path(source_a)
    path_b = _source_path(source_b)

    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    sp = size_precheck if size_precheck is not None else cfg.size_precheck
    qc = quick_check if quick_check is not None else cfg.quick_check
    h = headers if headers is not None else (cfg.headers or None)
    t = timeout if timeout is not None else cfg.timeout
    fr = follow_redirects if follow_redirects is not None else cfg.follow_redirects
    vs = verify_ssl if verify_ssl is not None else cfg.verify_ssl
    ap = cfg.allow_private_redirects

    fd, task = async_compare_start(
        path_a, path_b,
        chunk_size=cs,
        size_precheck=sp,
        quick_check=qc,
        headers=h if h else None,
        timeout=t,
        follow_redirects=fr,
        verify_ssl=vs,
        allow_private=ap,
    )

    return await _await_task(fd, lambda: async_compare_result(task))


async def compare_dir(
    dir_a: str,
    dir_b: str,
    *,
    chunk_size: int | None = None,
    size_precheck: bool | None = None,
    quick_check: bool | None = None,
    follow_symlinks: bool = True,
    max_workers: int | None = None,
) -> DirResult:
    """Compare two directories recursively (async).

    Directory walk and file comparisons run in C threads.

    :param dir_a: Path to first directory.
    :param dir_b: Path to second directory.
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    cfg = get_config()
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    sp = size_precheck if size_precheck is not None else cfg.size_precheck
    qc = quick_check if quick_check is not None else cfg.quick_check
    mw = max_workers if max_workers is not None else cfg.max_workers

    fd, task = async_compare_dir_start(
        dir_a, dir_b,
        chunk_size=cs,
        size_precheck=sp,
        quick_check=qc,
        follow_symlinks=follow_symlinks,
        max_workers=mw,
    )

    raw = await _await_task(fd, lambda: async_compare_dir_result(task))
    return _build_dir_result(raw)


async def compare_archive(
    path_a: str,
    path_b: str,
    *,
    chunk_size: int | None = None,
    max_decompressed_size: int | None = None,
    max_compression_ratio: int | None = None,
    max_archive_entries: int | None = None,
    max_entry_name_length: int | None = None,
) -> DirResult:
    """Compare two archive files entry-by-entry (async).

    Archive I/O runs in a C thread via libarchive. Completion
    notification via eventfd integrated with asyncio.
    """
    cfg = get_config()
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    mds = max_decompressed_size if max_decompressed_size is not None else (cfg.max_decompressed_size or -1)
    mcr = max_compression_ratio if max_compression_ratio is not None else (cfg.max_compression_ratio or -1)
    me = max_archive_entries if max_archive_entries is not None else (cfg.max_archive_entries or -1)
    menl = max_entry_name_length if max_entry_name_length is not None else (cfg.max_entry_name_length or -1)

    fd, task = async_compare_archive_start(
        path_a, path_b,
        chunk_size=cs,
        max_decompressed_size=mds,
        max_compression_ratio=mcr,
        max_entries=me,
        max_entry_name_length=menl,
    )

    raw = await _await_task(fd, lambda: async_compare_archive_result(task))
    return _build_dir_result(raw)


async def compare_all(
    sources: list[str | Source],
    *,
    chunk_size: int | None = None,
    size_precheck: bool | None = None,
    quick_check: bool | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    follow_redirects: bool | None = None,
    verify_ssl: bool | None = None,
) -> bool:
    """Check if all sources are identical (async).

    Compares source[0] against all others concurrently.
    """
    if len(sources) < 2:
        return True

    kwargs: dict[str, Any] = {}
    if chunk_size is not None:
        kwargs["chunk_size"] = chunk_size
    if size_precheck is not None:
        kwargs["size_precheck"] = size_precheck
    if quick_check is not None:
        kwargs["quick_check"] = quick_check
    if headers is not None:
        kwargs["headers"] = headers
    if timeout is not None:
        kwargs["timeout"] = timeout
    if follow_redirects is not None:
        kwargs["follow_redirects"] = follow_redirects
    if verify_ssl is not None:
        kwargs["verify_ssl"] = verify_ssl

    ref = sources[0]
    coros = [compare(ref, s, **kwargs) for s in sources[1:]]
    results = await asyncio.gather(*coros)
    return all(results)


async def compare_many(
    sources: list[str | Source],
    *,
    chunk_size: int | None = None,
    size_precheck: bool | None = None,
    quick_check: bool | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    follow_redirects: bool | None = None,
    verify_ssl: bool | None = None,
) -> CompareResult:
    """Detailed pairwise comparison of multiple sources (async).

    All pairs compared concurrently via asyncio.gather().
    """
    kwargs: dict[str, Any] = {}
    if chunk_size is not None:
        kwargs["chunk_size"] = chunk_size
    if size_precheck is not None:
        kwargs["size_precheck"] = size_precheck
    if quick_check is not None:
        kwargs["quick_check"] = quick_check
    if headers is not None:
        kwargs["headers"] = headers
    if timeout is not None:
        kwargs["timeout"] = timeout
    if follow_redirects is not None:
        kwargs["follow_redirects"] = follow_redirects
    if verify_ssl is not None:
        kwargs["verify_ssl"] = verify_ssl

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
    chunk_size: int | None = None,
    size_precheck: bool | None = None,
    quick_check: bool | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    follow_redirects: bool | None = None,
    verify_ssl: bool | None = None,
) -> DirResult:
    """Compare directory files against URL mapping (async).

    Directory walk, HTTP fetches, and comparisons all run in C threads.
    Completion notification via eventfd integrated with asyncio.
    """
    cfg = get_config()
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    sp = size_precheck if size_precheck is not None else cfg.size_precheck
    qc = quick_check if quick_check is not None else cfg.quick_check
    h = headers if headers is not None else (cfg.headers or None)
    t = timeout if timeout is not None else cfg.timeout
    fr = follow_redirects if follow_redirects is not None else cfg.follow_redirects
    vs = verify_ssl if verify_ssl is not None else cfg.verify_ssl
    ap = cfg.allow_private_redirects

    fd, task = async_compare_dir_urls_start(
        dir_path, url_map,
        chunk_size=cs,
        size_precheck=sp,
        quick_check=qc,
        headers=h if h else None,
        timeout=t,
        follow_redirects=fr,
        verify_ssl=vs,
        allow_private=ap,
    )

    raw = await _await_task(fd, lambda: async_compare_dir_urls_result(task))
    return _build_dir_result(raw)


__all__ = [
    "compare",
    "compare_dir",
    "compare_archive",
    "compare_all",
    "compare_many",
    "compare_dir_urls",
]
