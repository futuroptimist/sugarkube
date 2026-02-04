"""Coverage for the require_tools helper."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
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


def test_require_tools_shims_when_preinstall_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing tools should shim after failed installs when preinstall shims are enabled."""

    monkeypatch.delenv("SUGARKUBE_ALLOW_TOOL_SHIMS", raising=False)
    monkeypatch.delenv("SUGARKUBE_PREINSTALL_TOOL_SHIMS", raising=False)
    monkeypatch.setenv("SUGARKUBE_TOOL_SHIM_DIR", str(tmp_path))

    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", original_path)

    def fake_install(missing: Iterable[str]) -> list[str]:
        return []

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        candidate = tmp_path / tool
        if candidate.exists():
            return str(candidate)
        return None

    monkeypatch.setattr(conftest, "_install_missing_tools", fake_install)
    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    try:
        conftest.require_tools(["ip", "ping"])
    except pytest.skip.Exception as exc:  # pragma: no cover - explicit failure path
        pytest.fail(f"require_tools unexpectedly skipped: {exc.msg}")

    for tool in ("ip", "ping"):
        shimmed = tmp_path / tool
        assert shimmed.exists()
        assert os.access(shimmed, os.X_OK)

    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    assert str(tmp_path) in path_parts


def test_require_tools_falls_back_to_shims(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When allowed, missing tools are shimmed instead of skipped."""

    monkeypatch.setenv("SUGARKUBE_ALLOW_TOOL_SHIMS", "1")
    monkeypatch.setenv("SUGARKUBE_TOOL_SHIM_DIR", str(tmp_path))

    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", original_path)

    real_which = shutil.which

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        if tool in {"ip", "ping"}:
            candidate = tmp_path / tool
            return str(candidate) if candidate.exists() else None
        if tool == "apt-get":
            return None
        return real_which(tool, path=path)

    def failing_run(cmd: Iterable[str], *args, **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "failed")

    monkeypatch.setattr(conftest.shutil, "which", fake_which)
    monkeypatch.setattr(conftest.subprocess, "run", failing_run)

    try:
        conftest.require_tools(["ip", "ping"])

        for tool in ("ip", "ping"):
            shimmed = tmp_path / tool
            assert shimmed.exists()
            assert os.access(shimmed, os.X_OK)

        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        assert str(tmp_path) in path_parts
        assert path_parts.count(str(tmp_path)) == 1
    except pytest.skip.Exception as exc:  # pragma: no cover - explicit failure path
        pytest.fail(f"require_tools unexpectedly skipped: {exc.msg}")
    finally:
        os.environ["PATH"] = original_path

    assert os.environ.get("PATH", "") == original_path


def test_require_tools_prefers_shims_when_opted_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Opt-in shim mode should short-circuit installer calls."""

    monkeypatch.setenv("SUGARKUBE_ALLOW_TOOL_SHIMS", "1")
    monkeypatch.setenv("SUGARKUBE_TOOL_SHIM_DIR", str(tmp_path))

    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", original_path)

    def unexpected_install(missing: Iterable[str]) -> list[str]:
        raise AssertionError(f"_install_missing_tools should not run: {missing}")

    monkeypatch.setattr(conftest, "_install_missing_tools", unexpected_install)

    real_which = shutil.which

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        candidate = tmp_path / tool
        if candidate.exists():
            return str(candidate)
        if tool in {"ip", "ping"}:
            return None
        return real_which(tool, path=path)

    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    try:
        conftest.require_tools(["ip", "ping"])
    except pytest.skip.Exception as exc:  # pragma: no cover - explicit failure path
        pytest.fail(f"require_tools unexpectedly skipped: {exc.msg}")

    for tool in ("ip", "ping"):
        shimmed = tmp_path / tool
        assert shimmed.exists()
        assert os.access(shimmed, os.X_OK)

    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    assert str(tmp_path) in path_parts


def test_preinstall_test_cli_tools_installs_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preinstall helper should request all known CLI dependencies when missing."""

    recorded: list[list[str]] = []
    installed: set[str] = set()

    def fake_install(missing: Iterable[str]) -> list[str]:
        ordered = sorted(missing)
        recorded.append(ordered)
        installed.update(ordered)
        return ordered

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        if tool == "apt-get":
            return "/usr/bin/apt-get"
        if tool in installed:
            return f"/usr/bin/{tool}"
        return None

    monkeypatch.setattr(conftest, "_install_missing_tools", fake_install)
    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    installed = conftest.preinstall_test_cli_tools()

    assert recorded == [sorted(conftest.TEST_CLI_TOOLS)]
    assert installed == sorted(conftest.TEST_CLI_TOOLS)


def test_preinstall_test_cli_tools_noops_when_tools_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preinstall helper should skip work when dependencies already exist."""

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        return f"/usr/bin/{tool}"

    def fake_install(missing: Iterable[str]) -> list[str]:
        raise AssertionError(f"Unexpected install attempt for: {missing}")

    monkeypatch.setattr(conftest.shutil, "which", fake_which)
    monkeypatch.setattr(conftest, "_install_missing_tools", fake_install)

    assert conftest.preinstall_test_cli_tools() == []


def test_preinstall_test_cli_tools_shims_when_installs_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Preinstall helper should fall back to shims when installers are unavailable."""

    monkeypatch.setattr(conftest, "_TOOL_SHIM_DIR", None)
    monkeypatch.setenv("SUGARKUBE_TOOL_SHIM_DIR", str(tmp_path))
    monkeypatch.delenv("SUGARKUBE_PREINSTALL_TOOL_SHIMS", raising=False)

    original_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", original_path)

    def fake_install(missing: Iterable[str]) -> list[str]:
        return []

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        candidate = tmp_path / tool
        if candidate.exists():
            return str(candidate)
        return None

    monkeypatch.setattr(conftest, "_install_missing_tools", fake_install)
    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    shimmed = conftest.preinstall_test_cli_tools()

    assert shimmed == sorted(conftest.TEST_CLI_TOOLS)
    for tool in conftest.TEST_CLI_TOOLS:
        shimmed_path = tmp_path / tool
        assert shimmed_path.exists()
        assert os.access(shimmed_path, os.X_OK)

    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    assert str(tmp_path) in path_parts
    assert path_parts.count(str(tmp_path)) == 1


def test_preinstall_test_cli_tools_shim_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shim fallback should be disabled when explicitly requested."""

    shim_attempts: list[Iterable[str]] = []

    def fake_install(missing: Iterable[str]) -> list[str]:
        return []

    def record_shim_attempt(missing: Iterable[str]) -> Path:
        shim_attempts.append(list(missing))
        return Path("ignored")

    def fake_which(tool: str, path: str | None = None) -> str | None:  # type: ignore[override]
        return None

    monkeypatch.setenv("SUGARKUBE_PREINSTALL_TOOL_SHIMS", "0")
    monkeypatch.setattr(conftest, "_install_missing_tools", fake_install)
    monkeypatch.setattr(conftest, "_create_tool_shims", record_shim_attempt)
    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    assert conftest.preinstall_test_cli_tools() == []
    assert shim_attempts == []


def test_ensure_test_cli_tools_preinstalled_respects_skip_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session fixture should honor opt-out flag to avoid installs in CI."""

    monkeypatch.setenv("SUGARKUBE_SKIP_PREINSTALL_TOOLS", "1")

    def unexpected_preinstall_attempt() -> None:
        raise AssertionError("Preinstall should be skipped when opt-out is set")

    monkeypatch.setattr(conftest, "preinstall_test_cli_tools", unexpected_preinstall_attempt)

    conftest.ensure_test_cli_tools_preinstalled_if_allowed()
