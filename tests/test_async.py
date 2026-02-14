"""Tests for async API (Phase 5)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import komparu
import komparu.aio
from komparu import CompareResult, DiffReason


@pytest.fixture(autouse=True)
def allow_localhost():
    komparu.configure(allow_private_redirects=True)
    yield
    komparu.reset_config()


# =========================================================================
# compare — async file comparison
# =========================================================================


class TestAsyncCompare:
    @pytest.mark.asyncio
    async def test_identical_files(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        content = os.urandom(1024)
        a.write_bytes(content)
        b.write_bytes(content)
        assert await komparu.aio.compare(str(a), str(b)) is True

    @pytest.mark.asyncio
    async def test_different_files(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"hello")
        b.write_bytes(b"world")
        assert await komparu.aio.compare(str(a), str(b)) is False

    @pytest.mark.asyncio
    async def test_empty_files(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"")
        b.write_bytes(b"")
        assert await komparu.aio.compare(str(a), str(b)) is True

    @pytest.mark.asyncio
    async def test_different_sizes(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"short")
        b.write_bytes(b"much longer content")
        assert await komparu.aio.compare(str(a), str(b)) is False

    @pytest.mark.asyncio
    async def test_large_file(self, tmp_path: Path):
        content = os.urandom(256 * 1024)
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(content)
        b.write_bytes(content)
        assert await komparu.aio.compare(str(a), str(b)) is True

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path: Path):
        a = tmp_path / "a.bin"
        a.write_bytes(b"data")
        with pytest.raises((FileNotFoundError, IOError)):
            await komparu.aio.compare(str(a), str(tmp_path / "missing.bin"))

    @pytest.mark.asyncio
    async def test_http_identical(self, tmp_path: Path, httpserver):
        content = b"http content"
        a = tmp_path / "a.txt"
        a.write_bytes(content)
        httpserver.expect_request("/f.txt").respond_with_data(content)
        url = httpserver.url_for("/f.txt")
        assert await komparu.aio.compare(str(a), url) is True

    @pytest.mark.asyncio
    async def test_http_different(self, tmp_path: Path, httpserver):
        a = tmp_path / "a.txt"
        a.write_bytes(b"local")
        httpserver.expect_request("/f.txt").respond_with_data(b"remote")
        url = httpserver.url_for("/f.txt")
        assert await komparu.aio.compare(str(a), url) is False


# =========================================================================
# compare — concurrent async comparisons
# =========================================================================


class TestAsyncConcurrent:
    @pytest.mark.asyncio
    async def test_concurrent_compares(self, tmp_path: Path):
        """Multiple async comparisons run concurrently."""
        import asyncio

        files = []
        content = os.urandom(512)
        for i in range(10):
            p = tmp_path / f"f{i}.bin"
            p.write_bytes(content)
            files.append(str(p))

        coros = [
            komparu.aio.compare(files[0], files[i])
            for i in range(1, 10)
        ]
        results = await asyncio.gather(*coros)
        assert all(results)


# =========================================================================
# compare_dir — async directory comparison
# =========================================================================


@pytest.fixture
def make_dir(tmp_path: Path):
    def _make(name: str, files: dict[str, bytes]) -> Path:
        d = tmp_path / name
        for rel, content in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        return d
    return _make


class TestAsyncCompareDir:
    @pytest.mark.asyncio
    async def test_identical_dirs(self, make_dir):
        files = {f"file_{i}.txt": os.urandom(200) for i in range(10)}
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = await komparu.aio.compare_dir(str(a), str(b))
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_different_dirs(self, make_dir):
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
        result = await komparu.aio.compare_dir(str(a), str(b))
        assert result.equal is False
        assert "diff.txt" in result.diff
        assert result.only_left == {"only_a.txt"}
        assert result.only_right == {"only_b.txt"}

    @pytest.mark.asyncio
    async def test_nested_dirs(self, make_dir):
        files = {
            "a/b/c.txt": b"deep",
            "x/y.txt": b"nested",
        }
        a = make_dir("a", files)
        b = make_dir("b", files)
        result = await komparu.aio.compare_dir(str(a), str(b))
        assert result.equal is True


# =========================================================================
# compare_all — async
# =========================================================================


class TestAsyncCompareAll:
    @pytest.mark.asyncio
    async def test_all_identical(self, tmp_path: Path):
        content = os.urandom(500)
        paths = []
        for i in range(5):
            p = tmp_path / f"f{i}.bin"
            p.write_bytes(content)
            paths.append(str(p))
        assert await komparu.aio.compare_all(paths) is True

    @pytest.mark.asyncio
    async def test_one_different(self, tmp_path: Path):
        paths = []
        for i in range(3):
            p = tmp_path / f"f{i}.bin"
            p.write_bytes(b"same")
            paths.append(str(p))
        p = tmp_path / "diff.bin"
        p.write_bytes(b"different")
        paths.append(str(p))
        assert await komparu.aio.compare_all(paths) is False

    @pytest.mark.asyncio
    async def test_single(self, tmp_path: Path):
        p = tmp_path / "only.bin"
        p.write_bytes(b"data")
        assert await komparu.aio.compare_all([str(p)]) is True

    @pytest.mark.asyncio
    async def test_empty(self):
        assert await komparu.aio.compare_all([]) is True


# =========================================================================
# compare_many — async
# =========================================================================


class TestAsyncCompareMany:
    @pytest.mark.asyncio
    async def test_all_identical(self, tmp_path: Path):
        content = b"identical"
        paths = []
        for i in range(3):
            p = tmp_path / f"f{i}.txt"
            p.write_bytes(content)
            paths.append(str(p))
        result = await komparu.aio.compare_many(paths)
        assert isinstance(result, CompareResult)
        assert result.all_equal is True
        assert len(result.groups) == 1

    @pytest.mark.asyncio
    async def test_all_different(self, tmp_path: Path):
        paths = []
        for i in range(3):
            p = tmp_path / f"f{i}.txt"
            p.write_bytes(f"content_{i}".encode())
            paths.append(str(p))
        result = await komparu.aio.compare_many(paths)
        assert result.all_equal is False
        assert len(result.groups) == 3

    @pytest.mark.asyncio
    async def test_two_groups(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        c = tmp_path / "c.txt"
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        c.write_bytes(b"different")
        result = await komparu.aio.compare_many([str(a), str(b), str(c)])
        assert result.all_equal is False
        assert len(result.groups) == 2
        sizes = sorted(len(g) for g in result.groups)
        assert sizes == [1, 2]


# =========================================================================
# compare_dir_urls — async
# =========================================================================


class TestAsyncCompareDirUrls:
    @pytest.mark.asyncio
    async def test_identical(self, make_dir, httpserver):
        content = b"hello world"
        d = make_dir("local", {"file.txt": content})
        httpserver.expect_request("/file.txt").respond_with_data(content)
        url_map = {"file.txt": httpserver.url_for("/file.txt")}
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_content_mismatch(self, make_dir, httpserver):
        d = make_dir("local", {"file.txt": b"local version"})
        httpserver.expect_request("/file.txt").respond_with_data(b"remote version")
        url_map = {"file.txt": httpserver.url_for("/file.txt")}
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.CONTENT_MISMATCH

    @pytest.mark.asyncio
    async def test_only_local(self, make_dir, httpserver):
        d = make_dir("local", {"a.txt": b"data", "extra.txt": b"only local"})
        httpserver.expect_request("/a.txt").respond_with_data(b"data")
        url_map = {"a.txt": httpserver.url_for("/a.txt")}
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert result.only_left == {"extra.txt"}

    @pytest.mark.asyncio
    async def test_only_remote(self, make_dir, httpserver):
        d = make_dir("local", {"a.txt": b"data"})
        httpserver.expect_request("/a.txt").respond_with_data(b"data")
        httpserver.expect_request("/b.txt").respond_with_data(b"remote only")
        url_map = {
            "a.txt": httpserver.url_for("/a.txt"),
            "b.txt": httpserver.url_for("/b.txt"),
        }
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert result.only_right == {"b.txt"}
