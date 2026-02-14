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

    # Merge config with call params (call params win)
    cs = chunk_size if chunk_size is not None else cfg.chunk_size
    sp = size_precheck if size_precheck is not None else cfg.size_precheck
    qc = quick_check if quick_check is not None else cfg.quick_check

    # Phase 1: local files only — delegate to C extension
    return _compare_c(path_a, path_b, chunk_size=cs,
                      size_precheck=sp, quick_check=qc)


__all__ = [
    "__version__",
    "compare",
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
