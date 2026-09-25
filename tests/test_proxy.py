import re
import socket
import time
from urllib.parse import urlparse


def _assert_log(caplog, pattern, timeout=2.0):
    deadline = time.monotonic() + timeout
    while True:
        messages = [record.getMessage() for record in caplog.records]
        if any(re.search(pattern, message) for message in messages):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"no log matching {pattern!r} in {messages}")
        time.sleep(0.01)


def _send_raw(base_url, payload, half_close=False):
    parsed = urlparse(base_url)
    sock = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
    try:
        sock.sendall(payload)
        if half_close:
            sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    return b"".join(chunks)


def _raw_status_and_body(raw):
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split()[1])
    return status, body


def test_proxy_relays_allowed_request_to_upstream_and_back(
    fake_upstream, make_config, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(make_config())
    # when
    status, headers, body = fetch(base_url, "GET", "/_ping")
    # then
    assert status == 200
    assert body == b'{"upstream":"ok"}'
    assert headers["Content-Length"] == "17"
    assert fake_upstream.requests[0]["method"] == "GET"
    assert fake_upstream.requests[0]["path"] == "/_ping"
    _assert_log(
        caplog,
        r"allowed GET /_ping from 127\.0\.0\.1 via ALLOW_PING -> 200 in \d+\.\d+ ms",
    )


def test_proxy_relays_upstream_status_and_body(
    fake_upstream, make_config, start_proxy, fetch
):
    # given
    fake_upstream.response_status = 404
    fake_upstream.response_body = b'{"cause":"no such container"}'
    base_url = start_proxy(make_config())
    # when
    status, _headers, body = fetch(base_url, "GET", "/_ping")
    # then
    assert status == 404
    assert body == b'{"cause":"no such container"}'


def test_proxy_returns_403_with_reason_when_toggle_is_off(
    make_config, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(make_config())
    # when
    status, headers, body = fetch(base_url, "GET", "/containers/json")
    # then
    assert status == 403
    assert body == b"container-socket-proxy: ALLOW_CONTAINERS is not enabled"
    assert headers["Content-Type"] == "text/plain; charset=utf-8"
    _assert_log(
        caplog,
        r"denied GET /containers/json from 127\.0\.0\.1: ALLOW_CONTAINERS is not enabled",
    )


def test_proxy_returns_403_for_write_method_without_allow_write(
    make_config, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(make_config(toggles={"ALLOW_CONTAINERS": True}))
    # when
    status, _headers, body = fetch(base_url, "POST", "/containers/create")
    # then
    assert status == 403
    assert body == b"container-socket-proxy: method POST requires ALLOW_WRITE"
    _assert_log(
        caplog,
        r"denied POST /containers/create from 127\.0\.0\.1: method POST requires ALLOW_WRITE",
    )


def test_proxy_returns_403_for_unmatched_path(make_config, start_proxy, fetch, caplog):
    # given
    base_url = start_proxy(make_config())
    # when
    status, _headers, body = fetch(base_url, "GET", "/foo")
    # then
    assert status == 403
    assert (
        body == b"container-socket-proxy: no enabled endpoint group matches this path"
    )
    _assert_log(
        caplog,
        r"denied GET /foo from 127\.0\.0\.1: no enabled endpoint group matches this path",
    )


def test_proxy_relays_post_body_when_write_is_allowed(
    fake_upstream, make_config, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(
        make_config(toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True})
    )
    # when
    status, _headers, _body = fetch(
        base_url, "POST", "/containers/create", body=b'{"image":"alpine"}'
    )
    # then
    assert status == 200
    assert fake_upstream.requests[0]["method"] == "POST"
    assert fake_upstream.requests[0]["path"] == "/containers/create"
    assert fake_upstream.requests[0]["body"] == b'{"image":"alpine"}'
    assert fake_upstream.requests[0]["headers"]["Content-Length"] == "18"
    _assert_log(
        caplog,
        r"allowed POST /containers/create from 127\.0\.0\.1 via ALLOW_CONTAINERS -> 200 in \d+\.\d+ ms",
    )


def test_proxy_rejects_oversized_body_with_413(make_config, start_proxy, fetch, caplog):
    # given
    base_url = start_proxy(
        make_config(
            toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True},
            max_body_bytes=16,
        )
    )
    # when
    status, _headers, body = fetch(
        base_url, "POST", "/containers/create", body=b"x" * 100
    )
    # then
    assert status == 413
    assert body == b"request body exceeds MAX_BODY_BYTES"
    _assert_log(
        caplog,
        r"rejected POST /containers/create from 127\.0\.0\.1: request body of 100 bytes exceeds the configured limit",
    )


def test_proxy_allows_body_at_max_body_bytes_limit(
    fake_upstream, make_config, start_proxy, fetch
):
    # given
    base_url = start_proxy(
        make_config(
            toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True},
            max_body_bytes=16,
        )
    )
    # when
    status, _headers, _body = fetch(
        base_url, "POST", "/containers/create", body=b"x" * 16
    )
    # then
    assert status == 200
    assert fake_upstream.requests[0]["body"] == b"x" * 16


def test_proxy_rejects_invalid_content_length_with_400(
    make_config, start_proxy, caplog
):
    # given
    base_url = start_proxy(make_config())
    payload = b"GET /_ping HTTP/1.1\r\nHost: localhost\r\nContent-Length: abc\r\n\r\n"
    # when
    status, body = _raw_status_and_body(_send_raw(base_url, payload))
    # then
    assert status == 400
    assert body == b"invalid Content-Length header"
    _assert_log(
        caplog,
        r"rejected GET /_ping from 127\.0\.0\.1: invalid Content-Length header",
    )


def test_proxy_rejects_truncated_body_with_400(make_config, start_proxy, caplog):
    # given
    base_url = start_proxy(make_config())
    payload = b"GET /_ping HTTP/1.1\r\nHost: localhost\r\nContent-Length: 10\r\n\r\n"
    # when
    status, body = _raw_status_and_body(_send_raw(base_url, payload, half_close=True))
    # then
    assert status == 400
    assert body == b"unexpected end of request body"
    _assert_log(
        caplog,
        r"rejected GET /_ping from 127\.0\.0\.1: unexpected end of request body",
    )


def test_proxy_relays_chunked_body_as_content_lengthed_request(
    fake_upstream, make_config, start_proxy
):
    # given
    base_url = start_proxy(
        make_config(toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True})
    )
    payload = (
        b"POST /containers/create HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"5\r\nhello\r\n3\r\nabc\r\n0\r\n\r\n"
    )
    # when
    status, _body = _raw_status_and_body(_send_raw(base_url, payload))
    # then
    assert status == 200
    assert fake_upstream.requests[0]["body"] == b"helloabc"
    assert fake_upstream.requests[0]["headers"]["Content-Length"] == "8"
    assert "Transfer-Encoding" not in fake_upstream.requests[0]["headers"]


def test_proxy_rejects_oversized_chunked_body_with_413(
    make_config, start_proxy, caplog
):
    # given
    base_url = start_proxy(
        make_config(
            toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True},
            max_body_bytes=16,
        )
    )
    payload = (
        b"POST /containers/create HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"10\r\n" + b"a" * 16 + b"\r\n10\r\n" + b"b" * 16 + b"\r\n0\r\n\r\n"
    )
    # when
    status, body = _raw_status_and_body(_send_raw(base_url, payload))
    # then
    assert status == 413
    assert body == b"request body exceeds MAX_BODY_BYTES"
    _assert_log(
        caplog,
        r"rejected POST /containers/create from 127\.0\.0\.1: "
        r"chunked request body exceeds the configured limit",
    )


def test_proxy_accepts_bare_lf_chunked_framing(fake_upstream, make_config, start_proxy):
    # given
    base_url = start_proxy(
        make_config(toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True})
    )
    payload = (
        b"POST /containers/create HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"5\nhello\n3\nabc\n0\n\n"
    )
    # when
    status, _body = _raw_status_and_body(_send_raw(base_url, payload))
    # then
    assert status == 200
    assert fake_upstream.requests[0]["body"] == b"helloabc"


def test_proxy_rejects_excessive_chunked_trailers_with_400(
    make_config, start_proxy, caplog
):
    # given
    base_url = start_proxy(
        make_config(toggles={"ALLOW_CONTAINERS": True, "ALLOW_WRITE": True})
    )
    trailer = b"x: " + b"y" * (65536 // 2) + b"\r\n"
    payload = (
        b"POST /containers/create HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"0\r\n" + trailer * 2
    )
    # when
    status, body = _raw_status_and_body(_send_raw(base_url, payload))
    # then
    assert status == 400
    assert body == b"chunked trailers exceed the allowed size"
    _assert_log(
        caplog,
        r"rejected POST /containers/create from 127\.0\.0\.1: "
        r"chunked trailers exceed the allowed size",
    )


def test_proxy_returns_502_when_upstream_is_unreachable(
    make_config, dead_upstream_url, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(make_config(socket_url=dead_upstream_url()))
    # when
    status, _headers, body = fetch(base_url, "GET", "/_ping")
    # then
    assert status == 502
    assert body.startswith(b"container socket unreachable: ")
    _assert_log(
        caplog,
        r"upstream failure for GET /_ping from 127\.0\.0\.1 after \d+\.\d+ ms: ",
    )


def test_proxy_returns_501_for_upgrade_requests(
    make_config, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(make_config())
    # when
    status, _headers, body = fetch(
        base_url, "GET", "/_ping", headers={"Upgrade": "websocket"}
    )
    # then
    assert status == 501
    assert body == b"hijacked connections are not supported"
    _assert_log(
        caplog,
        r"denied GET /_ping from 127\.0\.0\.1: hijacked connections are not supported",
    )


def test_proxy_relays_head_request_without_body(
    fake_upstream, make_config, start_proxy, fetch, caplog
):
    # given
    base_url = start_proxy(make_config())
    # when
    status, headers, body = fetch(base_url, "HEAD", "/_ping")
    # then
    assert status == 200
    assert body == b""
    assert headers["Content-Length"] == "17"
    assert fake_upstream.requests[0]["method"] == "HEAD"
    _assert_log(
        caplog,
        r"allowed HEAD /_ping from 127\.0\.0\.1 via ALLOW_PING -> 200 in \d+\.\d+ ms",
    )


def test_proxy_strips_hop_by_hop_request_headers(
    fake_upstream, make_config, start_proxy, fetch
):
    # given
    base_url = start_proxy(make_config())
    headers = {
        "X-Custom": "hello",
        "Proxy-Authorization": "secret",
        "Keep-Alive": "timeout=5",
    }
    # when
    status, headers, _body = fetch(base_url, "GET", "/_ping", headers=headers)
    # then
    assert status == 200
    forwarded = fake_upstream.requests[0]["headers"]
    assert forwarded["X-Custom"] == "hello"
    assert "Proxy-Authorization" not in forwarded
    assert "Keep-Alive" not in forwarded


def test_proxy_strips_hop_by_hop_response_headers(
    fake_upstream, make_config, start_proxy, fetch
):
    # given
    fake_upstream.extra_headers = {
        "Keep-Alive": "timeout=5",
        "X-Response-Custom": "yes",
    }
    base_url = start_proxy(make_config())
    # when
    status, headers, _body = fetch(base_url, "GET", "/_ping")
    # then
    assert status == 200
    assert "Keep-Alive" not in headers
    assert headers["X-Response-Custom"] == "yes"
    assert headers["Server"] == "container-socket-proxy"
