"""Coverage for the ensure_root_privileges helper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import tests.conftest as conftest


def test_ensure_root_privileges_retries_with_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback to sudo should prevent skips when direct commands lack permissions."""

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd == ["unshare", "-n", "true"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        if cmd == ["sudo", "unshare", "-n", "true"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["ip", "netns", "add"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        if cmd[:4] == ["sudo", "ip", "netns", "add"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["ip", "netns", "delete"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        if cmd[:4] == ["sudo", "ip", "netns", "delete"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)
    monkeypatch.setattr(
        conftest.shutil,
        "which",
        lambda tool: "/usr/bin/sudo" if tool == "sudo" else f"/usr/bin/{tool}",
    )
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: SimpleNamespace(hex="stubbed"))

    conftest.ensure_root_privileges()

    assert ["unshare", "-n", "true"] in commands
    assert ["/usr/bin/sudo", "unshare", "-n", "true"] in commands
    assert ["ip", "netns", "add", "sugarkube-netns-probe-stubbed"] in commands
    assert ["/usr/bin/sudo", "ip", "netns", "add", "sugarkube-netns-probe-stubbed"] in commands
    assert ["ip", "netns", "delete", "sugarkube-netns-probe-stubbed"] in commands
    assert ["/usr/bin/sudo", "ip", "netns", "delete", "sugarkube-netns-probe-stubbed"] in commands


def test_ensure_root_privileges_skips_when_sudo_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip when both direct and sudo attempts cannot set up network namespaces."""

    commands: list[list[str]] = []

    def failing_run(cmd: list[str], capture_output: bool, text: bool):
        commands.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")

    monkeypatch.setattr(conftest.subprocess, "run", failing_run)
    monkeypatch.setattr(conftest.shutil, "which", lambda tool: "/usr/bin/sudo")
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: SimpleNamespace(hex="stubbed"))

    with pytest.raises(pytest.skip.Exception):
        conftest.ensure_root_privileges()

    assert ["unshare", "-n", "true"] in commands
    assert ["/usr/bin/sudo", "unshare", "-n", "true"] in commands
