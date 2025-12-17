"""Behavioral coverage for ensure_root_privileges."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import tests.conftest as conftest


def test_ensure_root_privileges_skips_when_netns_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd == ["id", "-u"]:
            return SimpleNamespace(stdout="1000\n", returncode=0)
        if cmd == ["unshare", "-n", "true"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[:3] == ["ip", "netns", "add"]:
            return SimpleNamespace(stdout="", stderr="", returncode=1)
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)

    with pytest.raises(pytest.skip.Exception):
        conftest.ensure_root_privileges()

    assert commands[-1][:3] == ["ip", "netns", "add"]


def test_ensure_root_privileges_allows_when_netns_creation_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], capture_output: bool, text: bool):
        commands.append(cmd)
        if cmd == ["id", "-u"]:
            return SimpleNamespace(stdout="1000\n", returncode=0)
        if cmd == ["unshare", "-n", "true"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[:3] == ["ip", "netns", "add"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[:3] == ["ip", "netns", "delete"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(conftest.subprocess, "run", fake_run)

    conftest.ensure_root_privileges()

    assert commands[-1][:3] == ["ip", "netns", "delete"]
