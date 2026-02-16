"""Tests for local file comparison (Phase 1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import komparu


class TestCompareIdentical:
    """Two identical files should return True."""

    def test_identical_small(self, make_file):
        content = b"hello world"
        a = make_file("a.txt", content)
        b = make_file("b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_identical_empty(self, make_file):
        a = make_file("a.txt", b"")
        b = make_file("b.txt", b"")
        assert komparu.compare(str(a), str(b)) is True

    def test_identical_single_byte(self, make_file):
        a = make_file("a.bin", b"\x00")
        b = make_file("b.bin", b"\x00")
        assert komparu.compare(str(a), str(b)) is True

    def test_identical_exact_chunk(self, make_file):
        """File size == chunk_size."""
        chunk = 1024
        content = os.urandom(chunk)
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        assert komparu.compare(str(a), str(b), chunk_size=chunk) is True

    def test_identical_multi_chunk(self, make_file):
        """File spans multiple chunks."""
        chunk = 1024
        content = os.urandom(chunk * 5 + 37)  # Not a multiple of chunk
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        assert komparu.compare(str(a), str(b), chunk_size=chunk) is True

    def test_identical_large(self, make_file):
        """1 MB file."""
        content = os.urandom(1024 * 1024)
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_same_file(self, make_file):
        """Comparing a file with itself."""
        a = make_file("a.txt", b"data")
        assert komparu.compare(str(a), str(a)) is True

    def test_hard_link(self, make_file, tmp_dir):
        """Hard link to same inode should return True instantly."""
        a = make_file("a.txt", b"hard_link_data")
        link = tmp_dir / "hardlink.txt"
        os.link(str(a), str(link))
        assert komparu.compare(str(a), str(link)) is True


class TestCompareDifferent:
    """Two different files should return False."""

    def test_different_content(self, make_file):
        a = make_file("a.txt", b"hello")
        b = make_file("b.txt", b"world")
        assert komparu.compare(str(a), str(b)) is False

    def test_different_size(self, make_file):
        a = make_file("a.txt", b"short")
        b = make_file("b.txt", b"longer text")
        assert komparu.compare(str(a), str(b)) is False

    def test_different_last_byte(self, make_file):
        """Files differ only in the very last byte."""
        base = os.urandom(10000)
        a = make_file("a.bin", base + b"\x00")
        b = make_file("b.bin", base + b"\x01")
        assert komparu.compare(str(a), str(b)) is False

    def test_different_first_byte(self, make_file):
        base = os.urandom(10000)
        a = make_file("a.bin", b"\x00" + base)
        b = make_file("b.bin", b"\x01" + base)
        assert komparu.compare(str(a), str(b)) is False

    def test_different_middle_byte(self, make_file):
        size = 10000
        mid = size // 2
        content = os.urandom(size)
        alt = bytearray(content)
        alt[mid] = (alt[mid] + 1) % 256
        a = make_file("a.bin", content)
        b = make_file("b.bin", bytes(alt))
        assert komparu.compare(str(a), str(b)) is False

    def test_one_empty_one_not(self, make_file):
        a = make_file("a.txt", b"")
        b = make_file("b.txt", b"data")
        assert komparu.compare(str(a), str(b)) is False

    def test_almost_equal_large(self, make_file):
        """1 MB files differing in last byte."""
        base = os.urandom(1024 * 1024 - 1)
        a = make_file("a.bin", base + b"\xAA")
        b = make_file("b.bin", base + b"\xBB")
        assert komparu.compare(str(a), str(b)) is False


class TestCompareEdgeCases:
    """Edge cases and error handling."""

    def test_file_not_found(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            komparu.compare(str(tmp_dir / "nonexistent"), str(tmp_dir / "also_missing"))

    def test_source_a_not_found(self, make_file, tmp_dir):
        b = make_file("b.txt", b"data")
        with pytest.raises(FileNotFoundError):
            komparu.compare(str(tmp_dir / "nonexistent"), str(b))

    def test_source_b_not_found(self, make_file, tmp_dir):
        a = make_file("a.txt", b"data")
        with pytest.raises(FileNotFoundError):
            komparu.compare(str(a), str(tmp_dir / "nonexistent"))

    def test_invalid_chunk_size(self, make_file):
        a = make_file("a.txt", b"data")
        b = make_file("b.txt", b"data")
        with pytest.raises(ValueError):
            komparu.compare(str(a), str(b), chunk_size=0)
        with pytest.raises((ValueError, OverflowError)):
            komparu.compare(str(a), str(b), chunk_size=-1)

    def test_custom_chunk_size(self, make_file):
        content = os.urandom(500)
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        # Very small chunk
        assert komparu.compare(str(a), str(b), chunk_size=1) is True
        # Very large chunk
        assert komparu.compare(str(a), str(b), chunk_size=1024 * 1024) is True

    def test_binary_content(self, make_file):
        """All byte values 0-255."""
        content = bytes(range(256)) * 10
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_source_is_directory(self, tmp_dir):
        """Directories must be rejected, not compared as empty files."""
        d = tmp_dir / "subdir"
        d.mkdir()
        f = tmp_dir / "file.txt"
        f.write_bytes(b"data")
        with pytest.raises((IsADirectoryError, IOError, FileNotFoundError)):
            komparu.compare(str(d), str(f))

    def test_permission_denied(self, make_file):
        a = make_file("a.txt", b"data")
        b = make_file("b.txt", b"data")
        os.chmod(str(b), 0o000)
        try:
            with pytest.raises((PermissionError, IOError, FileNotFoundError)):
                komparu.compare(str(a), str(b))
        finally:
            os.chmod(str(b), 0o644)

    def test_symlink_to_file(self, make_file, tmp_dir):
        """Symlinks should be followed transparently."""
        a = make_file("a.txt", b"symlink_data")
        link = tmp_dir / "link.txt"
        link.symlink_to(a)
        assert komparu.compare(str(a), str(link)) is True

    def test_broken_symlink(self, tmp_dir):
        link = tmp_dir / "broken_link"
        link.symlink_to(tmp_dir / "nonexistent_target")
        f = tmp_dir / "file.txt"
        f.write_bytes(b"data")
        with pytest.raises(FileNotFoundError):
            komparu.compare(str(link), str(f))


class TestCompareOptions:
    """Test comparison options."""

    def test_size_precheck_disabled(self, make_file):
        """With size_precheck=False, still detects different content."""
        a = make_file("a.txt", b"short")
        b = make_file("b.txt", b"longer text")
        assert komparu.compare(str(a), str(b), size_precheck=False) is False

    def test_quick_check_disabled(self, make_file):
        """With quick_check=False, still works correctly."""
        content = os.urandom(10000)
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        assert komparu.compare(str(a), str(b), quick_check=False) is True

    def test_all_options_disabled(self, make_file):
        content = os.urandom(1000)
        a = make_file("a.bin", content)
        b = make_file("b.bin", content)
        assert komparu.compare(
            str(a), str(b),
            size_precheck=False,
            quick_check=False,
        ) is True


# ---- New tests: Unicode file paths ----


class TestUnicodeFilePaths:
    """File comparison with Unicode characters in file names."""

    def test_cyrillic_filename_identical(self, make_file):
        """Cyrillic filenames with identical content."""
        content = b"cyrillic file content"
        a = make_file("\u0444\u0430\u0439\u043b_a.txt", content)
        b = make_file("\u0444\u0430\u0439\u043b_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_cyrillic_filename_different(self, make_file):
        """Cyrillic filenames with different content."""
        a = make_file("\u0444\u0430\u0439\u043b_a.txt", b"alpha")
        b = make_file("\u0444\u0430\u0439\u043b_b.txt", b"bravo")
        assert komparu.compare(str(a), str(b)) is False

    def test_chinese_filename_identical(self, make_file):
        """Chinese filenames with identical content."""
        content = b"chinese file content"
        a = make_file("\u6587\u4ef6_a.txt", content)
        b = make_file("\u6587\u4ef6_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_chinese_filename_different(self, make_file):
        """Chinese filenames with different content."""
        a = make_file("\u6587\u4ef6_a.txt", b"one")
        b = make_file("\u6587\u4ef6_b.txt", b"two")
        assert komparu.compare(str(a), str(b)) is False

    def test_japanese_filename(self, make_file):
        """Japanese (katakana) filenames."""
        content = b"japanese content"
        a = make_file("\u30c6\u30b9\u30c8_a.dat", content)
        b = make_file("\u30c6\u30b9\u30c8_b.dat", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_emoji_filename(self, make_file):
        """Emoji in filenames."""
        content = b"emoji content"
        a = make_file("\U0001f4c4_a.txt", content)
        b = make_file("\U0001f4c4_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_accented_latin_filename(self, make_file):
        """Accented Latin filenames (French, German)."""
        content = b"accented content"
        a = make_file("r\u00e9sum\u00e9_a.txt", content)
        b = make_file("r\u00e9sum\u00e9_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_unicode_in_subdirectory(self, make_file):
        """Unicode characters in parent directory name."""
        content = b"nested unicode"
        a = make_file("\u043f\u0430\u043f\u043a\u0430/a.txt", content)
        b = make_file("\u043f\u0430\u043f\u043a\u0430/b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_same_unicode_file(self, make_file):
        """Comparing a Unicode-named file with itself."""
        a = make_file("\u0444\u0430\u0439\u043b.txt", b"self compare")
        assert komparu.compare(str(a), str(a)) is True


# ---- New tests: Special character file paths ----


class TestSpecialCharFilePaths:
    """File comparison with special characters in file names."""

    def test_spaces_identical(self, make_file):
        """Files with spaces, identical content."""
        content = b"space content"
        a = make_file("my file a.txt", content)
        b = make_file("my file b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_spaces_different(self, make_file):
        """Files with spaces, different content."""
        a = make_file("my file a.txt", b"version 1")
        b = make_file("my file b.txt", b"version 2")
        assert komparu.compare(str(a), str(b)) is False

    def test_parentheses(self, make_file):
        """Files with parentheses in names."""
        content = b"paren content"
        a = make_file("file (1).txt", content)
        b = make_file("file (2).txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_brackets(self, make_file):
        """Files with square brackets."""
        content = b"bracket content"
        a = make_file("data[a].json", content)
        b = make_file("data[b].json", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_single_quotes(self, make_file):
        """Files with single quotes in names."""
        content = b"quote content"
        a = make_file("it's_a.txt", content)
        b = make_file("it's_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_hash_sign(self, make_file):
        """Files with # in names."""
        content = b"hash content"
        a = make_file("issue#1_a.txt", content)
        b = make_file("issue#1_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_at_sign(self, make_file):
        """Files with @ in names."""
        content = b"at content"
        a = make_file("user@host_a.txt", content)
        b = make_file("user@host_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_exclamation(self, make_file):
        """Files with ! in names."""
        content = b"bang content"
        a = make_file("alert!_a.txt", content)
        b = make_file("alert!_b.txt", content)
        assert komparu.compare(str(a), str(b)) is True

    def test_special_chars_in_subdir(self, make_file):
        """Special characters in parent directory name."""
        content = b"subdir special"
        a = make_file("dir with spaces/a.txt", content)
        b = make_file("dir with spaces/b.txt", content)
        assert komparu.compare(str(a), str(b)) is True
