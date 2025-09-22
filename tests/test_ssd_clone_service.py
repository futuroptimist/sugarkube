import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ssd_clone_service.py"
SPEC = importlib.util.spec_from_file_location("ssd_clone_service", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
sys.modules.setdefault("ssd_clone_module", types.ModuleType("ssd_clone_module"))
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]
sys.modules["ssd_clone_module"] = MODULE.ssd_clone


class DummyNotifier:
    should_enable = True
    notifications = []

    def __init__(self):
        self.enabled = type(self).should_enable

    @classmethod
    def from_env(cls):
        return cls()

    def notify(self, *, event, status, lines, fields):
        type(self).notifications.append((event, status, tuple(lines), dict(fields)))


@pytest.fixture(autouse=True)
def _patch_notifier(monkeypatch):
    DummyNotifier.notifications.clear()
    DummyNotifier.should_enable = True
    monkeypatch.setattr(MODULE, "TeamsNotifier", DummyNotifier)
    monkeypatch.setattr(MODULE, "TeamsNotificationError", RuntimeError)


def _configure_state(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "ssd.state.json"
    done_file = state_dir / "ssd.done"
    monkeypatch.setattr(MODULE, "STATE_DIR", state_dir)
    monkeypatch.setattr(MODULE, "STATE_FILE", state_file)
    monkeypatch.setattr(MODULE, "DONE_FILE", done_file)
    MODULE.ssd_clone.STATE_DIR = state_dir
    MODULE.ssd_clone.STATE_FILE = state_file
    MODULE.ssd_clone.DONE_FILE = done_file
    return state_dir, state_file, done_file


def test_notify_skips_when_disabled(monkeypatch):
    DummyNotifier.should_enable = False
    MODULE.notify("ssd-clone", "success", ["line"], {"Field": "Value"})
    assert DummyNotifier.notifications == []


def test_ssd_clone_service_success(monkeypatch, tmp_path):
    state_dir, state_file, done_file = _configure_state(monkeypatch, tmp_path)
    helper = tmp_path / "ssd_clone.py"
    helper.write_text("#!/usr/bin/env python3\n")
    helper.chmod(0o755)
    monkeypatch.setattr(MODULE, "CLONE_HELPER", helper)
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0)
    monkeypatch.setattr(MODULE, "AUTO_TARGET", None)
    monkeypatch.setattr(MODULE, "POLL_INTERVAL", 1)
    monkeypatch.setattr(MODULE, "MAX_WAIT", 1)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _secs: None)
    monkeypatch.setattr(MODULE, "log", lambda _msg: None)

    target_path = tmp_path / "dev" / "sda"
    target_path.parent.mkdir()
    target_path.write_text("target")

    monkeypatch.setattr(
        MODULE.ssd_clone,
        "auto_select_target",
        lambda: str(target_path),
    )

    def fake_run(command, check=False):  # noqa: ARG001 - subprocess signature
        assert command[0] == str(helper)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"completed": {"resize": True}}))
        done_file.write_text("complete\n")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    MODULE.main()

    events = [(event, status) for event, status, *_ in DummyNotifier.notifications]
    assert events == [
        ("ssd-clone", "starting"),
        ("ssd-clone", "info"),
        ("ssd-clone", "success"),
    ]


def test_ssd_clone_service_timeout(monkeypatch, tmp_path):
    _configure_state(monkeypatch, tmp_path)
    helper = tmp_path / "ssd_clone.py"
    helper.write_text("#!/usr/bin/env python3\n")
    helper.chmod(0o755)
    monkeypatch.setattr(MODULE, "CLONE_HELPER", helper)
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0)
    monkeypatch.setattr(MODULE, "AUTO_TARGET", None)
    monkeypatch.setattr(MODULE, "POLL_INTERVAL", 1)
    monkeypatch.setattr(MODULE, "MAX_WAIT", 1)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _secs: None)
    monkeypatch.setattr(MODULE, "log", lambda _msg: None)

    monkeypatch.setattr(MODULE.ssd_clone, "auto_select_target", lambda: None)

    with pytest.raises(SystemExit) as exc:
        MODULE.main()

    assert exc.value.code == 0
    assert DummyNotifier.notifications[-1][1] == "failed"
