"""komparu global configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KomparuConfig:
    """Global configuration with safe defaults.

    All values can be overridden per-call.
    Set numeric limits to None to disable.
    """

    # I/O
    chunk_size: int = 65536
    max_workers: int = 0  # 0 = auto (min(cpu, 8))
    timeout: float = 30.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    size_precheck: bool = True
    quick_check: bool = True

    # HTTP
    headers: dict[str, str] = field(default_factory=dict)
    retries: int = 0
    retry_backoff: float = 1.0

    # Archive safety limits
    max_decompressed_size: int | None = 1 * 1024**3       # 1 GB
    max_compression_ratio: int | None = 200
    max_archive_entries: int | None = 100_000
    max_entry_name_length: int | None = 4096

    # General limits
    comparison_timeout: float | None = 300.0               # 5 min

    # SSRF protection
    allow_private_redirects: bool = False


# Global singleton
_config = KomparuConfig()


def configure(**kwargs) -> None:
    """Update global configuration.

    :param chunk_size: Chunk size in bytes (default 65536).
    :param max_workers: Thread pool workers (0 = auto).
    :param timeout: HTTP timeout in seconds.
    :param follow_redirects: Follow HTTP redirects.
    :param verify_ssl: Verify SSL certificates.
    :param size_precheck: Compare sizes before content.
    :param quick_check: Sample first/last/middle before full scan.
    :param headers: Global HTTP headers.
    :param retries: HTTP retry count (default 0).
    :param retry_backoff: Retry backoff base (seconds).
    :param max_decompressed_size: Max decompressed bytes per archive (None = no limit).
    :param max_compression_ratio: Max compression ratio (None = no limit).
    :param max_archive_entries: Max files per archive (None = no limit).
    :param max_entry_name_length: Max path length per entry (None = no limit).
    :param comparison_timeout: Wall-clock timeout per comparison (None = no limit).
    :param allow_private_redirects: Allow redirects to private networks.
    """
    global _config
    for key, value in kwargs.items():
        if not hasattr(_config, key):
            from komparu._types import ConfigError
            raise ConfigError(f"unknown config option: {key!r}")
        setattr(_config, key, value)


def get_config() -> KomparuConfig:
    """Get current global configuration."""
    return _config


def reset_config() -> None:
    """Reset configuration to defaults."""
    global _config
    _config = KomparuConfig()
