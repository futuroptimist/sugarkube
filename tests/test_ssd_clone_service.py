import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ssd_clone_service.py"
SPEC = importlib.util.spec_from_file_location("scripts.ssd_clone_service", MODULE_PATH)
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


def test_notify_returns_when_notifier_missing(monkeypatch):
    monkeypatch.setattr(MODULE, "TeamsNotifier", None)
    MODULE.notify("ssd-clone", "info", [], {})
    assert DummyNotifier.notifications == []


def test_pick_target_auto_env(monkeypatch, tmp_path):
    target = tmp_path / "dev" / "sda"
    target.parent.mkdir(parents=True)
    target.write_text("disk")
    monkeypatch.setattr(MODULE, "AUTO_TARGET", str(target))
    assert MODULE.pick_target() == str(target)


def test_pick_target_auto_env_missing(monkeypatch, tmp_path):
    target = tmp_path / "dev" / "missing"
    messages = []
    monkeypatch.setattr(MODULE, "AUTO_TARGET", str(target))
    monkeypatch.setattr(MODULE, "log", messages.append)
    assert MODULE.pick_target() is None
    assert "missing" in messages[-1]


def test_ensure_root_requires_privileges(monkeypatch):
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit):
        MODULE.ensure_root()


def test_pick_target_auto_select_error(monkeypatch, capsys):
    monkeypatch.setattr(MODULE, "AUTO_TARGET", None)

    def fake_auto_select(*_args, **_kwargs):
        raise SystemExit("no target")

    monkeypatch.setattr(MODULE.ssd_clone, "auto_select_target", fake_auto_select)
    result = MODULE.pick_target()
    assert result is None
    captured = capsys.readouterr()
    assert "no target" in captured.out


def test_run_clone_with_extra_args(monkeypatch, tmp_path):
    target = str(tmp_path / "dev" / "sdc")
    command_seen = {}

    def fake_run(command, check=False):  # noqa: ARG001
        command_seen["command"] = command

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(MODULE, "EXTRA_ARGS", "--foo bar")
    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    MODULE.run_clone(target)
    assert command_seen["command"][-2:] == ["--foo", "bar"]


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
        lambda *_args, **_kwargs: str(target_path),
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

    monkeypatch.setattr(
        MODULE.ssd_clone,
        "auto_select_target",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(SystemExit) as exc:
        MODULE.main()

    assert exc.value.code == 0
    assert DummyNotifier.notifications[-1][1] == "failed"


def test_ssd_clone_service_failure_exit(monkeypatch, tmp_path):
    _state_dir, state_file, done_file = _configure_state(monkeypatch, tmp_path)
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

    target_path = tmp_path / "dev" / "sdb"
    target_path.parent.mkdir()
    target_path.write_text("target")

    monkeypatch.setattr(
        MODULE.ssd_clone,
        "auto_select_target",
        lambda *_args, **_kwargs: str(target_path),
    )

    def fake_run(command, check=False):  # noqa: ARG001 - subprocess signature
        assert command[0] == str(helper)

        class Result:
            returncode = 5

        return Result()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        MODULE.main()

    assert exc.value.code == 5
    assert not state_file.exists()
    assert not done_file.exists()
    assert DummyNotifier.notifications[-1][1] == "failed"


def test_main_done_file_exists(monkeypatch, tmp_path):
    state_dir, state_file, done_file = _configure_state(monkeypatch, tmp_path)
    done_file.write_text("done\n")
    helper = tmp_path / "ssd_clone.py"
    helper.write_text("#!/usr/bin/env python3\n")
    helper.chmod(0o755)
    monkeypatch.setattr(MODULE, "CLONE_HELPER", helper)
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0)
    MODULE.main()
    assert DummyNotifier.notifications == []


def test_main_missing_helper(monkeypatch, tmp_path):
    _configure_state(monkeypatch, tmp_path)
    helper = tmp_path / "missing.py"
    monkeypatch.setattr(MODULE, "CLONE_HELPER", helper)
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as exc:
        MODULE.main()
    assert "not found" in str(exc.value)


def test_main_raises_exit_code(monkeypatch, tmp_path):
    state_dir, state_file, done_file = _configure_state(monkeypatch, tmp_path)
    state_file.write_text("{}")
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
    monkeypatch.setattr(MODULE, "notify", lambda *args, **kwargs: None)
    target_path = tmp_path / "dev" / "sdd"
    target_path.parent.mkdir()
    target_path.write_text("target")
    monkeypatch.setattr(
        MODULE.ssd_clone,
        "auto_select_target",
        lambda *_args, **_kwargs: str(target_path),
    )

    def fake_run(command, check=False):  # noqa: ARG001
        class Result:
            returncode = 3

        return Result()

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exc:
        MODULE.main()
    assert exc.value.code == 3


def test_import_fallback(monkeypatch):
    import builtins

    module_name = "scripts.ssd_clone_service_missing"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,B009
        if name == "sugarkube_teams":
            raise ImportError("boom")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    assert module.TeamsNotifier is None
    assert module.TeamsNotificationError is RuntimeError
