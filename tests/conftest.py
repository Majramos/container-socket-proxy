import http.client
import logging
import os
import socket
import socketserver
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType
from urllib.parse import urlparse

import pytest

from container_socket_proxy import rules
from container_socket_proxy.config import ProxyConfig
from container_socket_proxy.proxy import ProxyServer


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _respond(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        payload = self.server.response_body
        self.send_response(self.server.response_status)
        for name, value in self.server.extra_headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = _respond
    do_HEAD = _respond
    do_POST = _respond
    do_PUT = _respond
    do_PATCH = _respond
    do_DELETE = _respond


class FakeUpstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _FakeUpstreamHandler)
        self.response_status = 200
        self.response_body = b'{"upstream":"ok"}'
        self.extra_headers = {}
        self.requests = []


class UnixFakeUpstream(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str):
        super().__init__(socket_path, _FakeUpstreamHandler)
        self.response_status = 200
        self.response_body = b'{"upstream":"ok"}'
        self.extra_headers: dict[str, str] = {}
        self.requests: list[dict[str, object]] = []


class _HangingUpstreamHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.release.wait()


class HangingUnixUpstream(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str):
        super().__init__(socket_path, _HangingUpstreamHandler)
        self.release = threading.Event()


@pytest.fixture
def fake_upstream():
    server = FakeUpstream()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def unix_upstream():
    with tempfile.TemporaryDirectory(prefix="psp-") as tmp:
        server = UnixFakeUpstream(os.path.join(tmp, "upstream.sock"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        server.server_close()


@pytest.fixture
def hanging_unix_upstream():
    with tempfile.TemporaryDirectory(prefix="psp-") as tmp:
        server = HangingUnixUpstream(os.path.join(tmp, "hanging.sock"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.release.set()
        server.shutdown()
        server.server_close()


@pytest.fixture
def make_config(fake_upstream):
    def _make(toggles=None, max_body_bytes=0, upstream_timeout=10.0, socket_url=None):
        resolved = {section.toggle: section.default for section in rules.SECTIONS}
        resolved[rules.ALLOW_WRITE] = False
        resolved.update(toggles or {})
        return ProxyConfig(
            host="127.0.0.1",
            port=0,
            socket=socket_url or f"http://127.0.0.1:{fake_upstream.server_address[1]}",
            log_level="INFO",
            max_body_bytes=max_body_bytes,
            upstream_timeout=upstream_timeout,
            toggles=MappingProxyType(resolved),
        )

    return _make


@pytest.fixture
def dead_upstream_url():
    def _url():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return f"http://127.0.0.1:{sock.getsockname()[1]}"

    return _url


@pytest.fixture
def start_proxy():
    servers = []

    def _start(config):
        server = ProxyServer(("127.0.0.1", 0), config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield _start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def fetch():
    def _fetch(base_url, method, path, body=None, headers=None):
        parsed = urlparse(base_url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    return _fetch


@pytest.fixture(autouse=True)
def proxy_logs(caplog):
    with caplog.at_level(logging.INFO, logger="container_socket_proxy.proxy"):
        yield
