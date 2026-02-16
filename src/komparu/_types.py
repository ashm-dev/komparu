"""komparu result types and enumerations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiffReason(str, Enum):
    """Reason why two entries differ."""

    CONTENT_MISMATCH = "content_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    MISSING = "missing"
    TYPE_MISMATCH = "type_mismatch"
    READ_ERROR = "read_error"


@dataclass(frozen=True, slots=True)
class Source:
    """Per-source HTTP configuration.

    :param url: File path or URL.
    :param headers: HTTP headers for this source.
    :param timeout: HTTP timeout in seconds.
    :param follow_redirects: Follow HTTP redirects.
    :param verify_ssl: Verify SSL certificates.
    :param proxy: Proxy URL (e.g. http://host:port, socks5://host:port).
    """

    url: str
    headers: dict[str, str] | None = None
    timeout: float | None = None
    follow_redirects: bool | None = None
    verify_ssl: bool | None = None
    proxy: str | None = None

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("Source.url cannot be empty")


@dataclass(frozen=True, slots=True)
class DirResult:
    """Result of directory or archive comparison.

    :param equal: True if all files are identical.
    :param diff: Files with different content, keyed by relative path.
    :param only_left: Files only in the first source.
    :param only_right: Files only in the second source.
    """

    equal: bool
    diff: dict[str, DiffReason]
    only_left: set[str]
    only_right: set[str]


@dataclass(frozen=True, slots=True)
class CompareResult:
    """Result of multi-source comparison.

    :param all_equal: True if all sources are identical.
    :param groups: Groups of identical sources.
    :param diff: Pairwise comparison results.
    """

    all_equal: bool
    groups: list[set[str]]
    diff: dict[tuple[str, str], bool]


# ---- Errors ----

class KomparuError(Exception):
    """Base exception for all komparu errors."""


class SourceNotFoundError(KomparuError):
    """File or URL not found."""


class SourceReadError(KomparuError):
    """I/O or HTTP read error."""


class ArchiveError(KomparuError):
    """Cannot read or parse archive."""


class ArchiveBombError(ArchiveError):
    """Archive exceeds safety limits (decompression bomb)."""


class ConfigError(KomparuError):
    """Invalid configuration."""


class ComparisonTimeoutError(KomparuError):
    """Comparison exceeded wall-clock timeout."""
