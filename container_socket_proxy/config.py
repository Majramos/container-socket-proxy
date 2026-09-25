import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from container_socket_proxy import rules, upstream

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "WARN", "INFO", "DEBUG"})
DEFAULT_UPSTREAM_TIMEOUT = 10.0


@dataclass(frozen=True)
class ProxyConfig:
    host: str
    port: int
    socket: str
    log_level: str
    max_body_bytes: int
    upstream_timeout: float
    toggles: MappingProxyType[str, bool]


def _bool_value(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in TRUE_VALUES


def _int_value(raw: str | None, name: str, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {raw!r}") from None


def _float_value(raw: str | None, name: str, default: float) -> float:
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got: {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got: {raw!r}")
    return value


def load_config(env: Mapping[str, str] | None = None) -> ProxyConfig:
    source: Mapping[str, str] = os.environ if env is None else env

    toggles = {
        section.toggle: _bool_value(source.get(section.toggle), section.default)
        for section in rules.SECTIONS
    }

    toggles[rules.ALLOW_WRITE] = _bool_value(source.get(rules.ALLOW_WRITE), False)

    port = _int_value(source.get("PROXY_PORT"), "PROXY_PORT", 2026)
    if not 1 <= port <= 65535:
        raise ValueError(f"PROXY_PORT must be between 1 and 65535, got: {port}")

    max_body_bytes = _int_value(source.get("MAX_BODY_BYTES"), "MAX_BODY_BYTES", 0)
    if max_body_bytes < 0:
        raise ValueError(f"MAX_BODY_BYTES must be >= 0, got: {max_body_bytes}")

    upstream_timeout = _float_value(
        source.get("UPSTREAM_TIMEOUT"),
        "UPSTREAM_TIMEOUT",
        DEFAULT_UPSTREAM_TIMEOUT,
    )
    if upstream_timeout < 0:
        raise ValueError(f"UPSTREAM_TIMEOUT must be >= 0, got: {upstream_timeout}")

    log_level = source.get("LOG_LEVEL", "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ValueError(
            f"LOG_LEVEL must be one of {', '.join(sorted(LOG_LEVELS))}; "
            f"got: {log_level!r}"
        )

    socket = source.get("CONTAINER_SOCKET") or source.get("DOCKER_SOCKET") or ""
    if not socket:
        socket = "/run/podman/podman.sock"

    upstream.validate_target(socket)

    return ProxyConfig(
        host=source.get("PROXY_HOST") or "0.0.0.0",
        port=port,
        socket=socket,
        log_level=log_level,
        max_body_bytes=max_body_bytes,
        upstream_timeout=upstream_timeout,
        toggles=MappingProxyType(toggles),
    )
