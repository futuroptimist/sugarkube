"""Ensure require_tools installs dependencies when permissions allow."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import tests.conftest as conftest


@pytest.mark.parametrize(
    "update_code, install_code",
    [
        (100, 0),
    ],
)
def test_install_missing_tools_falls_back_to_sudo(
    monkeypatch: pytest.MonkeyPatch, update_code: int, install_code: int
) -> None:
    """`_install_missing_tools` should retry with sudo when apt-get needs privileges."""

    commands: list[list[str]] = []

    def fake_run(cmd: list[str], capture_output: bool, text: bool, env: dict | None = None):
        commands.append(cmd)
        if cmd[0].endswith("apt-get") and cmd[1:] == ["update"]:
            return SimpleNamespace(returncode=update_code, stdout="", stderr="Permission denied")
        if cmd[0].endswith("sudo") and cmd[1:3] == ["/usr/bin/apt-get", "update"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0].endswith("sudo") and cmd[1:3] == ["/usr/bin/apt-get", "install"]:
            return SimpleNamespace(returncode=install_code, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(conftest.shutil, "which", lambda tool: "/usr/bin/" + tool)

    packages = conftest._install_missing_tools(["ip"])

    assert packages == ["iproute2"], "Installer should succeed when sudo is available"
    assert ["/usr/bin/sudo", "/usr/bin/apt-get", "update"] in commands
    assert [
        "/usr/bin/sudo",
        "/usr/bin/apt-get",
        "install",
        "--no-install-recommends",
        "-y",
        "iproute2",
    ] in commands
