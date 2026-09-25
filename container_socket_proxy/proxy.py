import http.client
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from container_socket_proxy import rules, upstream
from container_socket_proxy.config import ProxyConfig

logger = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = frozenset(
    {
        "connections",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

STRIPPED_REQUEST_HEADERS = HOP_BY_HOP_HEADERS | {"host", "content-length", "expect"}
STRIPPED_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS | {"server", "datr"}
RELAY_CHUNK_SIZE = 65536
MAX_TRAILER_BYTES = 65536


class BodyTooLarge(Exception):
    pass


class MalformedBody(Exception):
    pass


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: ProxyConfig) -> None:
        super().__init__(address, ProxyHandler)
        self.config = config


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120
    server: ProxyServer
    request_started: float
    relay_started: bool = False

    def version_string(self) -> str:
        return "container-socket-proxy"

    def do_GET(self) -> None:
        self._forward()

    do_HEAD = do_GET
    do_POST = do_GET
    do_PUT = do_GET
    do_PATCH = do_GET
    do_DELETE = do_GET
    do_OPTIONS = do_GET

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("%s %s", self.address_string(), fmt % args)

    def _elapsed_ms(self) -> float:
        return (time.monotonic() - self.request_started) * 1000

    def _reject(
        self,
        status: int,
        reason: str,
        body: str | None = None,
        verb: str = "denied",
    ) -> None:
        logger.warning(
            "%s %s %s from %s: %s",
            verb,
            self.command,
            self.path,
            self.address_string(),
            reason,
        )
        self._send_text(status, reason if body is None else body)

    def _read_body(self) -> bytes | None:
        try:
            return self._read_request_body()
        except BodyTooLarge as exc:
            self._reject(
                413,
                str(exc),
                body="request body exceeds MAX_BODY_BYTES",
                verb="rejected",
            )
        except MalformedBody as exc:
            self._reject(400, str(exc), verb="rejected")
        except OSError as exc:
            logger.warning(
                "client connection failed from %s while reading body: %s",
                self.address_string(),
                exc,
            )
            self.close_connection = True
        return None

    def _forward(self) -> None:
        self.request_started = time.monotonic()
        client = self.address_string()

        if self.headers.get("Upgrade"):
            self._reject(501, "hijacked connections are not supported")
            return

        decision = rules.decide(
            self.command,
            self.path,
            self.server.config.toggles,
        )

        if not decision.allowed:
            self._reject(
                403,
                decision.reason,
                body=f"container-socket-proxy: {decision.reason}",
            )
            return

        body = self._read_body()

        if body is None:
            return

        try:
            status = self._relay(body)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            logger.warning(
                "upstream failure for %s %s from %s after %.1f ms: %s",
                self.command,
                self.path,
                client,
                self._elapsed_ms(),
                exc,
            )

            if not self.relay_started:
                self._send_text(502, f"container socket unreachable: {exc}")

            return

        logger.info(
            "allowed %s %s from %s via %s -> %s in %.1f ms",
            self.command,
            self.path,
            client,
            decision.section,
            status,
            self._elapsed_ms(),
        )

    def _relay(self, body: bytes) -> int:
        conn = upstream.open_upstream(
            self.server.config.socket,
            self.server.config.upstream_timeout,
        )

        try:
            headers: dict[str, str] = {}

            for name, value in self.headers.items():
                if name.lower() in STRIPPED_REQUEST_HEADERS:
                    continue
                headers[name] = value

            if body:
                headers["Content-Length"] = str(len(body))

            conn.request(
                self.command,
                self.path,
                body=body or None,
                headers=headers,
            )

            response = conn.getresponse()

            if conn.sock is not None:
                conn.sock.settimeout(None)

            self._relay_response(response)
            return response.status
        finally:
            conn.close()

    def _relay_response(self, response: http.client.HTTPResponse) -> None:
        self.relay_started = True
        self.send_response(response.status, response.reason or None)

        content_length: str | None = None

        for name, value in response.getheaders():
            lowered = name.lower()

            if lowered in STRIPPED_RESPONSE_HEADERS:
                continue
            if lowered == "content-length":
                content_length = value
                continue

            self.send_header(name, value)

        if content_length is not None:
            self.send_header("Content-Length", content_length)

        self.send_header("Connection", "close")
        self.end_headers()

        if self.command == "HEAD":
            self.close_connection = True
            return

        try:
            while True:
                chunk = response.read1(RELAY_CHUNK_SIZE)

                if not chunk:
                    break

                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            logger.info(
                "client disconnected while streaming %s %s from %s after %.1f ms",
                self.command,
                self.path,
                self.address_string(),
                self._elapsed_ms(),
            )
        finally:
            self.close_connection = True

    def _read_request_body(self) -> bytes:
        encoding = (self.headers.get("Transfer-Encoding") or "").lower()

        if "chunked" in encoding:
            return self._read_chunked_body()

        length_header = self.headers.get("Content-Length")

        if length_header is None:
            return b""

        try:
            length = int(length_header)
        except ValueError:
            raise MalformedBody("invalid Content-Length header") from None

        if length < 0:
            raise MalformedBody("negative Content-Length header")

        limit = self.server.config.max_body_bytes

        if limit and length > limit:
            raise BodyTooLarge(
                f"request body of {length} bytes exceeds the configured limit"
            )

        return self._read_exact(length)

    def _read_exact(self, count: int) -> bytes:
        chunks: list[bytes] = []
        remaining = count

        while remaining > 0:
            chunk = self.rfile.read(min(remaining, RELAY_CHUNK_SIZE))

            if not chunk:
                raise MalformedBody("unexpected end of request body")

            chunks.append(chunk)
            remaining -= len(chunk)

        return b"".join(chunks)

    def _read_chunked_body(self) -> bytes:
        limit = self.server.config.max_body_bytes
        chunks: list[bytes] = []
        total = 0

        while True:
            size_line = self.rfile.readline(RELAY_CHUNK_SIZE)

            if not size_line:
                raise MalformedBody("unexpected end of chunked request body")

            try:
                chunk_size = int(size_line.split(b";")[0].strip(), 16)
            except ValueError:
                raise MalformedBody("invalid chunk size line") from None

            if chunk_size == 0:
                break

            if chunk_size < 0:
                raise MalformedBody("negative chunk size")

            total += chunk_size

            if limit and total > limit:
                raise BodyTooLarge("chunked request body exceeds the configured limit")

            chunks.append(self._read_exact(chunk_size))
            self.rfile.readline(2)

        trailer_total = 0

        while True:
            trailer_line = self.rfile.readline(RELAY_CHUNK_SIZE)

            if trailer_line in (b"\r\n", b"\n", b""):
                break

            trailer_total += len(trailer_line)

            if trailer_total > MAX_TRAILER_BYTES:
                raise MalformedBody("chunked trailers exceed the allowed size")

        return b"".join(chunks)

    def _send_text(self, status: int, message: str) -> None:
        payload = message.encode()
        self.close_connection = True

        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()

            if self.command != "HEAD":
                self.wfile.write(payload)
        except OSError:
            logger.debug("client disconnected before response: %s", status)
