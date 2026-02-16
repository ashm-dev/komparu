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


@pytest.fixture
def make_tar_plain(tmp_path: Path):
    """Create an uncompressed tar archive from a dict of {name: content}."""

    def _make(name: str, files: dict[str, bytes]) -> Path:
        p = tmp_path / name
        with tarfile.open(str(p), "w:") as tf:
            for entry_name, data in files.items():
                info = tarfile.TarInfo(name=entry_name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return p

    return _make


@pytest.fixture
def make_tar_bz2(tmp_path: Path):
    """Create a tar.bz2 archive from a dict of {name: content}."""

    def _make(name: str, files: dict[str, bytes]) -> Path:
        p = tmp_path / name
        with tarfile.open(str(p), "w:bz2") as tf:
            for entry_name, data in files.items():
                info = tarfile.TarInfo(name=entry_name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return p

    return _make


@pytest.fixture
def make_tar_xz(tmp_path: Path):
    """Create a tar.xz archive from a dict of {name: content}."""

    def _make(name: str, files: dict[str, bytes]) -> Path:
        p = tmp_path / name
        with tarfile.open(str(p), "w:xz") as tf:
            for entry_name, data in files.items():
                info = tarfile.TarInfo(name=entry_name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return p

    return _make


class TestSameArchive:
    """Same archive compared with itself should short-circuit."""

    def test_same_path(self, make_tar):
        """Same archive path → instant equal via inode."""
        a = make_tar("a.tar.gz", {"file.txt": b"data"})
        result = komparu.compare_archive(str(a), str(a))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_symlink_to_archive(self, make_tar, tmp_path: Path):
        """Symlink to same archive → inode match → equal."""
        a = make_tar("a.tar.gz", {"file.txt": b"data"})
        link = tmp_path / "link.tar.gz"
        link.symlink_to(a)
        result = komparu.compare_archive(str(a), str(link))
        assert result.equal is True

    def test_hard_link_to_archive(self, make_tar, tmp_path: Path):
        """Hard link to same archive → inode match → equal."""
        a = make_tar("a.tar.gz", {"file.txt": b"data"})
        link = tmp_path / "hardlink.tar.gz"
        os.link(str(a), str(link))
        result = komparu.compare_archive(str(a), str(link))
        assert result.equal is True

    def test_same_path_hash_compare(self, make_tar):
        """Same path with hash_compare=True → inode fires before hashing."""
        a = make_tar("a.tar.gz", {"file.txt": b"data"})
        result = komparu.compare_archive(str(a), str(a), hash_compare=True)
        assert result.equal is True
        assert result.diff == {}


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


# ---- New tests: Archive formats ----


class TestArchiveFormats:
    """Test various archive formats beyond tar.gz and zip."""

    def test_tar_plain_identical(self, make_tar_plain):
        """Uncompressed .tar archives with identical content."""
        files = {"readme.txt": b"hello", "data.bin": b"\x00\x01\x02"}
        a = make_tar_plain("a.tar", files)
        b = make_tar_plain("b.tar", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_tar_plain_different(self, make_tar_plain):
        """Uncompressed .tar archives with different content."""
        a = make_tar_plain("a.tar", {"file.txt": b"alpha"})
        b = make_tar_plain("b.tar", {"file.txt": b"bravo"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.CONTENT_MISMATCH

    def test_tar_plain_only_left(self, make_tar_plain):
        """Uncompressed .tar: entry only in left archive."""
        a = make_tar_plain("a.tar", {"a.txt": b"a", "extra.txt": b"e"})
        b = make_tar_plain("b.tar", {"a.txt": b"a"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"extra.txt"}

    def test_tar_bz2_identical(self, make_tar_bz2):
        """tar.bz2 archives with identical content."""
        files = {"doc.txt": b"bzip2 content", "bin.dat": os.urandom(256)}
        a = make_tar_bz2("a.tar.bz2", files)
        b = make_tar_bz2("b.tar.bz2", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}

    def test_tar_bz2_different(self, make_tar_bz2):
        """tar.bz2 archives with different content."""
        a = make_tar_bz2("a.tar.bz2", {"file.txt": b"one"})
        b = make_tar_bz2("b.tar.bz2", {"file.txt": b"two"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff

    def test_tar_bz2_only_right(self, make_tar_bz2):
        """tar.bz2: entry only in right archive."""
        a = make_tar_bz2("a.tar.bz2", {"common.txt": b"shared"})
        b = make_tar_bz2("b.tar.bz2", {"common.txt": b"shared", "new.txt": b"new"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert result.only_right == {"new.txt"}

    @pytest.mark.skipif(
        not hasattr(tarfile, "ENCODING"),
        reason="tarfile xz support check",
    )
    def test_tar_xz_identical(self, make_tar_xz):
        """tar.xz archives with identical content (requires lzma)."""
        pytest.importorskip("lzma")
        files = {"data.txt": b"xz compressed", "nested/file.bin": os.urandom(128)}
        a = make_tar_xz("a.tar.xz", files)
        b = make_tar_xz("b.tar.xz", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}

    @pytest.mark.skipif(
        not hasattr(tarfile, "ENCODING"),
        reason="tarfile xz support check",
    )
    def test_tar_xz_different(self, make_tar_xz):
        """tar.xz archives with different content."""
        pytest.importorskip("lzma")
        a = make_tar_xz("a.tar.xz", {"file.txt": b"version X"})
        b = make_tar_xz("b.tar.xz", {"file.txt": b"version Y"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff

    def test_cross_format_tar_gz_vs_tar_bz2(self, make_tar, make_tar_bz2):
        """Cross-format comparison: tar.gz vs tar.bz2 with same content."""
        files = {
            "readme.txt": b"cross-format test",
            "sub/data.bin": os.urandom(200),
        }
        a = make_tar("a.tar.gz", files)
        b = make_tar_bz2("b.tar.bz2", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_cross_format_tar_gz_vs_tar_plain(self, make_tar, make_tar_plain):
        """Cross-format comparison: tar.gz vs uncompressed tar."""
        files = {"file.txt": b"plain vs gzip"}
        a = make_tar("a.tar.gz", files)
        b = make_tar_plain("b.tar", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True

    def test_cross_format_tar_bz2_vs_zip(self, make_tar_bz2, make_zip):
        """Cross-format comparison: tar.bz2 vs zip with same content."""
        files = {"doc.txt": b"bz2 vs zip", "img.bin": os.urandom(100)}
        a = make_tar_bz2("a.tar.bz2", files)
        b = make_zip("b.zip", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True

    def test_cross_format_different_content(self, make_tar, make_tar_bz2):
        """Cross-format with different content should report differences."""
        a = make_tar("a.tar.gz", {"file.txt": b"gz version"})
        b = make_tar_bz2("b.tar.bz2", {"file.txt": b"bz2 version"})
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff

    def test_tar_plain_nested_dirs(self, make_tar_plain):
        """Uncompressed tar with deeply nested directory structure."""
        files = {
            "top.txt": b"top",
            "a/b/c/deep.txt": b"deeply nested",
            "a/sibling.txt": b"sibling",
        }
        a = make_tar_plain("a.tar", files)
        b = make_tar_plain("b.tar", files)
        result = komparu.compare_archive(str(a), str(b))
        assert result.equal is True


# ---- New tests: Archive bomb limits ----


class TestArchiveBombLimits:
    """Test max_decompressed_size, max_compression_ratio, max_entry_name_length."""

    def test_max_decompressed_size_exceeded(self, tmp_path: Path):
        """Archive with total decompressed size exceeding limit raises error."""
        a_path = tmp_path / "big.tar.gz"
        # Create archive with a single 10KB entry
        big_data = b"A" * 10240
        with tarfile.open(str(a_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="big.txt")
            info.size = len(big_data)
            tf.addfile(info, io.BytesIO(big_data))

        b_path = tmp_path / "small.tar.gz"
        with tarfile.open(str(b_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="small.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))

        # Set max_decompressed_size to 1KB — 10KB entry should trigger bomb
        with pytest.raises(IOError, match="bomb"):
            komparu.compare_archive(
                str(a_path), str(b_path),
                max_decompressed_size=1024,
            )

    def test_max_decompressed_size_within_limit(self, make_tar):
        """Archive within decompressed size limit should work normally."""
        files = {"file.txt": b"small content"}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(
            str(a), str(b),
            max_decompressed_size=1024 * 1024,
        )
        assert result.equal is True

    def test_max_compression_ratio_exceeded(self, tmp_path: Path):
        """Highly compressible content exceeding ratio limit raises error."""
        # Create archive with zeros (extremely compressible)
        zeros = b"\x00" * 102400  # 100KB of zeros
        a_path = tmp_path / "zeros.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="zeros.bin")
            info.size = len(zeros)
            tf.addfile(info, io.BytesIO(zeros))

        b_path = tmp_path / "b.tar.gz"
        with tarfile.open(str(b_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="file.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))

        # Set ratio to 2 — zeros compress much better than 2:1
        with pytest.raises(IOError, match="bomb"):
            komparu.compare_archive(
                str(a_path), str(b_path),
                max_compression_ratio=2,
            )

    def test_max_compression_ratio_within_limit(self, make_tar):
        """Content within compression ratio limit should work normally."""
        # Random data doesn't compress well
        files = {"random.bin": os.urandom(1000)}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(
            str(a), str(b),
            max_compression_ratio=200,
        )
        # Random data is identical so equal
        assert result.equal is True

    def test_max_entry_name_length_exceeded(self, tmp_path: Path):
        """Entry with name exceeding max length raises error."""
        long_name = "d/" * 2048 + "file.txt"  # Very long path
        a_path = tmp_path / "longname.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            info = tarfile.TarInfo(name=long_name)
            info.size = 4
            tf.addfile(info, io.BytesIO(b"data"))

        b_path = tmp_path / "b.tar.gz"
        with tarfile.open(str(b_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="file.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"data"))

        with pytest.raises(IOError, match="bomb"):
            komparu.compare_archive(
                str(a_path), str(b_path),
                max_entry_name_length=100,
            )

    def test_max_entry_name_length_within_limit(self, make_tar):
        """Entry with name within max length should work normally."""
        files = {"sub/dir/file.txt": b"data"}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(
            str(a), str(b),
            max_entry_name_length=4096,
        )
        assert result.equal is True

    def test_multiple_bomb_limits_combined(self, tmp_path: Path):
        """Strict limits on all bomb parameters simultaneously."""
        files_data = b"x" * 100
        a_path = tmp_path / "a.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            for i in range(5):
                info = tarfile.TarInfo(name=f"file_{i}.txt")
                info.size = len(files_data)
                tf.addfile(info, io.BytesIO(files_data))

        b_path = tmp_path / "b.tar.gz"
        with tarfile.open(str(b_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="file.txt")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))

        # max_archive_entries=3 should fire first (5 entries > 3)
        with pytest.raises(IOError, match="bomb"):
            komparu.compare_archive(
                str(a_path), str(b_path),
                max_archive_entries=3,
                max_decompressed_size=10000,
                max_entry_name_length=100,
            )


# ---- New tests: hash_compare mode ----


class TestHashCompare:
    """Test hash_compare=True mode for archive comparison."""

    def test_hash_identical_tar(self, make_tar):
        """hash_compare=True with identical tar.gz archives → equal."""
        files = {"file.txt": b"hello", "data.bin": b"binary data"}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_hash_identical_zip(self, make_zip):
        """hash_compare=True with identical zip archives → equal."""
        files = {"doc.txt": b"zip content", "img.bin": os.urandom(500)}
        a = make_zip("a.zip", files)
        b = make_zip("b.zip", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True

    def test_hash_different_content(self, make_tar):
        """hash_compare=True with different content → not equal."""
        a = make_tar("a.tar.gz", {"file.txt": b"version A"})
        b = make_tar("b.tar.gz", {"file.txt": b"version B"})
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is False
        assert "file.txt" in result.diff

    def test_hash_different_size(self, make_tar):
        """hash_compare=True with different sizes → not equal."""
        a = make_tar("a.tar.gz", {"file.txt": b"short"})
        b = make_tar("b.tar.gz", {"file.txt": b"much longer content here"})
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is False
        assert "file.txt" in result.diff

    def test_hash_only_left(self, make_tar):
        """hash_compare=True with entry only in left archive."""
        a = make_tar("a.tar.gz", {"common.txt": b"data", "extra.txt": b"only a"})
        b = make_tar("b.tar.gz", {"common.txt": b"data"})
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is False
        assert result.only_left == {"extra.txt"}
        assert result.only_right == set()

    def test_hash_only_right(self, make_tar):
        """hash_compare=True with entry only in right archive."""
        a = make_tar("a.tar.gz", {"common.txt": b"data"})
        b = make_tar("b.tar.gz", {"common.txt": b"data", "extra.txt": b"only b"})
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is False
        assert result.only_left == set()
        assert result.only_right == {"extra.txt"}

    def test_hash_both_only_left_and_right(self, make_tar):
        """hash_compare=True with entries unique to each side."""
        a = make_tar("a.tar.gz", {
            "common.txt": b"shared",
            "left_only.txt": b"left",
        })
        b = make_tar("b.tar.gz", {
            "common.txt": b"shared",
            "right_only.txt": b"right",
        })
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is False
        assert result.only_left == {"left_only.txt"}
        assert result.only_right == {"right_only.txt"}

    def test_hash_mixed_tar_zip(self, make_tar, make_zip):
        """hash_compare=True cross-format: tar.gz vs zip with same content."""
        files = {"file.txt": b"cross format hash"}
        a = make_tar("a.tar.gz", files)
        b = make_zip("b.zip", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True

    def test_hash_nested_paths(self, make_tar):
        """hash_compare=True with nested directory entries."""
        files = {
            "top.txt": b"top",
            "sub/nested.txt": b"nested",
            "sub/deep/file.bin": b"deep data",
        }
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True

    def test_hash_empty_files(self, make_tar):
        """hash_compare=True with empty file entries."""
        files = {"empty.txt": b""}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True

    def test_hash_large_content(self, make_tar):
        """hash_compare=True with larger content to exercise streaming hash."""
        content = os.urandom(50000)
        files = {"big.bin": content, "small.txt": b"tiny"}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True

    def test_hash_cross_format_tar_bz2(self, make_tar, make_tar_bz2):
        """hash_compare=True cross-format: tar.gz vs tar.bz2."""
        files = {"data.txt": b"cross format bz2 hash test"}
        a = make_tar("a.tar.gz", files)
        b = make_tar_bz2("b.tar.bz2", files)
        result = komparu.compare_archive(str(a), str(b), hash_compare=True)
        assert result.equal is True
