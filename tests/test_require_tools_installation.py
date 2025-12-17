"""Ensure require_tools installs dependencies when permissions allow."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

import tests.conftest as conftest


@pytest.mark.parametrize(
    "scenario",
    [
        {
            "name": "sudo_needed_for_update_and_install",
            "update_code": 100,
            "install_code": 100,
            "sudo_update_code": 0,
            "sudo_install_code": 0,
            "sudo_available": True,
            "expected_packages": ["iproute2"],
            "expected_commands": [
                ["/usr/bin/apt-get", "update"],
                ["/usr/bin/sudo", "/usr/bin/apt-get", "update"],
                [
                    "/usr/bin/sudo",
                    "/usr/bin/apt-get",
                    "install",
                    "--no-install-recommends",
                    "-y",
                    "iproute2",
                ],
            ],
            "absent_commands": [
                [
                    "/usr/bin/apt-get",
                    "install",
                    "--no-install-recommends",
                    "-y",
                    "iproute2",
                ]
            ],
        },
        {
            "name": "sudo_unavailable_after_permission_error",
            "update_code": 100,
            "install_code": 100,
            "sudo_update_code": 1,
            "sudo_install_code": 1,
            "sudo_available": False,
            "expected_packages": [],
            "expected_commands": [
                ["/usr/bin/apt-get", "update"],
            ],
            "absent_commands": [
                ["/usr/bin/apt-get", "install", "--no-install-recommends", "-y", "iproute2"],
                ["/usr/bin/sudo", "/usr/bin/apt-get", "update"],
            ],
        },
        {
            "name": "sudo_update_fails",
            "update_code": 100,
            "install_code": 100,
            "sudo_update_code": 100,
            "sudo_install_code": 100,
            "sudo_available": True,
            "expected_packages": [],
            "expected_commands": [
                ["/usr/bin/apt-get", "update"],
                ["/usr/bin/sudo", "/usr/bin/apt-get", "update"],
            ],
            "absent_commands": [
                ["/usr/bin/sudo", "/usr/bin/apt-get", "install", "--no-install-recommends", "-y", "iproute2"],
                ["/usr/bin/apt-get", "install", "--no-install-recommends", "-y", "iproute2"],
            ],
        },
        {
            "name": "non_sudo_path_succeeds",
            "update_code": 0,
            "install_code": 0,
            "sudo_update_code": 1,
            "sudo_install_code": 1,
            "sudo_available": True,
            "expected_packages": ["iproute2"],
            "expected_commands": [
                ["/usr/bin/apt-get", "update"],
                [
                    "/usr/bin/apt-get",
                    "install",
                    "--no-install-recommends",
                    "-y",
                    "iproute2",
                ],
            ],
            "absent_commands": [
                ["/usr/bin/sudo", "/usr/bin/apt-get", "update"],
                ["/usr/bin/sudo", "/usr/bin/apt-get", "install", "--no-install-recommends", "-y", "iproute2"],
            ],
        },
        {
            "name": "sudo_only_needed_for_install",
            "update_code": 0,
            "install_code": 100,
            "sudo_update_code": 1,
            "sudo_install_code": 0,
            "sudo_available": True,
            "expected_packages": ["iproute2"],
            "expected_commands": [
                ["/usr/bin/apt-get", "update"],
                [
                    "/usr/bin/apt-get",
                    "install",
                    "--no-install-recommends",
                    "-y",
                    "iproute2",
                ],
                [
                    "/usr/bin/sudo",
                    "/usr/bin/apt-get",
                    "install",
                    "--no-install-recommends",
                    "-y",
                    "iproute2",
                ],
            ],
            "absent_commands": [
                ["/usr/bin/sudo", "/usr/bin/apt-get", "update"],
            ],
        },
    ],
    ids=lambda scenario: scenario["name"],
)
def test_install_missing_tools_paths(monkeypatch: pytest.MonkeyPatch, scenario: dict) -> None:
    """`_install_missing_tools` should behave correctly across sudo and failure scenarios."""

    commands: list[list[str]] = []

    def fake_run(
        cmd: list[str], capture_output: bool, text: bool, env: dict | None = None
    ):  # pragma: no cover - behavior asserted via return codes
        commands.append(cmd)
        if cmd[0].endswith("apt-get") and cmd[1:] == ["update"]:
            return SimpleNamespace(
                returncode=scenario["update_code"], stdout="", stderr="Permission denied"
            )
        if cmd[0].endswith("apt-get") and cmd[1] == "install":
            return SimpleNamespace(
                returncode=scenario["install_code"], stdout="", stderr="Permission denied"
            )
        if cmd[0].endswith("sudo") and cmd[1:3] == ["/usr/bin/apt-get", "update"]:
            return SimpleNamespace(
                returncode=scenario["sudo_update_code"], stdout="", stderr="Permission denied"
            )
        if cmd[0].endswith("sudo") and cmd[1:3] == ["/usr/bin/apt-get", "install"]:
            return SimpleNamespace(
                returncode=scenario["sudo_install_code"], stdout="", stderr="Permission denied"
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    def fake_which(tool: str) -> str | None:
        if tool == "sudo" and not scenario["sudo_available"]:
            return None
        return "/usr/bin/" + tool

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(conftest.shutil, "which", fake_which)

    packages = conftest._install_missing_tools(["ip"])

    assert packages == scenario["expected_packages"]
    for expected in scenario["expected_commands"]:
        assert expected in commands
    for unexpected in scenario["absent_commands"]:
        assert unexpected not in commands
