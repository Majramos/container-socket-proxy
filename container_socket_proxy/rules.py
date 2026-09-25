import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    section: str
    reason: str


@dataclass(frozen=True)
class Section:
    toggle: str
    default: bool
    patterns: tuple[re.Pattern[str], ...]


def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


VERSIONED = r"(?:/v[0-9.]+)?"
LIBPOD = r"(?:/v[0-9.]+)?/libpod"

SECTIONS: tuple[Section, ...] = (
    Section("ALLOW_PING", True, _compile((r"/_ping", rf"{LIBPOD}/_ping"))),
    Section(
        "ALLOW_VERSION",
        False,
        _compile(
            (
                rf"{VERSIONED}/version",
                rf"{LIBPOD}/version",
            )
        ),
    ),
    Section(
        "ALLOW_INFO",
        False,
        _compile(
            (
                rf"{VERSIONED}/info",
                rf"{VERSIONED}/system/info",
                rf"{LIBPOD}/info",
            )
        ),
    ),
    Section(
        "ALLOW_EXEC",
        False,
        _compile(
            (
                rf"{VERSIONED}/containers/[^/]+/exec",
                rf"{VERSIONED}/exec(?:/.*)?",
                rf"{LIBPOD}/exec(?:/.*)?",
                rf"{LIBPOD}/containers/[^/]+/exec",
            )
        ),
    ),
    Section(
        "ALLOW_ARCHIVE",
        False,
        _compile(
            (
                rf"{VERSIONED}/containers/[^/]+/archive",
                rf"{LIBPOD}/containers/[^/]+/archive",
            )
        ),
    ),
    Section(
        "ALLOW_BUILD",
        False,
        _compile(
            (
                rf"{VERSIONED}/build",
                rf"{LIBPOD}/build",
            )
        ),
    ),
    Section(
        "ALLOW_EVENTS",
        False,
        _compile(
            (
                rf"{VERSIONED}/events",
                rf"{LIBPOD}/events",
            )
        ),
    ),
    Section(
        "ALLOW_CONTAINERS",
        False,
        _compile(
            (
                rf"{VERSIONED}/containers(?:/.*)?",
                rf"{LIBPOD}/containers(?:/.*)?",
            )
        ),
    ),
    Section(
        "ALLOW_IMAGES",
        False,
        _compile(
            (
                rf"{VERSIONED}/images(?:/.*)?",
                rf"{LIBPOD}/images(?:/.*)?",
            )
        ),
    ),
    Section(
        "ALLOW_VOLUMES",
        False,
        _compile(
            (
                rf"{VERSIONED}/volumes(?:/.*)?",
                rf"{LIBPOD}/volumes(?:/.*)?",
            )
        ),
    ),
    Section(
        "ALLOW_NETWORKS",
        False,
        _compile(
            (
                rf"{VERSIONED}/networks(?:/.*)?",
                rf"{LIBPOD}/networks(?:/.*)?",
            )
        ),
    ),
    Section(
        "ALLOW_PODS",
        False,
        _compile((rf"{LIBPOD}/pods(?:/.*)?",)),
    ),
    Section(
        "ALLOW_SYSTEM",
        False,
        _compile(
            (
                rf"{VERSIONED}/system(?:/.*)?",
                rf"{VERSIONED}/auth",
                rf"{LIBPOD}/system(?:/.*)?",
            )
        ),
    ),
)


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALLOW_WRITE = "ALLOW_WRITE"


def match_section(path: str) -> Section | None:
    for section in SECTIONS:
        for pattern in section.patterns:
            if pattern.fullmatch(path):
                return section
    return None


def decide(
    method: str,
    raw_path: str,
    toggles: Mapping[str, bool],
) -> Decision:
    path = raw_path.partition("?")[0]
    section = match_section(path)

    if section is None:
        return Decision(False, "", "no enabled endpoint group matches this path")

    if not toggles.get(section.toggle, False):
        return Decision(False, section.toggle, f"{section.toggle} is not enabled")

    if method in WRITE_METHODS and not toggles.get(ALLOW_WRITE, False):
        return Decision(
            False,
            section.toggle,
            f"method {method} requires {ALLOW_WRITE}",
        )

    return Decision(True, section.toggle, "")
