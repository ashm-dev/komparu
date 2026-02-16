"""komparu — ultra-fast file comparison library."""

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
from komparu._api import (
    compare,
    compare_dir,
    compare_archive,
    compare_all,
    compare_many,
    compare_dir_urls,
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
