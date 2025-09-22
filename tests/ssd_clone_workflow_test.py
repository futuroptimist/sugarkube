import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ssd_clone.py"

if "ssd_clone" in sys.modules:
    ssd_clone = sys.modules["ssd_clone"]
else:
    SPEC = importlib.util.spec_from_file_location("ssd_clone", MODULE_PATH)
    ssd_clone = importlib.util.module_from_spec(SPEC)
    assert SPEC and SPEC.loader
    sys.modules["ssd_clone"] = ssd_clone
    SPEC.loader.exec_module(ssd_clone)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_env():
    original = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_randomize_disk_identifiers_fallback(monkeypatch):
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=False,
    )
    calls = []

    def fake_run(command_ctx, command, *, input_text=None):
        assert command_ctx is ctx
        calls.append(tuple(command))
        if command[:2] == ["sgdisk", "-G"]:
            raise ssd_clone.CommandError("sgdisk failure")
        return object()

    monkeypatch.setattr(ssd_clone, "run_command", fake_run)
    monkeypatch.setattr(ssd_clone.secrets, "randbits", lambda bits: 0x12345678)

    ssd_clone.randomize_disk_identifiers(ctx)

    assert calls == [
        ("sgdisk", "-G", "/dev/sdz"),
        ("sfdisk", "--disk-id", "/dev/sdz", "0x12345678"),
    ]


def test_update_configs_rewrites_files(tmp_path, monkeypatch):
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    ctx.mount_root = tmp_path / "mnt"
    ctx.mount_root.mkdir()
    ctx.state = {
        "partition_suffix_boot": "1",
        "partition_suffix_root": "2",
        "source_root_partuuid": "OLDROOT",
        "source_boot_partuuid": "OLDBOOT",
    }

    boot_mount = ctx.mount_root / "boot-config"
    root_mount = ctx.mount_root / "root-config"
    (root_mount / "etc").mkdir(parents=True)
    boot_mount.mkdir()

    (boot_mount / "cmdline.txt").write_text(
        "console=serial0,115200 root=PARTUUID=OLDROOT rw quiet\n",
        encoding="utf-8",
    )
    (root_mount / "etc" / "fstab").write_text(
        "PARTUUID=OLDBOOT /boot vfat defaults 0 2\nPARTUUID=OLDROOT / ext4 defaults 0 1\n",
        encoding="utf-8",
    )

    mounts = []

    def fake_mount(command_ctx, device, mountpoint):
        assert command_ctx is ctx
        mounts.append(("mount", device, mountpoint))

    def fake_unmount(command_ctx, mountpoint):
        assert command_ctx is ctx
        mounts.append(("umount", mountpoint))

    monkeypatch.setattr(ssd_clone, "mount_partition", fake_mount)
    monkeypatch.setattr(ssd_clone, "unmount_partition", fake_unmount)

    def fake_partuuid(device: str) -> str:
        return "BOOTNEW" if device.endswith("1") else "ROOTNEW"

    monkeypatch.setattr(ssd_clone, "get_partuuid", fake_partuuid)

    ssd_clone.update_configs(ctx)

    assert (
        (boot_mount / "cmdline.txt")
        .read_text(encoding="utf-8")
        .strip()
        .endswith("root=PARTUUID=ROOTNEW rw quiet")
    )
    assert "BOOTNEW" in (root_mount / "etc" / "fstab").read_text(encoding="utf-8")
    assert "ROOTNEW" in (root_mount / "etc" / "fstab").read_text(encoding="utf-8")
    assert mounts == [
        ("mount", "/dev/sdz1", boot_mount),
        ("mount", "/dev/sdz2", root_mount),
        ("umount", root_mount),
        ("umount", boot_mount),
    ]


def test_ensure_state_ready_resume_validation(tmp_path):
    state_path = tmp_path / "resume.json"
    state_path.write_text(json.dumps({"target": "/dev/sdc"}), encoding="utf-8")
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdb",
        dry_run=False,
        verbose=False,
        resume=True,
        state_file=state_path,
    )

    with pytest.raises(SystemExit, match="State file references"):
        ssd_clone.ensure_state_ready(ctx)


def test_finalize_marks_completion(tmp_path, monkeypatch):
    done_file = tmp_path / "logs" / "ssd-clone.done"
    monkeypatch.setattr(ssd_clone, "DONE_FILE", done_file)

    saved_states = []

    def fake_save_state(ctx):
        saved_states.append(ctx.state.copy())

    monkeypatch.setattr(ssd_clone, "save_state", fake_save_state)

    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    ctx.mount_root = tmp_path / "mnt"
    ctx.state = {}

    ssd_clone.finalize(ctx)

    assert done_file.exists()
    assert done_file.read_text(encoding="utf-8") == "Clone completed\n"
    assert ctx.state["completed"]["finalize"] is True
    assert saved_states
