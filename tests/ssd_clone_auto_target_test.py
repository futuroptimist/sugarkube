import importlib.util
import json
import os
import subprocess
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


def test_resolve_env_target_missing_device(monkeypatch):
    os.environ[ssd_clone.ENV_TARGET] = "/dev/missing"
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(SystemExit, match="does not exist"):
        ssd_clone.resolve_env_target()


def test_resolve_env_target_rejects_source_disk(monkeypatch):
    os.environ[ssd_clone.ENV_TARGET] = "/dev/mmcblk0"
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    with pytest.raises(SystemExit, match="source disk"):
        ssd_clone.resolve_env_target()


def test_auto_select_target_requires_list(monkeypatch, fake_disk_layout):
    monkeypatch.setattr(ssd_clone, "lsblk_json", lambda _: {"blockdevices": {}})
    with pytest.raises(SystemExit, match="Unexpected lsblk JSON structure"):
        ssd_clone.auto_select_target()


def test_auto_select_target_errors_without_candidates(monkeypatch, fake_disk_layout):
    monkeypatch.setattr(
        ssd_clone,
        "lsblk_json",
        lambda _: {
            "blockdevices": [{"name": "mmcblk0", "type": "disk", "size": 32 * 1024 * 1024 * 1024}]
        },
    )
    with pytest.raises(SystemExit, match="Unable to automatically determine"):
        ssd_clone.auto_select_target()


def test_lsblk_json_success(monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        assert cmd[:3] == ["lsblk", "--json", "-b"]
        return subprocess.CompletedProcess(cmd, 0, '{"blockdevices": []}', "")

    monkeypatch.setattr(ssd_clone.subprocess, "run", fake_run)
    result = ssd_clone.lsblk_json(["NAME"])
    assert result == {"blockdevices": []}


def test_lsblk_json_failure(monkeypatch):
    monkeypatch.setattr(
        ssd_clone.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "oops"),
    )
    with pytest.raises(SystemExit, match="lsblk --json failed"):
        ssd_clone.lsblk_json(["NAME"])


def test_lsblk_json_bad_json(monkeypatch):
    monkeypatch.setattr(
        ssd_clone.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "not json", ""),
    )
    with pytest.raises(SystemExit, match="Unable to parse lsblk output"):
        ssd_clone.lsblk_json(["NAME"])


def test_device_size_bytes(monkeypatch):
    monkeypatch.setattr(
        ssd_clone.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "4096\n", ""),
    )
    assert ssd_clone.device_size_bytes("/dev/sdz") == 4096


def test_device_size_bytes_errors(monkeypatch):
    monkeypatch.setattr(
        ssd_clone.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "\n", ""),
    )
    with pytest.raises(SystemExit, match="Unable to determine size"):
        ssd_clone.device_size_bytes("/dev/sdz")


def test_auto_select_target_skips_non_viable(monkeypatch, capsys):
    monkeypatch.setattr(ssd_clone, "resolve_env_target", lambda: None)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    monkeypatch.setattr(ssd_clone, "device_size_bytes", lambda _: 32 * 1024 * 1024 * 1024)
    devices = {
        "blockdevices": [
            {"name": "loop0", "type": "loop", "size": 64 * 1024},
            {"type": "disk", "size": 256 * 1024},
            {"name": "mmcblk0", "type": "disk", "size": 32 * 1024 * 1024 * 1024},
            {"name": "sdb", "type": "disk", "size": 16 * 1024 * 1024 * 1024, "hotplug": 1},
            {
                "kname": "sdc",
                "type": "disk",
                "size": 128 * 1024 * 1024 * 1024,
                "hotplug": 1,
                "tran": "usb",
                "model": "ShinySSD",
            },
        ]
    }
    monkeypatch.setattr(ssd_clone, "lsblk_json", lambda _: devices)
    target = ssd_clone.auto_select_target()
    captured = capsys.readouterr()
    assert target == "/dev/sdc"
    assert "Auto-selected clone target: /dev/sdc" in captured.out


def make_context(tmp_path, **overrides):
    state_file = overrides.pop("state_file", tmp_path / "state.json")
    context = ssd_clone.CloneContext(
        target_disk=overrides.pop("target_disk", "/dev/sdz"),
        dry_run=overrides.pop("dry_run", False),
        verbose=overrides.pop("verbose", False),
        resume=overrides.pop("resume", False),
        state_file=state_file,
        **overrides,
    )
    context.state = overrides.pop("state", {}) or {}
    return context


def test_save_state_writes_json(tmp_path):
    ctx = make_context(tmp_path)
    ctx.state = {"foo": "bar"}
    ssd_clone.save_state(ctx)
    data = json.loads(ctx.state_file.read_text(encoding="utf-8"))
    assert data["target"] == "/dev/sdz"
    assert data["completed"] == {}
    assert data["foo"] == "bar"


def test_save_state_skips_dry_run(tmp_path):
    ctx = make_context(tmp_path, dry_run=True)
    ctx.state = {"foo": "bar"}
    ssd_clone.save_state(ctx)
    assert not ctx.state_file.exists()
    assert ctx.state == {"foo": "bar"}


def test_load_state_reads_json(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"target": "/dev/sdz", "completed": {}}), encoding="utf-8")
    ctx = make_context(tmp_path, state_file=state_path)
    ssd_clone.load_state(ctx)
    assert ctx.state == {"target": "/dev/sdz", "completed": {}}


def test_ensure_state_ready_resume_mismatch(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"target": "/dev/sda"}), encoding="utf-8")
    ctx = make_context(tmp_path, state_file=state_path, resume=True)
    with pytest.raises(SystemExit, match="State file references"):
        ssd_clone.ensure_state_ready(ctx)


def test_ensure_state_ready_initializes_state(tmp_path):
    ctx = make_context(tmp_path)
    ssd_clone.ensure_state_ready(ctx)
    assert ctx.state_file.exists()
    data = json.loads(ctx.state_file.read_text(encoding="utf-8"))
    assert data["target"] == "/dev/sdz"
    assert data["completed"] == {}


def test_load_state_missing_file(tmp_path):
    ctx = make_context(tmp_path)
    assert not ctx.state_file.exists()
    ctx.state = {"preexisting": True}
    ssd_clone.load_state(ctx)
    assert ctx.state == {}


def test_ensure_state_ready_requires_resume(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"target": "/dev/sdz"}), encoding="utf-8")
    ctx = make_context(tmp_path, state_file=state_path)
    with pytest.raises(SystemExit, match="Use --resume"):
        ssd_clone.ensure_state_ready(ctx)


def test_randomize_disk_identifiers_success(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    calls = []

    def fake_run_command(inner_ctx, command, *, input_text=None):
        assert inner_ctx is ctx
        calls.append((tuple(command), input_text))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ssd_clone, "run_command", fake_run_command)
    ssd_clone.randomize_disk_identifiers(ctx)
    assert calls == [(("sgdisk", "-G", "/dev/sdz"), None)]


def test_randomize_disk_identifiers_fallback(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    calls = []
    messages = []

    def fake_run_command(inner_ctx, command, *, input_text=None):
        calls.append((tuple(command), input_text))
        if command[:2] == ["sgdisk", "-G"]:
            raise ssd_clone.CommandError("boom")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ssd_clone, "run_command", fake_run_command)
    monkeypatch.setattr(
        ssd_clone,
        "secrets",
        type("Secrets", (), {"randbits": staticmethod(lambda bits: 0x12345678)}),
    )
    monkeypatch.setattr(ctx, "log", lambda message: messages.append(message))
    ssd_clone.randomize_disk_identifiers(ctx)
    assert calls == [
        (("sgdisk", "-G", "/dev/sdz"), None),
        (("sfdisk", "--disk-id", "/dev/sdz", "0x12345678"), None),
    ]
    assert any("falling back" in message for message in messages)
