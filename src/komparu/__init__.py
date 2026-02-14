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


def _resolve_opt(source_val, call_val, cfg_val):
    """Three-tier priority: Source > call param > global config."""
    if source_val is not None:
        return source_val
    if call_val is not None:
        return call_val
    return cfg_val


def compare(
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
    retries: int | None = None,
    retry_backoff: float | None = None,
    min_size: int | None = None,
    integrity_check: bool = True,
) -> bool:
    """Compare two sources byte-by-byte.

    :param source_a: File path, URL, or Source object.
    :param source_b: File path, URL, or Source object.
    :param chunk_size: Chunk size in bytes.
    :param size_precheck: Compare sizes before content.
    :param quick_check: Sample first/last/middle before full scan.
    :param headers: Global HTTP headers for URL sources.
    :param timeout: HTTP timeout in seconds.
    :param follow_redirects: Follow HTTP redirects.
    :param verify_ssl: Verify SSL certificates.
    :param retries: HTTP retry count.
    :param retry_backoff: Retry backoff base (seconds).
    :param min_size: Reject source if smaller than this.
    :param integrity_check: Check file mtime before/after comparison.
    :returns: True if sources are byte-identical.
    """
    cfg = get_config()

    # Resolve source paths
    path_a = source_a.url if isinstance(source_a, Source) else source_a
    path_b = source_b.url if isinstance(source_b, Source) else source_b

    # Merge options: Source() > call param > config
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    sp = size_precheck if size_precheck is not None else cfg.size_precheck
    qc = quick_check if quick_check is not None else cfg.quick_check

    # HTTP options — use the more specific headers per-source
    # For the C layer, we pass the global headers; per-source resolution
    # happens when we support Source objects fully in the C layer.
    # For now: merge the "most applicable" headers for each source.
    h = headers if headers is not None else (cfg.headers or None)
    t = timeout if timeout is not None else cfg.timeout
    fr = follow_redirects if follow_redirects is not None else cfg.follow_redirects
    vs = verify_ssl if verify_ssl is not None else cfg.verify_ssl

    ap = cfg.allow_private_redirects

    return _compare_c(
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
    chunk_size: int | None = None,
    size_precheck: bool | None = None,
    quick_check: bool | None = None,
    follow_symlinks: bool = True,
) -> DirResult:
    """Compare two directories recursively.

    :param dir_a: Path to first directory.
    :param dir_b: Path to second directory.
    :param chunk_size: Chunk size for file comparison.
    :param size_precheck: Compare file sizes before content.
    :param quick_check: Sample first/last/middle before full scan.
    :param follow_symlinks: Follow symbolic links during traversal.
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    cfg = get_config()
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    sp = size_precheck if size_precheck is not None else cfg.size_precheck
    qc = quick_check if quick_check is not None else cfg.quick_check

    raw = _compare_dir_c(
        dir_a, dir_b,
        chunk_size=cs,
        size_precheck=sp,
        quick_check=qc,
        follow_symlinks=follow_symlinks,
    )
    return _build_dir_result(raw)


def compare_archive(
    path_a: str,
    path_b: str,
    *,
    chunk_size: int | None = None,
    max_decompressed_size: int | None = None,
    max_compression_ratio: int | None = None,
    max_archive_entries: int | None = None,
    max_entry_name_length: int | None = None,
) -> DirResult:
    """Compare two archive files entry-by-entry.

    :param path_a: Path to first archive file.
    :param path_b: Path to second archive file.
    :param chunk_size: Chunk size (unused, archives compared in-memory).
    :param max_decompressed_size: Max total decompressed bytes (bomb limit).
    :param max_compression_ratio: Max compression ratio (bomb limit).
    :param max_archive_entries: Max number of archive entries (bomb limit).
    :param max_entry_name_length: Max entry path length (bomb limit).
    :returns: DirResult with equal, diff, only_left, only_right.
    """
    cfg = get_config()
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    mds = max_decompressed_size if max_decompressed_size is not None else (cfg.max_decompressed_size or -1)
    mcr = max_compression_ratio if max_compression_ratio is not None else (cfg.max_compression_ratio or -1)
    me = max_archive_entries if max_archive_entries is not None else (cfg.max_archive_entries or -1)
    menl = max_entry_name_length if max_entry_name_length is not None else (cfg.max_entry_name_length or -1)

    raw = _compare_archive_c(
        path_a, path_b,
        chunk_size=cs,
        max_decompressed_size=mds,
        max_compression_ratio=mcr,
        max_entries=me,
        max_entry_name_length=menl,
    )
    return _build_dir_result(raw)


__all__ = [
    "__version__",
    "compare",
    "compare_dir",
    "compare_archive",
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
