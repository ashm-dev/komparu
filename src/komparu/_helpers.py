"""Internal helpers for komparu API."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

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


def _path_matches_ignore(path: str, patterns: list[str]) -> bool:
    """Check if any component of *path* matches any ignore pattern."""
    parts = PurePosixPath(path).parts
    return any(fnmatch(part, pat) for part in parts for pat in patterns)


def filter_dir_result(result: DirResult, ignore: list[str]) -> DirResult:
    """Remove entries whose path matches any ignore glob pattern.

    Each component of the relative path is tested against every pattern
    using :func:`fnmatch.fnmatch`.  If any component matches, the entry
    is excluded.  The ``equal`` flag is recomputed after filtering.
    """
    if not ignore:
        return result

    diff = {k: v for k, v in result.diff.items()
            if not _path_matches_ignore(k, ignore)}
    only_left = {p for p in result.only_left
                 if not _path_matches_ignore(p, ignore)}
    only_right = {p for p in result.only_right
                  if not _path_matches_ignore(p, ignore)}

    # If the original result was equal and nothing was filtered away,
    # keep it.  Otherwise recompute: equal iff no remaining diffs.
    equal = result.equal if result.equal else (
        not diff and not only_left and not only_right
    )

    errors = {p for p in result.errors
              if not _path_matches_ignore(p, ignore)}

    return DirResult(equal=equal, diff=diff,
                     only_left=only_left, only_right=only_right,
                     errors=errors)


def build_dir_result(raw: dict) -> DirResult:
    """Convert C extension dict to DirResult."""
    diff = {k: DiffReason(v) for k, v in raw["diff"].items()}
    return DirResult(
        equal=raw["equal"],
        diff=diff,
        only_left=raw["only_left"],
        only_right=raw["only_right"],
        errors=raw.get("errors", set()),
    )
