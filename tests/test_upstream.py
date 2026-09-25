import time

import pytest

from container_socket_proxy import upstream


def test_open_upstream_rejects_unknown_scheme():
    # given
    target = "foo://bar"
    # when / then
    with pytest.raises(ValueError, match="unsupported upstream scheme"):
        upstream.open_upstream(target, 1.0)


def test_unix_connection_keeps_timeout_after_connect(unix_upstream):
    # given
    conn = upstream.UnixHTTPConnection(str(unix_upstream.server_address), timeout=0.5)
    try:
        # when
        conn.connect()
        # then
        assert conn.sock is not None
        assert conn.sock.gettimeout() == 0.5
    finally:
        conn.close()


def test_proxy_relays_request_over_unix_socket(
    unix_upstream, make_config, start_proxy, fetch
):
    # given
    base_url = start_proxy(
        make_config(socket_url=f"unix://{unix_upstream.server_address}")
    )
    # when
    status, _headers, body = fetch(base_url, "GET", "/_ping")
    # then
    assert status == 200
    assert body == b'{"upstream":"ok"}'
    assert unix_upstream.requests[0]["method"] == "GET"
    assert unix_upstream.requests[0]["path"] == "/_ping"


def test_proxy_returns_502_when_unix_upstream_hangs_on_headers(
    hanging_unix_upstream, make_config, start_proxy, fetch
):
    # given
    base_url = start_proxy(
        make_config(
            socket_url=f"unix://{hanging_unix_upstream.server_address}",
            upstream_timeout=0.5,
        )
    )
    # when
    started = time.monotonic()
    status, _headers, body = fetch(base_url, "GET", "/_ping")
    elapsed = time.monotonic() - started
    # then
    assert status == 502
    assert body.startswith(b"container socket unreachable:")
    assert elapsed < 5.0
