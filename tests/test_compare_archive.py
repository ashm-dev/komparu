"""Tests for archive comparison (Phase 3)."""

from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

import komparu
from komparu import DiffReason


@pytest.fixture
def make_tar(tmp_path: Path):
    """Create a tar.gz archive from a dict of {name: content}."""

    def _make(name: str, files: dict[str, bytes]) -> Path:
        p = tmp_path / name
        with tarfile.open(str(p), "w:gz") as tf:
            for entry_name, data in files.items():
                info = tarfile.TarInfo(name=entry_name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return p

    return _make


@pytest.fixture
def make_zip(tmp_path: Path):
    """Create a zip archive from a dict of {name: content}."""

    def _make(name: str, files: dict[str, bytes]) -> Path:
        p = tmp_path / name
        with zipfile.ZipFile(str(p), "w", zipfile.ZIP_DEFLATED) as zf:
            for entry_name, data in files.items():
                zf.writestr(entry_name, data)
        return p

    return _make


class TestIdenticalArchives:
    """Two identical archives should return equal=True."""

    def test_tar_identical(self, make_tar):
        files = {"file.txt": b"hello", "data.bin": b"binary"}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_zip_identical(self, make_zip):
        files = {"doc.txt": b"content", "img.bin": os.urandom(500)}
        a = make_zip("a.zip", files)
        b = make_zip("b.zip", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True

    def test_nested_paths(self, make_tar):
        files = {
            "root.txt": b"root",
            "sub/nested.txt": b"nested",
            "sub/deep/file.bin": b"deep",
        }
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True

    def test_empty_files(self, make_tar):
        files = {"empty.txt": b""}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True


class TestDifferentArchives:
    """Archives with differences."""

    def test_content_mismatch(self, make_tar):
        a = make_tar("a.tar.gz", {"file.txt": b"version A"})
        b = make_tar("b.tar.gz", {"file.txt": b"version B"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.CONTENT_MISMATCH

    def test_size_mismatch(self, make_tar):
        a = make_tar("a.tar.gz", {"file.txt": b"short"})
        b = make_tar("b.tar.gz", {"file.txt": b"much longer content here"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.SIZE_MISMATCH

    def test_only_left(self, make_tar):
        a = make_tar("a.tar.gz", {"common.txt": b"data", "extra.txt": b"only a"})
        b = make_tar("b.tar.gz", {"common.txt": b"data"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"extra.txt"}

    def test_only_right(self, make_tar):
        a = make_tar("a.tar.gz", {"common.txt": b"data"})
        b = make_tar("b.tar.gz", {"common.txt": b"data", "extra.txt": b"only b"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert result.only_right == {"extra.txt"}

    def test_mixed_tar_zip(self, make_tar, make_zip):
        """Compare tar vs zip with same content."""
        files = {"file.txt": b"same content"}
        a = make_tar("a.tar.gz", files)
        b = make_zip("b.zip", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True


class TestArchiveSafety:
    """Path sanitization and bomb protection."""

    def test_path_traversal_skipped(self, make_tar, tmp_path: Path):
        """Entries with .. in path are silently skipped."""
        a_path = tmp_path / "a.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            # Normal entry
            info = tarfile.TarInfo(name="safe.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"safe"))
            # Dangerous entry with ..
            info = tarfile.TarInfo(name="../etc/passwd")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))

        b = make_tar("b.tar.gz", {"safe.txt": b"safe"})
        result = komparu.compare_archive(str(a_path), str(b))
        # The ../etc/passwd entry is skipped, so both have only safe.txt
        assert result.equal is True

    def test_absolute_path_skipped(self, make_tar, tmp_path: Path):
        """Entries with absolute paths are silently skipped."""
        a_path = tmp_path / "a.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="good.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"good"))
            info = tarfile.TarInfo(name="/etc/shadow")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))

        b = make_tar("b.tar.gz", {"good.txt": b"good"})
        result = komparu.compare_archive(str(a_path), str(b))
        assert result.equal is True

    def test_leading_dot_slash_normalized(self, make_tar, tmp_path: Path):
        """./prefix is stripped during normalization."""
        a_path = tmp_path / "a.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="./file.txt")
            info.size = 5
            tf.addfile(info, io.BytesIO(b"hello"))

        b = make_tar("b.tar.gz", {"file.txt": b"hello"})
        result = komparu.compare_archive(str(a_path), str(b))
        assert result.equal is True

    def test_max_entries_bomb(self, tmp_path: Path):
        """Archive with too many entries raises error."""
        a_path = tmp_path / "bomb.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            for i in range(20):
                info = tarfile.TarInfo(name=f"file_{i}.txt")
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))

        b_path = tmp_path / "b.tar.gz"
        with tarfile.open(str(b_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="file.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))

        with pytest.raises(IOError, match="bomb"):
            komparu.compare_archive(
                str(a_path), str(b_path),
                max_archive_entries=10,
            )


class TestArchiveErrors:
    """Error handling."""

    def test_nonexistent_archive(self, make_tar, tmp_path: Path):
        a = make_tar("a.tar.gz", {"file.txt": b"data"})
        with pytest.raises(IOError):
            komparu.compare_archive(str(a), str(tmp_path / "nope.tar.gz"))

    def test_invalid_archive(self, tmp_path: Path):
        """Non-archive file should raise error."""
        a = tmp_path / "not_archive.txt"
        a.write_bytes(b"this is not an archive")
        b = tmp_path / "also_not.txt"
        b.write_bytes(b"this is not an archive")
        with pytest.raises(IOError):
            komparu.compare_archive(str(a), str(b))
