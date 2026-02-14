"""Shared fixtures for komparu tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def make_file(tmp_path: Path):
    """Factory fixture: create a file with given content."""

    def _make(name: str, content: bytes) -> Path:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    return _make


@pytest.fixture
def make_files(make_file):
    """Factory fixture: create multiple files, return dict of paths."""

    def _make(files: dict[str, bytes]) -> dict[str, Path]:
        return {name: make_file(name, content) for name, content in files.items()}

    return _make
