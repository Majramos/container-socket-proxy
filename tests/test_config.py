from types import MappingProxyType

import pytest

from container_socket_proxy.config import DEFAULT_UPSTREAM_TIMEOUT, load_config


def test_load_config_with_empty_env_returns_defaults():
    # given
    env = {}
    # when
    config = load_config(env)
    # then
    assert config.host == "0.0.0.0"
    assert config.port == 2026
    assert config.socket == "/run/podman/podman.sock"
    assert config.log_level == "INFO"
    assert config.max_body_bytes == 0
    assert config.upstream_timeout == DEFAULT_UPSTREAM_TIMEOUT
    assert config.toggles["ALLOW_PING"] is True
    assert config.toggles["ALLOW_WRITE"] is False
    assert config.toggles["ALLOW_CONTAINERS"] is False
    assert config.toggles["ALLOW_IMAGES"] is False


def test_load_config_reads_os_environ_when_env_is_none(monkeypatch):
    # given
    monkeypatch.setenv("PROXY_PORT", "31337")
    monkeypatch.delenv("ALLOW_PING", raising=False)
    # when
    config = load_config()
    # then
    assert config.port == 31337
    assert config.toggles["ALLOW_PING"] is True


def test_load_config_returns_immutable_toggles():
    # given
    env = {}
    # when
    config = load_config(env)
    # then
    assert isinstance(config.toggles, MappingProxyType)


def test_load_config_reads_host_and_socket_overrides():
    # given
    env = {"PROXY_HOST": "127.0.0.1", "CONTAINER_SOCKET": "tcp://podman.internal:8080"}
    # when
    config = load_config(env)
    # then
    assert config.host == "127.0.0.1"
    assert config.socket == "tcp://podman.internal:8080"


def test_load_config_prefers_container_socket_over_docker_socket():
    # given
    env = {
        "CONTAINER_SOCKET": "/run/podman/podman.sock",
        "DOCKER_SOCKET": "/var/run/docker.sock",
    }
    # when
    config = load_config(env)
    # then
    assert config.socket == "/run/podman/podman.sock"


def test_load_config_reads_docker_socket():
    # given
    env = {"DOCKER_SOCKET": "/var/run/docker.sock"}
    # when
    config = load_config(env)
    # then
    assert config.socket == "/var/run/docker.sock"


def test_load_config_treats_empty_socket_values_as_unset():
    # given
    env = {"CONTAINER_SOCKET": "", "DOCKER_SOCKET": ""}
    # when
    config = load_config(env)
    # then
    assert config.socket == "/run/podman/podman.sock"


def test_load_config_rejects_unknown_socket_scheme():
    # given
    env = {"CONTAINER_SOCKET": "foo://bar"}
    # when / then
    with pytest.raises(ValueError, match="unsupported upstream scheme"):
        load_config(env)


def test_load_config_rejects_socket_url_without_host():
    # given
    env = {"CONTAINER_SOCKET": "tcp://:8080"}
    # when / then
    with pytest.raises(ValueError, match="no host"):
        load_config(env)


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", "ON"])
def test_load_config_accepts_truthy_toggle_values(raw):
    # given
    env = {"ALLOW_CONTAINERS": raw, "ALLOW_WRITE": raw}
    # when
    config = load_config(env)
    # then
    assert config.toggles["ALLOW_CONTAINERS"] is True
    assert config.toggles["ALLOW_WRITE"] is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "maybe", "2"])
def test_load_config_treats_other_toggle_values_as_false(raw):
    # given
    env = {"ALLOW_PING": raw}
    # when
    config = load_config(env)
    # then
    assert config.toggles["ALLOW_PING"] is False


def test_load_config_treats_empty_toggle_value_as_default():
    # given
    env = {"ALLOW_PING": "", "ALLOW_CONTAINERS": ""}
    # when
    config = load_config(env)
    # then
    assert config.toggles["ALLOW_PING"] is True
    assert config.toggles["ALLOW_CONTAINERS"] is False


def test_load_config_accepts_valid_port_range():
    # given
    # when
    lowest = load_config({"PROXY_PORT": "1"})
    highest = load_config({"PROXY_PORT": "65535"})
    # then
    assert lowest.port == 1
    assert highest.port == 65535


@pytest.mark.parametrize("raw", ["0", "-1", "65536", "abc"])
def test_load_config_rejects_invalid_port(raw):
    # given
    env = {"PROXY_PORT": raw}
    # when / then
    with pytest.raises(ValueError, match="PROXY_PORT"):
        load_config(env)


def test_load_config_accepts_max_body_bytes():
    # given
    env = {"MAX_BODY_BYTES": "1024"}
    # when
    config = load_config(env)
    # then
    assert config.max_body_bytes == 1024


def test_load_config_rejects_negative_max_body_bytes():
    # given
    env = {"MAX_BODY_BYTES": "-5"}
    # when / then
    with pytest.raises(ValueError, match="MAX_BODY_BYTES must be >= 0"):
        load_config(env)


def test_load_config_accepts_upstream_timeout_number():
    # given
    env = {"UPSTREAM_TIMEOUT": "2.5"}
    # when
    config = load_config(env)
    # then
    assert config.upstream_timeout == 2.5


@pytest.mark.parametrize("raw", ["abc", "nan", "inf", "-1"])
def test_load_config_rejects_invalid_upstream_timeout(raw):
    # given
    env = {"UPSTREAM_TIMEOUT": raw}
    # when / then
    with pytest.raises(ValueError, match="UPSTREAM_TIMEOUT"):
        load_config(env)


def test_load_config_uppercases_log_level():
    # given
    env = {"LOG_LEVEL": "debug"}
    # when
    config = load_config(env)
    # then
    assert config.log_level == "DEBUG"


def test_load_config_rejects_unknown_log_level():
    # given
    env = {"LOG_LEVEL": "bogus"}
    # when / then
    with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
        load_config(env)
