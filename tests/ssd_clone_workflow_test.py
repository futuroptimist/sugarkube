import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ssd_clone.py"
SPEC = importlib.util.spec_from_file_location("ssd_clone_workflow", MODULE_PATH)
ssd_clone = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules.setdefault("ssd_clone_workflow", ssd_clone)
SPEC.loader.exec_module(ssd_clone)  # type: ignore[attr-defined]


@pytest.fixture
def clone_ctx(tmp_path):
    state_file = tmp_path / "state.json"
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdz",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=state_file,
    )
    ctx.mount_root = tmp_path / "mnt"
    return ctx


def test_step_marks_completion_and_persists_state(clone_ctx, tmp_path, monkeypatch):
    recorded = {}

    def fake_save(ctx):
        recorded["state_snapshot"] = json.loads(json.dumps(ctx.state))

    monkeypatch.setattr(ssd_clone, "save_state", fake_save)

    executed = []

    def sample_step(ctx):
        executed.append(ctx.target_disk)

    step = ssd_clone.Step("format", "Formatting target")
    step.run(clone_ctx, sample_step)

    assert executed == ["/dev/sdz"]
    assert clone_ctx.state["completed"]["format"] is True
    assert recorded["state_snapshot"]["completed"]["format"] is True


def test_step_skips_when_already_completed(clone_ctx):
    clone_ctx.state = {"completed": {"partition": True}}

    def should_not_run(ctx):  # pragma: no cover - defensive
        raise AssertionError("Step executed despite being marked complete")

    step = ssd_clone.Step("partition", "Replicating partition table")
    step.run(clone_ctx, should_not_run)


def test_ensure_state_ready_resume_validates_target(clone_ctx, tmp_path):
    clone_ctx.resume = True
    clone_ctx.state_file.write_text(json.dumps({"target": "/dev/sda"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        ssd_clone.ensure_state_ready(clone_ctx)


def test_ensure_state_ready_requires_resume_for_existing_state(clone_ctx):
    clone_ctx.state_file.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        ssd_clone.ensure_state_ready(clone_ctx)


def test_ensure_state_ready_initializes_state_when_missing(tmp_path):
    ctx = ssd_clone.CloneContext(
        target_disk="/dev/sdy",
        dry_run=False,
        verbose=False,
        resume=False,
        state_file=tmp_path / "state.json",
    )
    ctx.mount_root = tmp_path / "mnt"
    ssd_clone.ensure_state_ready(ctx)
    assert ctx.state["target"] == "/dev/sdy"
    assert ctx.state_file.exists()


def test_finalize_writes_marker_and_updates_state(clone_ctx, tmp_path, monkeypatch):
    done_file = tmp_path / "done"
    monkeypatch.setattr(ssd_clone, "DONE_FILE", done_file)

    ssd_clone.finalize(clone_ctx)

    assert done_file.read_text(encoding="utf-8") == "Clone completed\n"
    assert clone_ctx.state["completed"]["finalize"] is True
