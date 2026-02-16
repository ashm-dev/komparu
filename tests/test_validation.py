"""Tests for parameter validation."""

import pytest
import komparu
from komparu import Source


class TestEmptyPaths:
    def test_compare_empty_source_a(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="source_a cannot be empty"):
            komparu.compare("", str(f))

    def test_compare_empty_source_b(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="source_b cannot be empty"):
            komparu.compare(str(f), "")

    def test_compare_dir_empty(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        with pytest.raises(ValueError, match="dir_a cannot be empty"):
            komparu.compare_dir("", str(d))

    def test_compare_archive_empty(self, tmp_path):
        with pytest.raises(ValueError, match="path_a cannot be empty"):
            komparu.compare_archive("", "/tmp/b.tar.gz")

    def test_compare_dir_urls_empty(self, tmp_path):
        with pytest.raises(ValueError, match="dir_path cannot be empty"):
            komparu.compare_dir_urls("", {})


class TestChunkSize:
    def test_zero(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            komparu.compare(str(f), str(f), chunk_size=0)

    def test_negative(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            komparu.compare(str(f), str(f), chunk_size=-1)

    def test_too_large(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="chunk_size must be <= 1GB"):
            komparu.compare(str(f), str(f), chunk_size=2 * 1024 * 1024 * 1024)

    def test_valid_boundary(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert komparu.compare(str(f), str(f), chunk_size=1) is True


class TestTimeout:
    def test_zero(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="timeout must be positive"):
            komparu.compare(str(f), str(f), timeout=0)

    def test_negative(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="timeout must be positive"):
            komparu.compare(str(f), str(f), timeout=-1)


class TestMaxWorkers:
    def test_negative(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        with pytest.raises(ValueError, match="max_workers must be non-negative"):
            komparu.compare_dir(str(d), str(d), max_workers=-1)

    def test_too_large(self, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        with pytest.raises(ValueError, match="max_workers must be <= 256"):
            komparu.compare_dir(str(d), str(d), max_workers=1000)


class TestSourceValidation:
    def test_empty_url(self):
        with pytest.raises(ValueError, match="Source.url cannot be empty"):
            Source(url="")

    def test_valid_source(self):
        s = Source(url="/path/to/file")
        assert s.url == "/path/to/file"


class TestCompareAllValidation:
    def test_chunk_size_zero(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            komparu.compare_all([str(f), str(f)], chunk_size=0)

    def test_timeout_negative(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="timeout must be positive"):
            komparu.compare_all([str(f), str(f)], timeout=-1)

    def test_max_workers_negative(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="max_workers must be non-negative"):
            komparu.compare_all([str(f), str(f)], max_workers=-1)


class TestCompareManyValidation:
    def test_chunk_size_zero(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            komparu.compare_many([str(f), str(f)], chunk_size=0)

    def test_timeout_negative(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="timeout must be positive"):
            komparu.compare_many([str(f), str(f)], timeout=-1)
