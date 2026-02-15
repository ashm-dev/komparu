"""Tests for configuration system."""

from __future__ import annotations

import pytest

import komparu
from komparu._config import get_config, reset_config


class TestConfigure:

    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_defaults(self):
        cfg = get_config()
        assert cfg.chunk_size == 65536
        assert cfg.max_workers == 0
        assert cfg.timeout == 30.0
        assert cfg.follow_redirects is True
        assert cfg.verify_ssl is True
        assert cfg.size_precheck is True
        assert cfg.max_decompressed_size == 1 * 1024**3
        assert cfg.max_compression_ratio == 200
        assert cfg.max_archive_entries == 100_000
        assert cfg.comparison_timeout == 300.0
        assert cfg.allow_private_redirects is False

    def test_set_chunk_size(self):
        komparu.configure(chunk_size=131072)
        assert get_config().chunk_size == 131072

    def test_disable_limits(self):
        komparu.configure(
            max_decompressed_size=None,
            max_compression_ratio=None,
            max_archive_entries=None,
            comparison_timeout=None,
        )
        cfg = get_config()
        assert cfg.max_decompressed_size is None
        assert cfg.max_compression_ratio is None
        assert cfg.max_archive_entries is None
        assert cfg.comparison_timeout is None

    def test_unknown_option(self):
        with pytest.raises(komparu.ConfigError):
            komparu.configure(nonexistent_option=42)

    def test_reset(self):
        komparu.configure(chunk_size=999)
        reset_config()
        assert get_config().chunk_size == 65536
