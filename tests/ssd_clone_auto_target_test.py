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
    original_target = os.environ.pop(ssd_clone.ENV_TARGET, None)
    original_wait = os.environ.pop(ssd_clone.ENV_WAIT, None)
    original_poll = os.environ.pop(ssd_clone.ENV_POLL, None)
    original_extra = os.environ.pop(ssd_clone.ENV_EXTRA_ARGS, None)
    try:
        yield
    finally:
        if original_target is not None:
            os.environ[ssd_clone.ENV_TARGET] = original_target
        if original_wait is not None:
            os.environ[ssd_clone.ENV_WAIT] = original_wait
        if original_poll is not None:
            os.environ[ssd_clone.ENV_POLL] = original_poll
        if original_extra is not None:
            os.environ[ssd_clone.ENV_EXTRA_ARGS] = original_extra


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


def test_parse_args_appends_extra_env(monkeypatch):
    monkeypatch.setenv(ssd_clone.ENV_EXTRA_ARGS, "--dry-run --resume")
    args = ssd_clone.parse_args(["--target", "/dev/sdz"])
    assert args.dry_run is True
    assert args.resume is True


def test_parse_args_rejects_bad_extra_env(monkeypatch):
    monkeypatch.setenv(ssd_clone.ENV_EXTRA_ARGS, "'unterminated")
    with pytest.raises(SystemExit, match=ssd_clone.ENV_EXTRA_ARGS):
        ssd_clone.parse_args(["--target", "/dev/sdz"])


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
    os.environ[ssd_clone.ENV_WAIT] = "0"
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
    os.environ[ssd_clone.ENV_WAIT] = "0"
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


def test_auto_select_target_waits_for_hotplug(monkeypatch):
    monkeypatch.setattr(ssd_clone, "resolve_env_target", lambda: None)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    monkeypatch.setattr(ssd_clone, "device_size_bytes", lambda _: 16 * 1024 * 1024 * 1024)

    responses = [
        {"blockdevices": [{"name": "mmcblk0", "type": "disk", "size": 16 * 1024 * 1024 * 1024}]},
        {
            "blockdevices": [
                {"name": "mmcblk0", "type": "disk", "size": 16 * 1024 * 1024 * 1024},
                {
                    "name": "sda",
                    "type": "disk",
                    "size": 64 * 1024 * 1024 * 1024,
                    "hotplug": 1,
                    "tran": "usb",
                    "model": "HotplugSSD",
                },
            ]
        },
    ]
    call_counter = {"count": 0}

    def fake_lsblk(_fields):
        index = min(call_counter["count"], len(responses) - 1)
        call_counter["count"] += 1
        return responses[index]

    monkeypatch.setattr(ssd_clone, "lsblk_json", fake_lsblk)

    timeline = iter([0.0, 0.5, 1.0, 1.5])
    monkeypatch.setattr(ssd_clone.time, "monotonic", lambda: next(timeline))
    sleeps: list[float] = []
    monkeypatch.setattr(ssd_clone.time, "sleep", lambda seconds: sleeps.append(seconds))

    target = ssd_clone.auto_select_target(wait_secs=2, poll_secs=1)

    assert target == "/dev/sda"
    assert sleeps == [1]


def test_auto_select_target_timeout(monkeypatch):
    monkeypatch.setattr(ssd_clone, "resolve_env_target", lambda: None)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda path: path)
    monkeypatch.setattr(ssd_clone, "device_size_bytes", lambda _: 16 * 1024 * 1024 * 1024)
    monkeypatch.setattr(
        ssd_clone,
        "lsblk_json",
        lambda _fields: {
            "blockdevices": [
                {
                    "name": "mmcblk0",
                    "type": "disk",
                    "size": 16 * 1024 * 1024 * 1024,
                }
            ]
        },
    )

    class FakeClock:
        def __init__(self):
            self.values = [0.0, 1.0, 2.1]

        def monotonic(self):
            return self.values.pop(0)

        def sleep(self, _seconds):
            pass

    clock = FakeClock()
    monkeypatch.setattr(ssd_clone.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ssd_clone.time, "sleep", clock.sleep)

    with pytest.raises(SystemExit, match="Unable to automatically determine"):
        ssd_clone.auto_select_target(wait_secs=2, poll_secs=1)


def test_auto_select_target_rejects_invalid_env(monkeypatch):
    monkeypatch.setattr(ssd_clone, "resolve_env_target", lambda: None)
    os.environ[ssd_clone.ENV_WAIT] = "not-a-number"
    with pytest.raises(SystemExit, match=ssd_clone.ENV_WAIT):
        ssd_clone.auto_select_target()
    os.environ[ssd_clone.ENV_WAIT] = "0"
    os.environ[ssd_clone.ENV_POLL] = "0"
    with pytest.raises(SystemExit, match=ssd_clone.ENV_POLL):
        ssd_clone.auto_select_target()


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


def test_clone_context_defaults_cover_new_flags() -> None:
    ctx = ssd_clone.CloneContext(target_disk="/dev/sdz")
    assert ctx.dry_run is False
    assert ctx.verbose is False
    assert ctx.resume is False
    assert ctx.assume_yes is False
    assert ctx.skip_partition is False
    assert ctx.skip_format is False
    assert ctx.skip_to is None
    assert ctx.preserve_labels is False
    assert ctx.refresh_uuid is False
    assert ctx.boot_label is None
    assert ctx.root_label is None
    assert ctx.boot_mount == "/boot"


def test_clone_context_defaults_keep_state_file() -> None:
    ctx = ssd_clone.CloneContext(target_disk="/dev/sdz")
    assert ctx.state_file == ssd_clone.STATE_FILE
    assert ctx.state == {}


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


def test_step_run_records_completion(tmp_path):
    ctx = make_context(tmp_path)
    step = ssd_clone.Step("demo", "Demo step")
    invoked = []

    def _action(run_ctx):
        assert run_ctx is ctx
        invoked.append(True)

    step.run(ctx, _action)

    assert invoked == [True]
    assert ctx.state["completed"]["demo"] is True


def test_step_run_skips_completed(tmp_path, capsys):
    ctx = make_context(tmp_path, state={"completed": {"demo": True}})
    step = ssd_clone.Step("demo", "Demo step")

    step.run(ctx, lambda _: pytest.fail("step should have been skipped"))

    captured = capsys.readouterr()
    assert "Skipping demo (already completed)" in captured.out


def test_run_command_handles_dry_run(tmp_path):
    ctx = make_context(tmp_path, dry_run=True)

    result = ssd_clone.run_command(ctx, ["echo", "hello"])

    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.args == ["echo", "hello"]


def test_run_command_verbose_output(monkeypatch, tmp_path, capsys):
    ctx = make_context(tmp_path, verbose=True)

    def fake_run(command, check, text, capture_output, input=None):
        assert command == ["echo", "hi"]
        assert check is False
        assert text is True
        assert capture_output is True
        return subprocess.CompletedProcess(command, 0, "stdout text", "stderr text")

    monkeypatch.setattr(ssd_clone.subprocess, "run", fake_run)

    result = ssd_clone.run_command(ctx, ["echo", "hi"])

    assert result.returncode == 0
    captured = capsys.readouterr()
    assert "stdout text" in captured.out
    assert "stderr text" in captured.err


def test_run_command_raises_on_failure(monkeypatch, tmp_path):
    ctx = make_context(tmp_path)

    def fake_run(command, check, text, capture_output, input=None):
        return subprocess.CompletedProcess(command, 1, "boom", "bang")

    monkeypatch.setattr(ssd_clone.subprocess, "run", fake_run)

    with pytest.raises(ssd_clone.CommandError) as excinfo:
        ssd_clone.run_command(ctx, ["false"])

    assert "Command failed" in str(excinfo.value)


def test_update_configs_rewrites_files(monkeypatch, tmp_path):
    ctx = make_context(tmp_path, mount_root=tmp_path)
    ctx.state.update(
        {
            "partition_suffix_boot": "1",
            "partition_suffix_root": "2",
            "source_root_partuuid": "root-old",
            "source_boot_partuuid": "boot-old",
        }
    )
    ctx.target_disk = "/dev/sdz"

    boot_mount = tmp_path / "boot-config"
    root_mount = tmp_path / "root-config"
    boot_mount.mkdir(parents=True, exist_ok=True)
    root_etc = root_mount / "etc"
    root_etc.mkdir(parents=True, exist_ok=True)

    (boot_mount / "cmdline.txt").write_text("root=PARTUUID=root-old quiet\n", encoding="utf-8")
    (root_etc / "fstab").write_text(
        "PARTUUID=root-old / ext4\nPARTUUID=boot-old /boot vfat\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(ssd_clone, "mount_partition", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssd_clone, "unmount_partition", lambda *args, **kwargs: None)

    uuids = {"/dev/sdz1": "boot-new", "/dev/sdz2": "root-new"}
    monkeypatch.setattr(ssd_clone, "get_partuuid", lambda device: uuids[device])

    ssd_clone.update_configs(ctx)

    cmdline = (boot_mount / "cmdline.txt").read_text(encoding="utf-8")
    fstab = (root_etc / "fstab").read_text(encoding="utf-8")

    assert "root=PARTUUID=root-new" in cmdline
    assert "PARTUUID=root-new / ext4" in fstab
    assert "PARTUUID=boot-new /boot" in fstab
