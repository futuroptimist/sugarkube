import importlib.util
import os
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


@pytest.fixture(autouse=True)
def _clear_env():
    """Ensure SUGARKUBE_SSD_CLONE_TARGET does not leak between tests."""

    original = os.environ.pop(ssd_clone.ENV_TARGET, None)
    try:
        yield
    finally:
        if original is not None:
            os.environ[ssd_clone.ENV_TARGET] = original


def make_context(tmp_path, *, dry_run=False, verbose=False):
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=dry_run,
        verbose=verbose,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    ctx.mount_root = tmp_path / "mnt"
    return ctx


def test_step_run_executes_and_marks_complete(monkeypatch, tmp_path):
    ctx = make_context(tmp_path)
    executed = []
    monkeypatch.setattr(ssd_clone, "save_state", lambda local_ctx: executed.append("saved"))

    ctx.dry_run = False
    step = ssd_clone.Step("demo", "Demo step")

    def _run(local_ctx):
        local_ctx.state.setdefault("ran", True)

    step.run(ctx, _run)

    assert ctx.state["ran"] is True
    assert ctx.state["completed"]["demo"] is True
    assert executed == ["saved"]


def test_step_run_skips_completed(tmp_path):
    ctx = make_context(tmp_path, dry_run=True)
    ctx.state = {"completed": {"skip": True}}
    called = []
    step = ssd_clone.Step("skip", "Skip step")

    def _run(local_ctx):
        called.append(local_ctx)

    step.run(ctx, _run)
    assert called == []


def test_run_command_dry_run(monkeypatch, tmp_path):
    ctx = make_context(tmp_path, dry_run=True)

    def _fail(*_, **__):  # pragma: no cover - should never run
        raise AssertionError("subprocess.run should not be called in dry-run mode")

    monkeypatch.setattr(ssd_clone.subprocess, "run", _fail)

    result = ssd_clone.run_command(ctx, ["echo", "hello"])
    assert result.returncode == 0
    assert result.args == ["echo", "hello"]


def test_run_command_verbose_outputs(monkeypatch, tmp_path, capsys):
    ctx = make_context(tmp_path, dry_run=False, verbose=True)

    def _run(*_, **__):
        return ssd_clone.subprocess.CompletedProcess(["echo"], 0, "out", "err")

    monkeypatch.setattr(ssd_clone.subprocess, "run", _run)

    result = ssd_clone.run_command(ctx, ["echo"])
    captured = capsys.readouterr()
    assert result.stdout == "out"
    assert captured.out.endswith("out")
    assert captured.err.endswith("err")


def test_resolve_env_target_requires_existing(monkeypatch):
    override = "/dev/missing"
    os.environ[ssd_clone.ENV_TARGET] = override
    original_exists = Path.exists

    def fake_exists(self):
        if str(self) == override:
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    with pytest.raises(SystemExit) as exc:
        ssd_clone.resolve_env_target()
    assert override in str(exc.value)


def test_resolve_env_target_rejects_source_disk(monkeypatch):
    override = "/dev/mmcblk0"
    os.environ[ssd_clone.ENV_TARGET] = override
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == override)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda value: value)

    with pytest.raises(SystemExit) as exc:
        ssd_clone.resolve_env_target()
    assert "source disk" in str(exc.value)


def test_resolve_env_target_returns_valid_override(monkeypatch):
    override = "/dev/sdz"
    os.environ[ssd_clone.ENV_TARGET] = override
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == override)
    monkeypatch.setattr(ssd_clone, "resolve_mount_device", lambda _: "/dev/mmcblk0p2")
    monkeypatch.setattr(ssd_clone, "parent_disk", lambda _: "/dev/mmcblk0")
    monkeypatch.setattr(ssd_clone.os.path, "realpath", lambda value: value)

    assert ssd_clone.resolve_env_target() == override
