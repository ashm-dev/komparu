"""Tests for HTTP comparison (Phase 2)."""

from __future__ import annotations

import os

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

import komparu


@pytest.fixture(autouse=True)
def allow_localhost():
    """Allow connections to localhost for testing."""
    komparu.configure(allow_private_redirects=True)
    yield
    komparu.reset_config()


class TestHttpIdentical:
    """Two identical remote files should return True."""

    def test_identical_small(self, httpserver: HTTPServer):
        content = b"hello world"
        httpserver.expect_request("/a").respond_with_data(content)
        httpserver.expect_request("/b").respond_with_data(content)
        url_a = httpserver.url_for("/a")
        url_b = httpserver.url_for("/b")
        assert komparu.compare(url_a, url_b) is True

    def test_identical_binary(self, httpserver: HTTPServer):
        content = os.urandom(5000)
        httpserver.expect_request("/a").respond_with_data(content)
        httpserver.expect_request("/b").respond_with_data(content)
        assert komparu.compare(
            httpserver.url_for("/a"),
            httpserver.url_for("/b"),
        ) is True


class TestHttpDifferent:
    """Two different remote files should return False."""

    def test_different_content(self, httpserver: HTTPServer):
        httpserver.expect_request("/a").respond_with_data(b"hello")
        httpserver.expect_request("/b").respond_with_data(b"world")
        assert komparu.compare(
            httpserver.url_for("/a"),
            httpserver.url_for("/b"),
        ) is False

    def test_different_size(self, httpserver: HTTPServer):
        httpserver.expect_request("/a").respond_with_data(b"short")
        httpserver.expect_request("/b").respond_with_data(b"much longer content here")
        assert komparu.compare(
            httpserver.url_for("/a"),
            httpserver.url_for("/b"),
        ) is False


class TestMixedComparison:
    """Local file vs HTTP URL."""

    def test_local_vs_http_identical(self, httpserver: HTTPServer, make_file):
        content = b"mixed comparison test data"
        local = make_file("local.bin", content)
        httpserver.expect_request("/remote").respond_with_data(content)
        assert komparu.compare(
            str(local),
            httpserver.url_for("/remote"),
        ) is True

    def test_local_vs_http_different(self, httpserver: HTTPServer, make_file):
        local = make_file("local.bin", b"local data")
        httpserver.expect_request("/remote").respond_with_data(b"remote data")
        assert komparu.compare(
            str(local),
            httpserver.url_for("/remote"),
        ) is False


class TestHttpHeaders:
    """Custom headers are sent correctly."""

    def test_custom_headers(self, httpserver: HTTPServer, make_file):
        content = b"auth protected content"
        local = make_file("local.bin", content)

        def handler(request):
            if request.headers.get("Authorization") != "Bearer test_token":
                return Response("Unauthorized", status=401)
            return Response(content, status=200)

        httpserver.expect_request("/protected").respond_with_handler(handler)

        # Without headers — should fail
        with pytest.raises(IOError):
            komparu.compare(
                str(local),
                httpserver.url_for("/protected"),
            )

        # With headers — should succeed
        assert komparu.compare(
            str(local),
            httpserver.url_for("/protected"),
            headers={"Authorization": "Bearer test_token"},
        ) is True


class TestHttpErrors:
    """HTTP error handling."""

    def test_404_not_found(self, httpserver: HTTPServer, make_file):
        local = make_file("local.bin", b"data")
        httpserver.expect_request("/missing").respond_with_data(
            b"Not Found", status=404
        )
        with pytest.raises(IOError):
            komparu.compare(str(local), httpserver.url_for("/missing"))

    def test_500_server_error(self, httpserver: HTTPServer, make_file):
        local = make_file("local.bin", b"data")
        httpserver.expect_request("/error").respond_with_data(
            b"Internal Error", status=500
        )
        with pytest.raises(IOError):
            komparu.compare(str(local), httpserver.url_for("/error"))

    def test_invalid_url(self, make_file):
        local = make_file("local.bin", b"data")
        with pytest.raises(IOError):
            komparu.compare(str(local), "http://invalid.host.komparu.test/file")


class TestHttpRangeSupport:
    """Range request handling."""

    def test_range_request_with_handler(self, httpserver: HTTPServer):
        """Server that properly handles Range requests."""
        content = os.urandom(10000)

        def range_handler(request):
            range_header = request.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                parts = range_header[6:].split("-")
                start = int(parts[0])
                end = int(parts[1]) if parts[1] else len(content) - 1
                end = min(end, len(content) - 1)
                chunk = content[start:end + 1]
                resp = Response(chunk, status=206)
                resp.headers["Content-Range"] = f"bytes {start}-{end}/{len(content)}"
                resp.headers["Content-Length"] = str(len(chunk))
                return resp
            # HEAD or full GET
            resp = Response(content, status=200)
            resp.headers["Content-Length"] = str(len(content))
            resp.headers["Accept-Ranges"] = "bytes"
            return resp

        httpserver.expect_request("/a").respond_with_handler(range_handler)
        httpserver.expect_request("/b").respond_with_handler(range_handler)

        assert komparu.compare(
            httpserver.url_for("/a"),
            httpserver.url_for("/b"),
        ) is True
