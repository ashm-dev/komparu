"""Tests for async API (Phase 5)."""

from __future__ import annotations

import io
import os
import tarfile
import zipfile
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
# compare_archive — async archive comparison
# =========================================================================


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


class TestAsyncCompareArchive:
    """Async archive comparison tests mirroring test_compare_archive.py."""

    # --- Identical archives ---

    @pytest.mark.asyncio
    async def test_tar_identical(self, make_tar):
        files = {"file.txt": b"hello", "data.bin": b"binary"}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    @pytest.mark.asyncio
    async def test_zip_identical(self, make_zip):
        files = {"doc.txt": b"content", "img.bin": os.urandom(500)}
        a = make_zip("a.zip", files)
        b = make_zip("b.zip", files)
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_nested_paths(self, make_tar):
        files = {
            "root.txt": b"root",
            "sub/nested.txt": b"nested",
            "sub/deep/file.bin": b"deep",
        }
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_empty_files(self, make_tar):
        files = {"empty.txt": b""}
        a = make_tar("a.tar.gz", files)
        b = make_tar("b.tar.gz", files)
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is True

    # --- Different archives ---

    @pytest.mark.asyncio
    async def test_content_mismatch(self, make_tar):
        """Same sizes, different content -> CONTENT_MISMATCH."""
        a = make_tar("a.tar.gz", {"file.txt": b"version A"})
        b = make_tar("b.tar.gz", {"file.txt": b"version B"})
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.CONTENT_MISMATCH

    @pytest.mark.asyncio
    async def test_size_mismatch(self, make_tar):
        a = make_tar("a.tar.gz", {"file.txt": b"short"})
        b = make_tar("b.tar.gz", {"file.txt": b"much longer content here"})
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.SIZE_MISMATCH

    @pytest.mark.asyncio
    async def test_only_left(self, make_tar):
        a = make_tar("a.tar.gz", {"common.txt": b"data", "extra.txt": b"only a"})
        b = make_tar("b.tar.gz", {"common.txt": b"data"})
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is False
        assert result.only_left == {"extra.txt"}

    @pytest.mark.asyncio
    async def test_only_right(self, make_tar):
        a = make_tar("a.tar.gz", {"common.txt": b"data"})
        b = make_tar("b.tar.gz", {"common.txt": b"data", "extra.txt": b"only b"})
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is False
        assert result.only_right == {"extra.txt"}

    @pytest.mark.asyncio
    async def test_mixed_tar_zip(self, make_tar, make_zip):
        """Compare tar vs zip with same content."""
        files = {"file.txt": b"same content"}
        a = make_tar("a.tar.gz", files)
        b = make_zip("b.zip", files)
        result = await komparu.aio.compare_archive(str(a), str(b))
        assert result.equal is True

    # --- Safety ---

    @pytest.mark.asyncio
    async def test_path_traversal_skipped(self, make_tar, tmp_path: Path):
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
        result = await komparu.aio.compare_archive(str(a_path), str(b))
        # The ../etc/passwd entry is skipped, so both have only safe.txt
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_absolute_path_skipped(self, make_tar, tmp_path: Path):
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
        result = await komparu.aio.compare_archive(str(a_path), str(b))
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_leading_dot_slash_normalized(self, make_tar, tmp_path: Path):
        """./prefix is stripped during normalization."""
        a_path = tmp_path / "a.tar.gz"
        with tarfile.open(str(a_path), "w:gz") as tf:
            info = tarfile.TarInfo(name="./file.txt")
            info.size = 5
            tf.addfile(info, io.BytesIO(b"hello"))

        b = make_tar("b.tar.gz", {"file.txt": b"hello"})
        result = await komparu.aio.compare_archive(str(a_path), str(b))
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_max_entries_bomb(self, tmp_path: Path):
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
            await komparu.aio.compare_archive(
                str(a_path), str(b_path),
                max_archive_entries=10,
            )

    # --- Errors ---

    @pytest.mark.asyncio
    async def test_nonexistent_archive(self, make_tar, tmp_path: Path):
        a = make_tar("a.tar.gz", {"file.txt": b"data"})
        with pytest.raises(IOError):
            await komparu.aio.compare_archive(str(a), str(tmp_path / "nope.tar.gz"))

    @pytest.mark.asyncio
    async def test_invalid_archive(self, tmp_path: Path):
        """Non-archive file should raise error."""
        a = tmp_path / "not_archive.txt"
        a.write_bytes(b"this is not an archive")
        b = tmp_path / "also_not.txt"
        b.write_bytes(b"this is not an archive")
        with pytest.raises(IOError):
            await komparu.aio.compare_archive(str(a), str(b))


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
        """Same size, different content → CONTENT_MISMATCH."""
        d = make_dir("local", {"file.txt": b"local_data"})
        httpserver.expect_request("/file.txt").respond_with_data(b"remote_dat")
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

    @pytest.mark.asyncio
    async def test_size_mismatch(self, make_dir, httpserver):
        """Files with different sizes -> SIZE_MISMATCH."""
        d = make_dir("local", {"file.txt": b"short"})
        httpserver.expect_request("/file.txt").respond_with_data(
            b"much longer data here"
        )
        url_map = {"file.txt": httpserver.url_for("/file.txt")}
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert "file.txt" in result.diff
        assert result.diff["file.txt"] == DiffReason.SIZE_MISMATCH

    @pytest.mark.asyncio
    async def test_empty_dir_empty_map(self, tmp_path: Path):
        """Empty directory with empty url_map -> equal."""
        d = tmp_path / "empty_local"
        d.mkdir()
        result = await komparu.aio.compare_dir_urls(str(d), {})
        assert result.equal is True
        assert result.diff == {}
        assert result.only_left == set()
        assert result.only_right == set()

    @pytest.mark.asyncio
    async def test_empty_dir_with_urls(self, tmp_path: Path, httpserver):
        """Empty directory but url_map has entries -> only_right."""
        d = tmp_path / "empty_local"
        d.mkdir()
        httpserver.expect_request("/remote.txt").respond_with_data(b"data")
        url_map = {"remote.txt": httpserver.url_for("/remote.txt")}
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert result.only_right == {"remote.txt"}
        assert result.only_left == set()

    @pytest.mark.asyncio
    async def test_dir_with_no_urls(self, make_dir):
        """Directory has files but url_map is empty -> only_left."""
        d = make_dir("local", {"a.txt": b"aaa", "b.txt": b"bbb"})
        result = await komparu.aio.compare_dir_urls(str(d), {})
        assert result.equal is False
        assert result.only_left == {"a.txt", "b.txt"}
        assert result.only_right == set()

    @pytest.mark.asyncio
    async def test_nested_local_files(self, make_dir, httpserver):
        """Local dir has nested subdirectories, url_map references them."""
        nested_content = b"deeply nested content"
        d = make_dir("local", {
            "a/b/c.txt": nested_content,
            "x/y.txt": b"shallow nested",
        })
        httpserver.expect_request("/a/b/c.txt").respond_with_data(nested_content)
        httpserver.expect_request("/x/y.txt").respond_with_data(b"shallow nested")
        url_map = {
            "a/b/c.txt": httpserver.url_for("/a/b/c.txt"),
            "x/y.txt": httpserver.url_for("/x/y.txt"),
        }
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_multiple_files_mixed(self, make_dir, httpserver):
        """Multiple files: some identical, some different, some only_left/right."""
        d = make_dir("local", {
            "same.txt": b"identical",
            "diff.txt": b"local_ver",
            "only_local.txt": b"exclusive left",
        })
        httpserver.expect_request("/same.txt").respond_with_data(b"identical")
        httpserver.expect_request("/diff.txt").respond_with_data(b"remot_ver")
        httpserver.expect_request("/only_remote.txt").respond_with_data(
            b"exclusive right"
        )
        url_map = {
            "same.txt": httpserver.url_for("/same.txt"),
            "diff.txt": httpserver.url_for("/diff.txt"),
            "only_remote.txt": httpserver.url_for("/only_remote.txt"),
        }
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is False
        assert "diff.txt" in result.diff
        assert result.diff["diff.txt"] == DiffReason.CONTENT_MISMATCH
        assert result.only_left == {"only_local.txt"}
        assert result.only_right == {"only_remote.txt"}

    @pytest.mark.asyncio
    async def test_binary_content(self, make_dir, httpserver):
        """Binary content comparison via HTTP."""
        binary_data = os.urandom(4096)
        d = make_dir("local", {"data.bin": binary_data})
        httpserver.expect_request("/data.bin").respond_with_data(binary_data)
        url_map = {"data.bin": httpserver.url_for("/data.bin")}
        result = await komparu.aio.compare_dir_urls(str(d), url_map)
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_large_file(self, make_dir, httpserver):
        """Large file (~256KB) comparison via HTTP."""
        large_content = os.urandom(256 * 1024)
        d = make_dir("local", {"large.bin": large_content})
        httpserver.expect_request("/large.bin").respond_with_data(large_content)
        url_map = {"large.bin": httpserver.url_for("/large.bin")}
        # Use chunk_size >= file size since test server lacks Range support
        result = await komparu.aio.compare_dir_urls(
            str(d), url_map, chunk_size=256 * 1024
        )
        assert result.equal is True

    @pytest.mark.asyncio
    async def test_concurrent_dir_urls(self, make_dir, httpserver):
        """Multiple async compare_dir_urls calls running concurrently."""
        import asyncio

        dirs = []
        url_maps = []
        for i in range(5):
            content = f"content_{i}".encode()
            name = f"f{i}.txt"
            d = make_dir(f"local_{i}", {name: content})
            httpserver.expect_request(f"/dir{i}/{name}").respond_with_data(content)
            dirs.append(str(d))
            url_maps.append({name: httpserver.url_for(f"/dir{i}/{name}")})

        coros = [
            komparu.aio.compare_dir_urls(dirs[i], url_maps[i])
            for i in range(5)
        ]
        results = await asyncio.gather(*coros)
        assert all(r.equal for r in results)
