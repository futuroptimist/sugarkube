"""Coverage for the network-namespace stub opt-in."""

from __future__ import annotations

import subprocess

import pytest

import tests.test_mdns_ready_e2e as mdns_ready
from tests.helpers import netns_stub


def test_netns_stub_flag_enables_stubbed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opting into stub mode should bypass privileged netns calls."""

    monkeypatch.setenv("SUGARKUBE_ALLOW_NETNS_STUBS", "1")

    called: list[list[str]] = []

    def fail_if_called(cmd: list[str]) -> None:  # pragma: no cover - explicit failure path
        called.append(cmd)
        raise AssertionError(f"Unexpected command execution: {cmd}")

    monkeypatch.setattr(mdns_ready, "_run_with_sudo_fallback", fail_if_called)

    fixture = mdns_ready.iter_netns_setup()
    stubbed = next(fixture)

    assert stubbed["stubbed"] is True
    assert stubbed["ip1"].startswith("192.0.2.")
    assert called == []

    with pytest.raises(StopIteration):
        next(fixture)


def test_netns_stub_helpers_are_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helpers should be pure and depend solely on the environment variable."""

    monkeypatch.delenv("SUGARKUBE_ALLOW_NETNS_STUBS", raising=False)
    assert netns_stub.should_stub_netns_setup() is False
    assert netns_stub.netns_stub_mode() == "off"

    monkeypatch.setenv("SUGARKUBE_ALLOW_NETNS_STUBS", "1")
    assert netns_stub.should_stub_netns_setup() is True
    assert netns_stub.netns_stub_mode() == "force"

    monkeypatch.setenv("SUGARKUBE_ALLOW_NETNS_STUBS", "auto")
    assert netns_stub.should_stub_netns_setup() is False
    assert netns_stub.netns_stub_mode() == "auto"

    stubbed = netns_stub.stub_netns_environment()
    assert stubbed == netns_stub.stub_netns_environment()
    assert stubbed["stubbed"] is True


def test_netns_stub_auto_mode_falls_back_on_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto stub mode should yield stubbed namespaces when setup hits permission errors."""

    monkeypatch.setenv("SUGARKUBE_ALLOW_NETNS_STUBS", "auto")

    def no_op_tools(tools: list[str]) -> None:
        return

    def no_op_privileges() -> None:
        return

    calls: list[list[str]] = []

    def permission_denied(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "Permission denied")

    monkeypatch.setattr(mdns_ready, "require_tools", no_op_tools)
    monkeypatch.setattr(mdns_ready, "ensure_root_privileges", no_op_privileges)
    monkeypatch.setattr(mdns_ready, "_run_with_sudo_fallback", permission_denied)

    fixture = mdns_ready.iter_netns_setup()
    stubbed = next(fixture)

    assert stubbed["stubbed"] is True
    assert calls

    with pytest.raises(StopIteration):
        next(fixture)
