import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ssd_clone.py"

if "ssd_clone" in sys.modules:
    ssd_clone = sys.modules["ssd_clone"]
else:
    SPEC = importlib.util.spec_from_file_location("ssd_clone", MODULE_PATH)
    assert SPEC and SPEC.loader
    ssd_clone = importlib.util.module_from_spec(SPEC)
    sys.modules["ssd_clone"] = ssd_clone
    SPEC.loader.exec_module(ssd_clone)  # type: ignore[attr-defined]


@pytest.fixture
def ctx(tmp_path):
    context = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    context.state = {}
    return context


def test_step_run_skips_completed(ctx):
    ctx.state = {"completed": {"partition": True}}
    step = ssd_clone.Step("partition", "Replicating partition table")

    def fail(_ctx):
        raise AssertionError("step should not run when already completed")

    step.run(ctx, fail)


def test_step_run_marks_completion(monkeypatch, ctx):
    invoked = {"count": 0}

    def fake_save_state(local_ctx):
        invoked["count"] += 1
        assert local_ctx.state["completed"]["format"] is True

    monkeypatch.setattr(ssd_clone, "save_state", fake_save_state)

    step = ssd_clone.Step("format", "Formatting target partitions")

    def noop(local_ctx):
        local_ctx.state.setdefault("ran", True)

    step.run(ctx, noop)
    assert ctx.state.get("ran") is True
    assert invoked["count"] == 1


def test_run_command_dry_run(tmp_path):
    context = ssd_clone.CloneContext(
        target_disk="/dev/sdy",
        dry_run=True,
        verbose=False,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    result = ssd_clone.run_command(context, ["echo", "hello"])
    assert result.returncode == 0


def test_run_command_streams_output(monkeypatch, capsys, ctx):
    ctx.verbose = True

    def fake_run(*args, **kwargs):
        command = args[0]
        return subprocess.CompletedProcess(command, 0, "stdout-data", "stderr-data")

    monkeypatch.setattr(ssd_clone.subprocess, "run", fake_run)

    result = ssd_clone.run_command(ctx, ["true"])
    assert result.returncode == 0
    captured = capsys.readouterr()
    assert "stdout-data" in captured.out
    assert "stderr-data" in captured.err


def test_run_command_raises(monkeypatch, ctx):
    def fake_run(*args, **kwargs):
        command = args[0]
        return subprocess.CompletedProcess(command, 1, "", "boom")

    monkeypatch.setattr(ssd_clone.subprocess, "run", fake_run)

    with pytest.raises(ssd_clone.CommandError):
        ssd_clone.run_command(ctx, ["false"])


def test_randomize_disk_identifiers_falls_back(monkeypatch, ctx):
    calls = []

    def fake_run(local_ctx, command, *, input_text=None):
        calls.append(command)
        if command[:2] == ["sgdisk", "-G"]:
            raise ssd_clone.CommandError("fail")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ssd_clone, "run_command", fake_run)
    ssd_clone.randomize_disk_identifiers(ctx)
    assert any(cmd[:2] == ["sfdisk", "--disk-id"] for cmd in calls)


def test_ensure_state_ready_requires_resume(tmp_path, ctx):
    ctx.state_file.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        ssd_clone.ensure_state_ready(ctx)


def test_ensure_state_ready_resume_loads(tmp_path):
    state_file = tmp_path / "state.json"
    state = {"target": "/dev/sdz", "completed": {}}
    state_file.write_text(json.dumps(state), encoding="utf-8")
    context = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=True,
        state_file=state_file,
    )
    ssd_clone.ensure_state_ready(context)
    assert context.state == state


def test_ensure_state_ready_resume_rejects_mismatch(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"target": "/dev/sdb"}), encoding="utf-8")
    context = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=True,
        state_file=state_file,
    )
    with pytest.raises(SystemExit):
        ssd_clone.ensure_state_ready(context)


def test_gather_source_metadata(monkeypatch, tmp_path):
    context = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    context.state = {}

    def fake_resolve(mountpoint):
        return "/dev/mmcblk0p2" if mountpoint == "/" else "/dev/mmcblk0p1"

    monkeypatch.setattr(ssd_clone, "resolve_mount_device", fake_resolve)
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda device: device[:-2])
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda value: value)
    monkeypatch.setattr(
        ssd_clone,
        "partition_suffix",
        lambda device: "1" if device.endswith("p1") else "2",
    )
    monkeypatch.setattr(ssd_clone, "get_partuuid", lambda device: f"uuid-{device}")
    monkeypatch.setattr(
        ssd_clone,
        "detect_filesystem",
        lambda device: "vfat" if device.endswith("p1") else "ext4",
    )

    saved = {"called": False}

    def fake_save_state(local_ctx):
        saved["called"] = True
        assert local_ctx.state["source_disk"] == "/dev/mmcblk0"

    monkeypatch.setattr(ssd_clone, "save_state", fake_save_state)

    ssd_clone.gather_source_metadata(context)
    assert context.state["source_root_partuuid"] == "uuid-/dev/mmcblk0p2"
    assert context.state["source_boot_partuuid"] == "uuid-/dev/mmcblk0p1"
    assert context.state["source_root_fs"] == "ext4"
    assert context.state["source_boot_fs"] == "vfat"
    assert saved["called"] is True


def test_main_rejects_missing_target(monkeypatch, tmp_path):
    monkeypatch.setattr(ssd_clone, "ensure_root", lambda: None)
    monkeypatch.setattr(
        ssd_clone,
        "parse_args",
        lambda: argparse.Namespace(
            target="/dev/missing",
            auto_target=False,
            dry_run=False,
            resume=False,
            state_file=tmp_path / "state.json",
            mount_root=tmp_path / "mnt",
            verbose=False,
        ),
    )
    monkeypatch.setattr(ssd_clone.Path, "exists", lambda self: str(self) != "/dev/missing")

    with pytest.raises(SystemExit):
        ssd_clone.main()
