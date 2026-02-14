"""Tests for directory comparison (Phase 3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import komparu
from komparu import DiffReason


@pytest.fixture
def make_dir(tmp_path: Path):
    """Create a directory tree from a dict of {relative_path: content}."""

    def _make(name: str, files: dict[str, bytes]) -> Path:
        d = tmp_path / name
        for rel, content in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        return d

    return _make


class TestIdenticalDirs:
    """Two identical directories should return equal=True."""

    def test_single_file(self, make_dir):
        a = make_dir("a", {"file.txt": b"hello"})
        b = make_dir("b", {"file.txt": b"hello"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_multiple_files(self, make_dir):
        files = {
            "one.txt": b"first",
            "two.txt": b"second",
            "three.bin": os.urandom(1000),
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_nested_dirs(self, make_dir):
        files = {
            "top.txt": b"top level",
            "sub/nested.txt": b"nested content",
            "sub/deep/file.bin": b"deep file",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_empty_dirs(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_empty_files(self, make_dir):
        a = make_dir("a", {"empty.txt": b""})
        b = make_dir("b", {"empty.txt": b""})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True


class TestDifferentDirs:
    """Directories with differences."""

    def test_content_mismatch(self, make_dir):
        a = make_dir("a", {"file.txt": b"hello"})
        b = make_dir("b", {"file.txt": b"world"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.CONTENT_MISMATCH

    def test_size_mismatch(self, make_dir):
        a = make_dir("a", {"file.txt": b"short"})
        b = make_dir("b", {"file.txt": b"much longer content"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.SIZE_MISMATCH

    def test_only_left(self, make_dir):
        a = make_dir("a", {"common.txt": b"data", "extra.txt": b"only in a"})
        b = make_dir("b", {"common.txt": b"data"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"extra.txt"}
        assert result.only_right == set()

    def test_only_right(self, make_dir):
        a = make_dir("a", {"common.txt": b"data"})
        b = make_dir("b", {"common.txt": b"data", "extra.txt": b"only in b"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert result.only_left == set()
        assert result.only_right == {"extra.txt"}

    def test_nested_only_left(self, make_dir):
        a = make_dir("a", {"sub/file.txt": b"data", "sub/extra.txt": b"extra"})
        b = make_dir("b", {"sub/file.txt": b"data"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"sub/extra.txt"}

    def test_mixed_differences(self, make_dir):
        a = make_dir("a", {
            "same.txt": b"identical",
            "different.txt": b"version A",
            "only_a.txt": b"exclusive",
        })
        b = make_dir("b", {
            "same.txt": b"identical",
            "different.txt": b"version B",
            "only_b.txt": b"exclusive",
        })
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "different.txt" in result.diff
        assert result.only_left == {"only_a.txt"}
        assert result.only_right == {"only_b.txt"}


class TestDirErrors:
    """Error handling."""

    def test_nonexistent_dir(self, tmp_path: Path):
        a = tmp_path / "exists"
        a.mkdir()
        with pytest.raises(IOError):
            komparu.compare_dir(str(a), str(tmp_path / "nope"))

    def test_nonexistent_both(self, tmp_path: Path):
        with pytest.raises(IOError):
            komparu.compare_dir(
                str(tmp_path / "nope_a"),
                str(tmp_path / "nope_b"),
            )


class TestDirOptions:
    """Options affect comparison behavior."""

    def test_chunk_size(self, make_dir):
        content = os.urandom(10000)
        a = make_dir("a", {"big.bin": content})
        b = make_dir("b", {"big.bin": content})
        result = komparu.compare_dir(str(a), str(b), chunk_size=256)
        assert result.equal is True

    def test_no_quick_check(self, make_dir):
        content = os.urandom(200000)
        a = make_dir("a", {"big.bin": content})
        b = make_dir("b", {"big.bin": content})
        result = komparu.compare_dir(str(a), str(b), quick_check=False)
        assert result.equal is True
