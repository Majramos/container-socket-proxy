import pytest

from container_socket_proxy import rules


def _toggles(**overrides):
    resolved = {section.toggle: section.default for section in rules.SECTIONS}
    resolved["ALLOW_WRITE"] = False
    resolved.update(overrides)
    return resolved


@pytest.mark.parametrize(
    ("path", "toggle"),
    [
        ("/_ping", "ALLOW_PING"),
        ("/libpod/_ping", "ALLOW_PING"),
        ("/v1.40/libpod/_ping", "ALLOW_PING"),
        ("/version", "ALLOW_VERSION"),
        ("/v1.42/version", "ALLOW_VERSION"),
        ("/libpod/version", "ALLOW_VERSION"),
        ("/info", "ALLOW_INFO"),
        ("/v1.42/info", "ALLOW_INFO"),
        ("/system/info", "ALLOW_INFO"),
        ("/libpod/info", "ALLOW_INFO"),
        ("/containers/foo/exec", "ALLOW_EXEC"),
        ("/v1.40/exec/abc", "ALLOW_EXEC"),
        ("/libpod/containers/foo/exec", "ALLOW_EXEC"),
        ("/containers/foo/archive", "ALLOW_ARCHIVE"),
        ("/libpod/containers/foo/archive", "ALLOW_ARCHIVE"),
        ("/build", "ALLOW_BUILD"),
        ("/v1.0/build", "ALLOW_BUILD"),
        ("/events", "ALLOW_EVENTS"),
        ("/containers/json", "ALLOW_CONTAINERS"),
        ("/containers", "ALLOW_CONTAINERS"),
        ("/v1.42/containers/create", "ALLOW_CONTAINERS"),
        ("/libpod/containers/foo/stats", "ALLOW_CONTAINERS"),
        ("/containers/foo/archive/extra", "ALLOW_CONTAINERS"),
        ("/images/json", "ALLOW_IMAGES"),
        ("/v1.42/images", "ALLOW_IMAGES"),
        ("/volumes", "ALLOW_VOLUMES"),
        ("/networks/create", "ALLOW_NETWORKS"),
        ("/libpod/pods", "ALLOW_PODS"),
        ("/libpod/pods/list", "ALLOW_PODS"),
        ("/system/df", "ALLOW_SYSTEM"),
        ("/auth", "ALLOW_SYSTEM"),
        ("/v1.42/system/prune", "ALLOW_SYSTEM"),
        ("/foo", None),
        ("/_pingx", None),
        ("/pods/json", None),
        ("/v1.42/pods", None),
    ],
)
def test_match_section_resolves_path_to_toggle(path, toggle):
    # given
    section = rules.match_section(path)
    # when / then
    assert (section.toggle if section else None) == toggle


def test_decide_get_ping_with_default_toggles_is_allowed():
    # given
    toggles = _toggles()
    # when
    decision = rules.decide("GET", "/_ping", toggles)
    # then
    assert decision.allowed
    assert decision.section == "ALLOW_PING"
    assert decision.reason == ""


def test_decide_path_with_disabled_toggle_is_denied_with_reason():
    # given
    toggles = _toggles()
    # when
    decision = rules.decide("GET", "/containers/json", toggles)
    # then
    assert not decision.allowed
    assert decision.section == "ALLOW_CONTAINERS"
    assert decision.reason == "ALLOW_CONTAINERS is not enabled"


def test_decide_unmatched_path_is_denied_without_section():
    # given
    toggles = _toggles(ALLOW_CONTAINERS=1)
    # when
    decision = rules.decide("GET", "/foo", toggles)
    # then
    assert not decision.allowed
    assert decision.section == ""
    assert decision.reason == "no enabled endpoint group matches this path"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_decide_write_method_without_allow_write_is_denied(method):
    # given
    toggles = _toggles(ALLOW_CONTAINERS=1)
    # when
    decision = rules.decide(method, "/containers/create", toggles)
    # then
    assert not decision.allowed
    assert decision.section == "ALLOW_CONTAINERS"
    assert decision.reason == f"method {method} requires ALLOW_WRITE"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_decide_write_method_with_allow_write_is_allowed(method):
    # given
    toggles = _toggles(ALLOW_CONTAINERS=1, ALLOW_WRITE=1)
    # when
    decision = rules.decide(method, "/containers/create", toggles)
    # then
    assert decision.allowed
    assert decision.section == "ALLOW_CONTAINERS"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_decide_read_method_does_not_require_allow_write(method):
    # given
    toggles = _toggles(ALLOW_CONTAINERS=1)
    # when
    decision = rules.decide(method, "/containers/json", toggles)
    # then
    assert decision.allowed
    assert decision.section == "ALLOW_CONTAINERS"


def test_decide_query_string_is_ignored():
    # given
    toggles = _toggles(ALLOW_CONTAINERS=1)
    # when
    decision = rules.decide("GET", "/containers/json?all=1&limit=50", toggles)
    # then
    assert decision.allowed
    assert decision.section == "ALLOW_CONTAINERS"


def test_decide_query_string_with_disabled_toggle_is_denied():
    # given
    toggles = _toggles()
    # when
    decision = rules.decide("GET", "/containers/json?all=1", toggles)
    # then
    assert not decision.allowed
    assert decision.reason == "ALLOW_CONTAINERS is not enabled"


def test_decide_archive_path_matches_archive_section_before_containers():
    # given
    toggles = _toggles(**{section.toggle: True for section in rules.SECTIONS})
    # when
    decision = rules.decide("GET", "/containers/foo/archive", toggles)
    # then
    assert decision.allowed
    assert decision.section == "ALLOW_ARCHIVE"


def test_decide_pods_paths_only_match_under_libpod():
    # given
    toggles = _toggles(ALLOW_PODS=1)
    # when
    under_libpod = rules.decide("GET", "/libpod/pods/json", toggles)
    bare = rules.decide("GET", "/pods/json", toggles)
    # then
    assert under_libpod.allowed
    assert under_libpod.section == "ALLOW_PODS"
    assert not bare.allowed
    assert bare.reason == "no enabled endpoint group matches this path"
