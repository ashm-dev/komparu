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


class TestSameDir:
    """Same directory compared with itself should short-circuit."""

    def test_same_path(self, make_dir):
        """Same path string → instant equal via realpath."""
        a = make_dir("a", {"file.txt": b"data"})
        result = komparu.compare_dir(str(a), str(a))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    def test_symlink_to_dir(self, make_dir, tmp_path: Path):
        """Symlink to same dir → realpath resolves → equal."""
        a = make_dir("a", {"file.txt": b"data"})
        link = tmp_path / "link_dir"
        link.symlink_to(a)
        result = komparu.compare_dir(str(a), str(link))
        assert result.equal is True

    def test_trailing_slash(self, make_dir):
        """Trailing slash variants → realpath normalizes."""
        a = make_dir("a", {"file.txt": b"data"})
        result = komparu.compare_dir(str(a), str(a) + "/")
        assert result.equal is True

    def test_relative_path(self, make_dir):
        """Relative vs absolute → realpath resolves both."""
        a = make_dir("a", {"file.txt": b"data"})
        abs_path = str(a)
        # Use relative path through parent
        rel_path = os.path.join(str(a.parent), ".", a.name)
        result = komparu.compare_dir(abs_path, rel_path)
        assert result.equal is True


class TestCrossDirHardlinks:
    """Cross-directory hardlinks exercise per-file inode check in dir_cmp_task_exec."""

    def test_cross_dir_hardlink(self, make_dir, tmp_path: Path):
        """Files in two dirs are hardlinked → same inode → equal."""
        a = make_dir("a", {"file.txt": b"data", "other.txt": b"more"})
        b_dir = tmp_path / "b"
        b_dir.mkdir()
        os.link(str(a / "file.txt"), str(b_dir / "file.txt"))
        os.link(str(a / "other.txt"), str(b_dir / "other.txt"))
        result = komparu.compare_dir(str(a), str(b_dir))
        assert result.equal is True


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


# ---- New tests: Unicode paths ----


class TestUnicodePaths:
    """Directory comparison with Unicode file and directory names."""

    def test_cyrillic_filename_identical(self, make_dir):
        """Files with Cyrillic names compared as identical."""
        files = {"\u0444\u0430\u0439\u043b.txt": b"cyrillic content"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}

    def test_cyrillic_filename_different(self, make_dir):
        """Files with Cyrillic names with different content."""
        a = make_dir("a", {"\u0444\u0430\u0439\u043b.txt": b"version A"})
        b = make_dir("b", {"\u0444\u0430\u0439\u043b.txt": b"version B"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "\u0444\u0430\u0439\u043b.txt" in result.diff

    def test_chinese_filename_identical(self, make_dir):
        """Files with Chinese characters in names."""
        files = {"\u6587\u4ef6.txt": b"chinese content"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_chinese_filename_different(self, make_dir):
        """Files with Chinese names and different content."""
        a = make_dir("a", {"\u6587\u4ef6.txt": b"alpha"})
        b = make_dir("b", {"\u6587\u4ef6.txt": b"bravo"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "\u6587\u4ef6.txt" in result.diff

    def test_japanese_filename(self, make_dir):
        """Files with Japanese characters in names."""
        files = {"\u30c6\u30b9\u30c8.dat": b"japanese test"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_emoji_filename(self, make_dir):
        """Files with emoji characters in names."""
        files = {"\U0001f4c4document.txt": b"emoji file"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_unicode_nested_dir(self, make_dir):
        """Nested directories with Unicode names."""
        files = {
            "\u043f\u0430\u043f\u043a\u0430/\u0444\u0430\u0439\u043b.txt": b"nested cyrillic",
            "\u043f\u0430\u043f\u043a\u0430/\u0434\u0430\u043d\u043d\u044b\u0435.bin": b"\x00\x01\x02",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_unicode_only_left(self, make_dir):
        """Unicode-named file only in left directory."""
        a = make_dir("a", {
            "common.txt": b"shared",
            "\u0434\u043e\u043f.txt": b"extra",
        })
        b = make_dir("b", {"common.txt": b"shared"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"\u0434\u043e\u043f.txt"}

    def test_unicode_only_right(self, make_dir):
        """Unicode-named file only in right directory."""
        a = make_dir("a", {"common.txt": b"shared"})
        b = make_dir("b", {
            "common.txt": b"shared",
            "\u6587\u4ef6.txt": b"extra",
        })
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert result.only_right == {"\u6587\u4ef6.txt"}

    def test_mixed_ascii_unicode(self, make_dir):
        """Mix of ASCII and Unicode filenames."""
        files = {
            "readme.txt": b"ascii",
            "\u0444\u0430\u0439\u043b.txt": b"cyrillic",
            "\u6587\u4ef6.dat": b"chinese",
            "sub/normal.txt": b"normal",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_accented_latin_filename(self, make_dir):
        """Files with accented Latin characters (e.g., French, German)."""
        files = {
            "r\u00e9sum\u00e9.txt": b"french",
            "\u00fcbersicht.txt": b"german",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True


# ---- New tests: Special character paths ----


class TestSpecialCharPaths:
    """Directory comparison with special characters in file names."""

    def test_spaces_in_filename(self, make_dir):
        """Files with spaces in their names."""
        files = {"my file.txt": b"space content"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_spaces_different_content(self, make_dir):
        """Files with spaces, different content."""
        a = make_dir("a", {"my file.txt": b"version 1"})
        b = make_dir("b", {"my file.txt": b"version 2"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "my file.txt" in result.diff

    def test_multiple_spaces(self, make_dir):
        """Files with multiple consecutive spaces."""
        files = {"a   b   c.txt": b"many spaces"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_parentheses_in_filename(self, make_dir):
        """Files with parentheses in their names."""
        files = {"file (1).txt": b"copy", "file (2).txt": b"another"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_brackets_in_filename(self, make_dir):
        """Files with square brackets in their names."""
        files = {"data[0].json": b"{}", "data[1].json": b"[]"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_curly_braces_in_filename(self, make_dir):
        """Files with curly braces in their names."""
        files = {"template{v1}.txt": b"curly"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_single_quotes_in_filename(self, make_dir):
        """Files with single quotes in their names."""
        files = {"it's a file.txt": b"quote"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_exclamation_and_at(self, make_dir):
        """Files with ! and @ in their names."""
        files = {"alert!.txt": b"bang", "user@host.txt": b"at sign"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_hash_and_percent(self, make_dir):
        """Files with # and % in their names."""
        files = {"issue#42.txt": b"hash", "100%.txt": b"percent"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_plus_equals_ampersand(self, make_dir):
        """Files with +, =, & in their names."""
        files = {
            "a+b.txt": b"plus",
            "x=y.txt": b"equals",
            "foo&bar.txt": b"ampersand",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_comma_semicolon(self, make_dir):
        """Files with commas and semicolons."""
        files = {"a,b,c.csv": b"comma", "x;y.txt": b"semi"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_dash_underscore_dot(self, make_dir):
        """Files with dashes, underscores, and multiple dots."""
        files = {
            "my-file.txt": b"dash",
            "my_file.txt": b"underscore",
            "file.tar.gz.bak": b"multi dot",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_tilde_in_filename(self, make_dir):
        """Files with tilde character."""
        files = {"backup~.txt": b"tilde"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_special_chars_in_subdir(self, make_dir):
        """Special characters in subdirectory names."""
        files = {
            "dir with spaces/file.txt": b"spaced dir",
            "dir (copy)/data.bin": b"paren dir",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is True

    def test_special_chars_only_left(self, make_dir):
        """Special-character file only in left directory."""
        a = make_dir("a", {
            "normal.txt": b"shared",
            "file (1).txt": b"extra",
        })
        b = make_dir("b", {"normal.txt": b"shared"})
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"file (1).txt"}

    def test_special_chars_mixed_differences(self, make_dir):
        """Multiple special character files with various differences."""
        a = make_dir("a", {
            "same file.txt": b"identical",
            "diff [v1].txt": b"alpha",
            "only_a!.txt": b"exclusive",
        })
        b = make_dir("b", {
            "same file.txt": b"identical",
            "diff [v1].txt": b"bravo",
            "only_b@.txt": b"exclusive",
        })
        result = komparu.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "diff [v1].txt" in result.diff
        assert result.only_left == {"only_a!.txt"}
        assert result.only_right == {"only_b@.txt"}
