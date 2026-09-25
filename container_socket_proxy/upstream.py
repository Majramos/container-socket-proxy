import http.client
import socket
from urllib.parse import urlparse

SUPPORTED_SCHEMES = ("https", "http", "tcp")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float | None) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


def validate_target(target: str) -> None:
    if target.startswith("unix:///"):
        return

    parsed = urlparse(target)

    if not parsed.scheme:
        return

    if parsed.scheme not in SUPPORTED_SCHEMES:
        raise ValueError(f"unsupported upstream scheme: {target}")

    if parsed.hostname is None:
        raise ValueError(f"upstream target has no host: {target}")


def open_upstream(target: str, timeout: float | None) -> http.client.HTTPConnection:
    validate_target(target)

    effective_timeout: float | None = timeout or None

    if target.startswith("unix://"):
        return UnixHTTPConnection(
            target[len("unix://") :],
            effective_timeout,
        )

    parsed = urlparse(target)

    if parsed.scheme in SUPPORTED_SCHEMES:
        host = parsed.hostname

        if host is None:
            raise ValueError(f"upstream target has no host: {target}")

        if parsed.scheme == "https":
            return http.client.HTTPSConnection(
                host,
                parsed.port or 443,
                timeout=effective_timeout,
            )

        return http.client.HTTPConnection(
            host,
            parsed.port or 80,
            timeout=effective_timeout,
        )

    return UnixHTTPConnection(target, effective_timeout)
