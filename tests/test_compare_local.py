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
