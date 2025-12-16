"""Coverage for the require_tools helper."""

from __future__ import annotations

import subprocess
from typing import Iterable

import pytest

import tests.conftest as conftest


def test_require_tools_installs_missing_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing tools should trigger a best-effort apt install before skipping."""

    installed: set[str] = set()

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        if tool == "apt-get":
            return "/usr/bin/apt-get"
        if tool in installed:
            return f"/usr/bin/{tool}"
        return None

    commands: list[list[str]] = []

    def fake_run(cmd: Iterable[str], *args, **kwargs) -> subprocess.CompletedProcess[str]:
        command_list = list(cmd)
        commands.append(command_list)
        if command_list[:2] == ["/usr/bin/apt-get", "update"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if command_list[:2] == ["/usr/bin/apt-get", "install"]:
            installed.add("ip")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "missing")

    monkeypatch.setattr(conftest.shutil, "which", fake_which)
    monkeypatch.setattr(conftest.subprocess, "run", fake_run)

    try:
        conftest.require_tools(["ip"])
    except pytest.skip.Exception as exc:  # pragma: no cover - explicit failure path
        pytest.fail(f"require_tools unexpectedly skipped: {exc.msg}")

    assert ["/usr/bin/apt-get", "update"] in commands
    assert any("iproute2" in cmd for cmd in commands if cmd[:2] == ["/usr/bin/apt-get", "install"])


def test_require_tools_skips_when_installation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip gracefully when dependencies remain unavailable after installation attempts."""

    def always_missing(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        if tool == "apt-get":
            return "/usr/bin/apt-get"
        return None

    def failing_run(cmd: Iterable[str], *args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "failed")

    monkeypatch.setattr(conftest.shutil, "which", always_missing)
    monkeypatch.setattr(conftest.subprocess, "run", failing_run)

    with pytest.raises(pytest.skip.Exception):
        conftest.require_tools(["unshare", "ip"])


def test_require_tools_fails_in_ci_when_tools_remain_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing tools should fail fast in CI instead of silently skipping."""

    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(conftest, "_install_missing_tools", lambda missing: [])

    def fake_which(tool: str) -> str | None:
        return "/usr/bin/apt-get" if tool == "apt-get" else None

    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    with pytest.raises(pytest.fail.Exception) as excinfo:
        conftest.require_tools(["ip", "ping"])

    assert "Required tools not available" in str(excinfo.value)
