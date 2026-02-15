"""Tests for parallel comparison (Phase 4)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import komparu
from komparu import CompareResult, DiffReason


@pytest.fixture(autouse=True)
def allow_localhost():
    """Allow connections to localhost for testing."""
    komparu.configure(allow_private_redirects=True)
    yield
    komparu.reset_config()


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


# =========================================================================
# Thread pool — via parallel directory comparison
# =========================================================================


class TestParallelDirCompare:
    """Directory comparison using thread pool (max_workers > 1)."""

    def test_identical_parallel(self, make_dir):
        files = {f"file_{i}.txt": os.urandom(200) for i in range(20)}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b), max_workers=4)
        assert result.equal is True

    def test_identical_auto_workers(self, make_dir):
        files = {f"f{i}.bin": os.urandom(100) for i in range(10)}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b), max_workers=0)
        assert result.equal is True

    def test_differences_parallel(self, make_dir):
        a = make_dir("a", {
            "same.txt": b"identical",
            "diff.txt": b"version A",
            "only_a.txt": b"exclusive",
        })
        b = make_dir("b", {
            "same.txt": b"identical",
            "diff.txt": b"version B",
            "only_b.txt": b"exclusive",
        })
        result = komparu.compare_dir(str(a), str(b), max_workers=4)
        assert result.equal is False
        assert "diff.txt" in result.diff
        assert result.only_left == {"only_a.txt"}
        assert result.only_right == {"only_b.txt"}

    def test_many_files_parallel(self, make_dir):
        """Stress test with many small files."""
        files = {f"dir{i % 5}/file_{i}.txt": f"content_{i}".encode() for i in range(100)}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b), max_workers=8)
        assert result.equal is True

    def test_sequential_fallback(self, make_dir):
        """max_workers=1 forces sequential comparison."""
        files = {"a.txt": b"hello", "b.txt": b"world"}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = komparu.compare_dir(str(a), str(b), max_workers=1)
        assert result.equal is True


# =========================================================================
# compare_all
# =========================================================================


class TestCompareAll:
    """compare_all — check if all sources are identical."""

    def test_all_identical(self, tmp_path: Path):
        content = os.urandom(500)
        paths = []
        for i in range(5):
            p = tmp_path / f"file_{i}.bin"
            p.write_bytes(content)
            paths.append(str(p))
        assert komparu.compare_all(paths) is True

    def test_one_different(self, tmp_path: Path):
        paths = []
        for i in range(4):
            p = tmp_path / f"file_{i}.bin"
            p.write_bytes(b"same content")
            paths.append(str(p))
        # Make last file different
        p = tmp_path / "file_diff.bin"
        p.write_bytes(b"different content")
        paths.append(str(p))
        assert komparu.compare_all(paths) is False

    def test_single_source(self, tmp_path: Path):
        p = tmp_path / "only.bin"
        p.write_bytes(b"data")
        assert komparu.compare_all([str(p)]) is True

    def test_empty_list(self):
        assert komparu.compare_all([]) is True

    def test_two_identical(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        assert komparu.compare_all([str(a), str(b)]) is True

    def test_two_different(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"one")
        b.write_bytes(b"two")
        assert komparu.compare_all([str(a), str(b)]) is False

    def test_parallel_all(self, tmp_path: Path):
        content = os.urandom(1000)
        paths = []
        for i in range(10):
            p = tmp_path / f"file_{i}.bin"
            p.write_bytes(content)
            paths.append(str(p))
        assert komparu.compare_all(paths, max_workers=4) is True

    def test_sequential_all(self, tmp_path: Path):
        content = b"hello"
        paths = []
        for i in range(3):
            p = tmp_path / f"f_{i}.txt"
            p.write_bytes(content)
            paths.append(str(p))
        assert komparu.compare_all(paths, max_workers=1) is True


# =========================================================================
# compare_many
# =========================================================================


class TestCompareMany:
    """compare_many — detailed pairwise comparison."""

    def test_all_identical(self, tmp_path: Path):
        content = b"identical"
        paths = []
        for i in range(3):
            p = tmp_path / f"f{i}.txt"
            p.write_bytes(content)
            paths.append(str(p))

        result = komparu.compare_many(paths)
        assert isinstance(result, CompareResult)
        assert result.all_equal is True
        assert len(result.groups) == 1
        assert len(result.groups[0]) == 3

    def test_all_different(self, tmp_path: Path):
        paths = []
        for i in range(3):
            p = tmp_path / f"f{i}.txt"
            p.write_bytes(f"content_{i}".encode())
            paths.append(str(p))

        result = komparu.compare_many(paths)
        assert result.all_equal is False
        assert len(result.groups) == 3  # each in its own group

    def test_two_groups(self, tmp_path: Path):
        """Two files match, one is different."""
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        c = tmp_path / "c.txt"
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        c.write_bytes(b"different")

        result = komparu.compare_many([str(a), str(b), str(c)])
        assert result.all_equal is False
        assert len(result.groups) == 2

        # Find the group with 2 members
        sizes = sorted(len(g) for g in result.groups)
        assert sizes == [1, 2]

    def test_single_source(self, tmp_path: Path):
        p = tmp_path / "only.txt"
        p.write_bytes(b"data")
        result = komparu.compare_many([str(p)])
        assert result.all_equal is True
        assert len(result.groups) == 1

    def test_diff_dict(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"hello")
        b.write_bytes(b"world")

        result = komparu.compare_many([str(a), str(b)])
        assert (str(a), str(b)) in result.diff
        assert result.diff[(str(a), str(b))] is False

    def test_parallel_many(self, tmp_path: Path):
        content = b"same"
        paths = []
        for i in range(6):
            p = tmp_path / f"f{i}.txt"
            p.write_bytes(content)
            paths.append(str(p))
        result = komparu.compare_many(paths, max_workers=4)
        assert result.all_equal is True


# =========================================================================
# compare_dir_urls
# =========================================================================


class TestCompareDirUrls:
    """compare_dir_urls — compare directory against URL mapping."""

    def test_identical(self, make_dir, httpserver):
        content = b"hello world"
        d = make_dir("local", {"file.txt": content})
        httpserver.expect_request("/file.txt").respond_with_data(content)

        url_map = {"file.txt": httpserver.url_for("/file.txt")}
        result = komparu.compare_dir_urls(str(d), url_map)
        assert result.equal is True

    def test_content_mismatch(self, make_dir, httpserver):
        d = make_dir("local", {"file.txt": b"local_version_"})
        httpserver.expect_request("/file.txt").respond_with_data(b"remote_version")

        url_map = {"file.txt": httpserver.url_for("/file.txt")}
        result = komparu.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] in (
            DiffReason.CONTENT_MISMATCH,
            DiffReason.SIZE_MISMATCH,
        )

    def test_only_local(self, make_dir, httpserver):
        d = make_dir("local", {"a.txt": b"data", "extra.txt": b"only local"})
        httpserver.expect_request("/a.txt").respond_with_data(b"data")

        url_map = {"a.txt": httpserver.url_for("/a.txt")}
        result = komparu.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert result.only_left == {"extra.txt"}

    def test_only_remote(self, make_dir, httpserver):
        d = make_dir("local", {"a.txt": b"data"})
        httpserver.expect_request("/a.txt").respond_with_data(b"data")
        httpserver.expect_request("/b.txt").respond_with_data(b"remote only")

        url_map = {
            "a.txt": httpserver.url_for("/a.txt"),
            "b.txt": httpserver.url_for("/b.txt"),
        }
        result = komparu.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert result.only_right == {"b.txt"}

    def test_multiple_files(self, make_dir, httpserver):
        files = {f"f{i}.txt": f"content_{i}".encode() for i in range(5)}
        d = make_dir("local", files)
        for name, content in files.items():
            httpserver.expect_request(f"/{name}").respond_with_data(content)

        url_map = {name: httpserver.url_for(f"/{name}") for name in files}
        result = komparu.compare_dir_urls(str(d), url_map)
        assert result.equal is True

    def test_parallel_dir_urls(self, make_dir, httpserver):
        files = {f"f{i}.txt": f"data_{i}".encode() for i in range(5)}
        d = make_dir("local", files)
        for name, content in files.items():
            httpserver.expect_request(f"/{name}").respond_with_data(content)

        url_map = {name: httpserver.url_for(f"/{name}") for name in files}
        result = komparu.compare_dir_urls(str(d), url_map, max_workers=4)
        assert result.equal is True
