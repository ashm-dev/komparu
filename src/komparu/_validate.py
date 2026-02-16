"""Parameter validation for komparu API."""

from __future__ import annotations

from komparu._types import Source


def validate_path(val: str | Source, name: str) -> None:
    path = val.url if isinstance(val, Source) else val
    if not path:
        raise ValueError(f"{name} cannot be empty")


def validate_chunk_size(chunk_size: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_size > 1024 * 1024 * 1024:
        raise ValueError("chunk_size must be <= 1GB")


def validate_timeout(timeout: float | None) -> None:
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")


def validate_max_workers(max_workers: int) -> None:
    if max_workers < 0:
        raise ValueError("max_workers must be non-negative")
    if max_workers > 256:
        raise ValueError("max_workers must be <= 256")
