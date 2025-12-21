"""Coverage for the k3s discover namespace connectivity fallback and flaky skips."""

from __future__ import annotations

import subprocess

import pytest

from tests.helpers.netns_probe import NamespaceProbeResult
from tests.test_k3s_discover_failopen_e2e import _verify_namespace_connectivity


def test_verify_namespace_connectivity_uses_tcp_probe_when_ping_fails() -> None:
    """Fallback TCP probe should avoid flaky skips when ICMP is blocked."""

    commands: list[list[str]] = []

    def failing_ping(cmd: list[str], *_, **__) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    probe_calls: list[tuple[str, str, str, dict]] = []

    def successful_probe(
        leader_ns: str, follower_ns: str, follower_ip: str, **kwargs
    ) -> NamespaceProbeResult:
        probe_calls.append((leader_ns, follower_ns, follower_ip, kwargs))
        return NamespaceProbeResult(ok=True, attempts=1)

    try:
        _verify_namespace_connectivity(
            "leader", "follower", "192.0.2.10", run_cmd=failing_ping, probe=successful_probe
        )
    except pytest.skip.Exception as exc:
        pytest.fail(f"Connectivity verification unexpectedly skipped: {exc}")

    assert commands
    assert "ping" in commands[0]
    assert commands[0][:4] == ["ip", "netns", "exec", "leader"]
    assert commands[0][-1] == "192.0.2.10"
    assert probe_calls
    assert probe_calls[0][:3] == ("leader", "follower", "192.0.2.10")
    assert probe_calls[0][3] == {"attempts": 3, "retry_delay": 0.5}


def test_verify_namespace_connectivity_surfaces_probe_errors() -> None:
    """Failures should include the TCP probe reason and errors in the skip message."""

    def failing_ping(cmd: list[str], *_, **__) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "")

    def failing_probe(
        leader_ns: str, follower_ns: str, follower_ip: str, **kwargs
    ) -> NamespaceProbeResult:
        return NamespaceProbeResult(
            ok=False,
            attempts=2,
            reason="probe failed",
            errors=["timeout", "bind error"],
        )

    with pytest.raises(pytest.skip.Exception) as excinfo:
        _verify_namespace_connectivity(
            "leader", "follower", "192.0.2.20", run_cmd=failing_ping, probe=failing_probe
        )

    message = str(excinfo.value)
    assert "probe failed" in message
    assert "timeout" in message
    assert "bind error" in message
