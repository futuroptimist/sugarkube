"""Tests for the Sugarkube toolkit runner helpers."""

from __future__ import annotations

import os
import runpy
from types import SimpleNamespace

import pytest

from scripts import toolkit as bridge
from sugarkube_toolkit import cli, runner


@pytest.fixture(autouse=True)
def _preserve_env():
    original = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_run_commands_supports_dry_run(monkeypatch: pytest.MonkeyPatch, capsys):
    """Dry runs should only print the commands without executing them."""

    called = False

    def fake_run(*_args, **_kwargs):  # pragma: no cover - defensive
        nonlocal called
        called = True

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_commands([["echo", "hello world"]], dry_run=True)

    captured = capsys.readouterr()
    assert "$ echo 'hello world'" in captured.out
    assert not called


def test_run_commands_merges_environment(monkeypatch: pytest.MonkeyPatch):
    """Custom environment variables should augment the parent environment."""

    os.environ["MERGE_TEST"] = "original"

    recorded = {}

    def fake_run(command, *, env, check, text, stderr):
        recorded.update(
            {
                "command": command,
                "env": env,
                "check": check,
                "text": text,
                "stderr": stderr,
            }
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_commands([["true"]], env={"EXTRA": "value", "MERGE_TEST": "override"})

    assert recorded["command"] == ["true"]
    assert recorded["check"] is False
    assert recorded["text"] is True
    assert recorded["stderr"] is runner.subprocess.PIPE
    assert recorded["env"]["EXTRA"] == "value"
    assert recorded["env"]["MERGE_TEST"] == "override"
    assert os.environ["MERGE_TEST"] == "original"


def test_run_commands_raises_command_error(monkeypatch: pytest.MonkeyPatch):
    """Failures should raise CommandError with the stderr output."""

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=4, stderr="boom\n")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.CommandError) as excinfo:
        runner.run_commands([["false"]])

    message = str(excinfo.value)
    assert "false" in message
    assert "boom" in message


def test_scripts_toolkit_reexports_runner_helpers() -> None:
    """The bridge module should expose the runner helpers for legacy scripts."""

    assert bridge.CommandError is runner.CommandError
    assert bridge.run_commands is runner.run_commands
    assert bridge.format_command is runner.format_command
    assert set(bridge.__all__) == {"CommandError", "format_command", "run_commands"}


def test_main_module_invokes_cli_main(monkeypatch: pytest.MonkeyPatch):
    """The module entry point should exit using the CLI's main function."""

    monkeypatch.setattr(cli, "main", lambda: 42)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("sugarkube_toolkit.__main__", run_name="__main__")

    assert excinfo.value.code == 42
