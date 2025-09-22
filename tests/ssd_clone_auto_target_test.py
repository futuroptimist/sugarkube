import importlib.util
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


def test_parse_args_requires_target(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ssd_clone.py"])
    with pytest.raises(SystemExit):
        ssd_clone.parse_args()


def test_parse_args_accepts_auto_target(monkeypatch, tmp_path):
    argv = [
        "ssd_clone.py",
        "--auto-target",
        "--mount-root",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    args = ssd_clone.parse_args()
    assert args.auto_target is True
    assert args.target is None
    assert args.mount_root == tmp_path


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


def test_main_uses_auto_target(monkeypatch, tmp_path):
    chosen = {}

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ssd_clone.py",
            "--auto-target",
            "--mount-root",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(ssd_clone, "ensure_root", lambda: None)

    def fake_auto_select():
        chosen["device"] = "/dev/fake"
        return "/dev/fake"

    monkeypatch.setattr(ssd_clone, "auto_select_target", fake_auto_select)
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(ssd_clone, "ensure_mount_point", lambda path: None)

    def stop(ctx):
        raise SystemExit("stop")

    monkeypatch.setattr(ssd_clone, "ensure_state_ready", stop)

    with pytest.raises(SystemExit, match="stop"):
        ssd_clone.main()

    assert chosen["device"] == "/dev/fake"
