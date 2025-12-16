"""Unit tests for the k3s discover namespace connectivity validation helper."""

from types import SimpleNamespace

import pytest

from tests.test_k3s_discover_failopen_e2e import _verify_namespace_connectivity


def test_verify_namespace_connectivity_prefers_tcp_probe() -> None:
    """TCP probe success should short-circuit without invoking ping."""

    calls: list[tuple[str, str, str]] = []

    def probe(client_ns: str, server_ns: str, server_ip: str) -> bool:  # noqa: ANN001 - signature matches probe_namespace_connectivity
        calls.append((client_ns, server_ns, server_ip))
        return True

    def ping_runner(client_ns: str, target_ip: str) -> SimpleNamespace:  # noqa: ANN001 - signature matches ping_runner
        raise AssertionError(
            f"ping should not run when TCP probe succeeds (got {client_ns} -> {target_ip})"
        )

    _verify_namespace_connectivity(
        "ns-leader", "ns-follower", "192.168.120.2", probe=probe, ping_runner=ping_runner
    )

    assert calls == [("ns-leader", "ns-follower", "192.168.120.2")]


def test_verify_namespace_connectivity_skips_when_checks_fail() -> None:
    """Failure of both TCP probe and ping should raise pytest.SkipException."""

    def probe(client_ns: str, server_ns: str, server_ip: str) -> bool:  # noqa: ANN001 - signature matches probe_namespace_connectivity
        return False

    def ping_runner(client_ns: str, target_ip: str) -> SimpleNamespace:  # noqa: ANN001 - signature matches ping_runner
        return SimpleNamespace(returncode=1)

    with pytest.raises(pytest.skip.Exception):
        _verify_namespace_connectivity(
            "ns-leader", "ns-follower", "192.168.120.2", probe=probe, ping_runner=ping_runner
        )
