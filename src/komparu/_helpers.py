"""Internal helpers for komparu API."""

from __future__ import annotations

from komparu._types import DiffReason, DirResult, Source


def resolve_headers(source: str | Source, global_headers: dict[str, str] | None) -> dict[str, str] | None:
    """Merge per-source headers with global headers. Source wins."""
    if isinstance(source, Source) and source.headers:
        if global_headers:
            merged = dict(global_headers)
            merged.update(source.headers)
            return merged
        return source.headers
    return global_headers


def build_dir_result(raw: dict) -> DirResult:
    """Convert C extension dict to DirResult."""
    diff = {k: DiffReason(v) for k, v in raw["diff"].items()}
    return DirResult(
        equal=raw["equal"],
        diff=diff,
        only_left=raw["only_left"],
        only_right=raw["only_right"],
    )
