"""Coverage for the ensure_root_privileges helper."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Callable, Iterable

import pytest

import tests.conftest as conftest


def _build_fake_run(
    sudo_path: str | None,
    permission_failures: Iterable[list[str]],
    sudo_successes: Iterable[list[str]],
    cleanup_failure: bool = False,
) -> Callable[[list[str], bool, bool], SimpleNamespace]:
    commands: list[list[str]] = []

    def _matches(cmd: list[str], patterns: Iterable[list[str]]) -> bool:
        return any(cmd[: len(pattern)] == pattern for pattern in patterns)

    def fake_run(cmd: list[str], capture_output: bool, text: bool) -> SimpleNamespace:
        commands.append(cmd)
        sudo_cmds = [[sudo_path, "-n", *pattern] for pattern in permission_failures] if sudo_path else []
        if _matches(cmd, permission_failures):
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        if _matches(cmd, sudo_cmds):
            if _matches(cmd, sudo_successes):
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        if cleanup_failure and cmd[-2:] == ["netns", "delete"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_run.commands = commands  # type: ignore[attr-defined]
    return fake_run


def test_ensure_root_privileges_retries_with_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback to sudo should prevent skips when direct commands lack permissions."""

    fake_run = _build_fake_run(
        sudo_path="/usr/bin/sudo",
        permission_failures=[["unshare", "-n", "true"], ["ip", "netns", "add"], ["ip", "netns", "delete"]],
        sudo_successes=[["/usr/bin/sudo", "-n", "unshare", "-n", "true"], ["/usr/bin/sudo", "-n", "ip", "netns", "add"], ["/usr/bin/sudo", "-n", "ip", "netns", "delete"]],
    )

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)
    monkeypatch.setattr(
        conftest.shutil,
        "which",
        lambda tool: "/usr/bin/sudo" if tool == "sudo" else f"/usr/bin/{tool}",
    )
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: SimpleNamespace(hex="stubbed"))

    conftest.ensure_root_privileges()

    expected_netns = "sugarkube-netns-probe-stubbed"
    assert ["unshare", "-n", "true"] in fake_run.commands
    assert ["/usr/bin/sudo", "-n", "unshare", "-n", "true"] in fake_run.commands
    assert ["ip", "netns", "add", expected_netns] in fake_run.commands
    assert ["/usr/bin/sudo", "-n", "ip", "netns", "add", expected_netns] in fake_run.commands
    assert ["ip", "netns", "delete", expected_netns] in fake_run.commands
    assert ["/usr/bin/sudo", "-n", "ip", "netns", "delete", expected_netns] in fake_run.commands


def test_ensure_root_privileges_skips_when_sudo_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip when both direct and sudo attempts cannot set up network namespaces."""

    fake_run = _build_fake_run(
        sudo_path="/usr/bin/sudo",
        permission_failures=[["unshare", "-n", "true"], ["ip", "netns", "add"], ["ip", "netns", "delete"]],
        sudo_successes=[],
    )

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)
    monkeypatch.setattr(conftest.shutil, "which", lambda tool: "/usr/bin/sudo")
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: SimpleNamespace(hex="stubbed"))

    with pytest.raises(pytest.skip.Exception):
        conftest.ensure_root_privileges()

    assert ["unshare", "-n", "true"] in fake_run.commands
    assert ["/usr/bin/sudo", "-n", "unshare", "-n", "true"] in fake_run.commands


def test_ensure_root_privileges_skips_when_sudo_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not retry with sudo when it cannot be located."""

    fake_run = _build_fake_run(
        sudo_path=None,
        permission_failures=[["unshare", "-n", "true"]],
        sudo_successes=[],
    )

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)
    monkeypatch.setattr(conftest.shutil, "which", lambda tool: None)
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: SimpleNamespace(hex="stubbed"))

    with pytest.raises(pytest.skip.Exception) as excinfo:
        conftest.ensure_root_privileges()

    assert ["unshare", "-n", "true"] in fake_run.commands
    assert all(cmd[0] != "/usr/bin/sudo" for cmd in fake_run.commands)
    assert "sudo not available for retry" in str(excinfo.value)


def test_ensure_root_privileges_warns_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Surface a warning when cleanup cannot delete the probe namespace."""

    fake_run = _build_fake_run(
        sudo_path="/usr/bin/sudo",
        permission_failures=[["ip", "netns", "delete"]],
        sudo_successes=[],
        cleanup_failure=True,
    )

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)
    monkeypatch.setattr(conftest.shutil, "which", lambda tool: "/usr/bin/sudo")
    monkeypatch.setattr(conftest.uuid, "uuid4", lambda: SimpleNamespace(hex="stubbed"))

    with pytest.warns(RuntimeWarning, match="permission denied"):
        conftest.ensure_root_privileges()
