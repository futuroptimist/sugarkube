import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ssd_clone.py"
SPEC = importlib.util.spec_from_file_location("ssd_clone", MODULE_PATH)
ssd_clone = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["ssd_clone"] = ssd_clone
SPEC.loader.exec_module(ssd_clone)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _clear_env():
    original = os.environ.pop(ssd_clone.ENV_TARGET, None)
    try:
        yield
    finally:
        if original is not None:
            os.environ[ssd_clone.ENV_TARGET] = original


@pytest.fixture
def fake_disk_layout(monkeypatch):
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    monkeypatch.setattr(ssd_clone, "device_size_bytes", lambda _: 32 * 1024 * 1024 * 1024)
    devices = {
        "blockdevices": [
            {"name": "mmcblk0", "type": "disk", "size": 32 * 1024 * 1024 * 1024},
            {
                "name": "sda",
                "type": "disk",
                "size": 128 * 1024 * 1024 * 1024,
                "hotplug": 1,
                "tran": "usb",
                "model": "FastSSD",
            },
            {
                "name": "sdb",
                "type": "disk",
                "size": 64 * 1024 * 1024 * 1024,
                "hotplug": 0,
                "tran": "sata",
            },
        ]
    }
    monkeypatch.setattr(ssd_clone, "lsblk_json", lambda _: devices)


def test_auto_select_target_prefers_hotplug(fake_disk_layout):
    target = ssd_clone.auto_select_target()
    assert target == "/dev/sda"


def test_auto_select_target_honors_env_override(monkeypatch, fake_disk_layout):
    override = "/dev/sdz"
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == override)
    os.environ[ssd_clone.ENV_TARGET] = override
    target = ssd_clone.auto_select_target()
    assert target == override


def test_resolve_env_target_errors_for_missing_device(monkeypatch):
    override = "/dev/sdz"
    os.environ[ssd_clone.ENV_TARGET] = override
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(SystemExit) as excinfo:
        ssd_clone.resolve_env_target()
    assert override in str(excinfo.value)


def test_resolve_env_target_rejects_source_disk(monkeypatch):
    override = "/dev/mmcblk0"
    os.environ[ssd_clone.ENV_TARGET] = override
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    with pytest.raises(SystemExit) as excinfo:
        ssd_clone.resolve_env_target()
    assert "source disk" in str(excinfo.value)


def test_step_run_marks_completion(monkeypatch):
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sda",
        dry_run=False,
        verbose=False,
        resume=False,
    )
    ctx.state = {}
    ctx.log = lambda *_: None
    calls = []

    def fake_func(inner_ctx):
        calls.append("ran")
        inner_ctx.state.setdefault("ran", True)

    def fake_save_state(inner_ctx):
        calls.append("saved")
        assert inner_ctx.state["completed"]["demo"] is True

    monkeypatch.setattr(ssd_clone, "save_state", fake_save_state)
    step = ssd_clone.Step("demo", "Demo step")
    step.run(ctx, fake_func)
    assert calls == ["ran", "saved"]
    step.run(ctx, fake_func)
    assert calls == ["ran", "saved"]


def test_ensure_state_ready_checks_existing_state(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"target": "/dev/sda"}), encoding="utf-8")
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdb",
        dry_run=False,
        verbose=False,
        resume=True,
        state_file=state_file,
    )
    ctx.log = lambda *_: None
    with pytest.raises(SystemExit) as excinfo:
        ssd_clone.ensure_state_ready(ctx)
    assert "/dev/sda" in str(excinfo.value)


def test_ensure_state_ready_requires_resume_flag(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdb",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=state_file,
    )
    ctx.log = lambda *_: None
    with pytest.raises(SystemExit) as excinfo:
        ssd_clone.ensure_state_ready(ctx)
    assert "state exists" in str(excinfo.value)
