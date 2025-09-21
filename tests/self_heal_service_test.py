import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "self_heal_service.py"


def _run(
    unit: str,
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "SELF_HEAL_STATE_DIR": str(tmp_path / "state"),
            "SELF_HEAL_BOOT_DIR": str(tmp_path / "boot"),
            "SELF_HEAL_LOG_DIR": str(tmp_path / "logs"),
            "SELF_HEAL_TEST_MODE": "1",
        }
    )
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--unit", unit],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result


def _load_state(tmp_path: Path, unit: str) -> dict:
    state_file = tmp_path / "state" / f"{unit}.json"
    assert state_file.exists()
    with state_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_projects_compose_success(tmp_path: Path) -> None:
    result = _run("projects-compose.service", tmp_path)
    assert result.returncode == 0

    state = _load_state(tmp_path, "projects-compose.service")
    assert state["attempts"] == 0

    log_file = tmp_path / "logs" / "projects-compose.service.log"
    contents = log_file.read_text(encoding="utf-8")
    assert "recovery succeeded" in contents
    assert "docker compose" in contents


def test_projects_compose_escalates_after_threshold(tmp_path: Path) -> None:
    env = {
        "SELF_HEAL_MAX_ATTEMPTS": "2",
        "SELF_HEAL_TEST_FAILURES": "systemctl is-active projects-compose",
    }
    first = _run("projects-compose.service", tmp_path, env)
    assert first.returncode == 1
    state = _load_state(tmp_path, "projects-compose.service")
    assert state["attempts"] == 1

    boot_dir = tmp_path / "boot"
    assert not list(boot_dir.glob("*.md"))

    second = _run("projects-compose.service", tmp_path, env)
    assert second.returncode == 1
    state = _load_state(tmp_path, "projects-compose.service")
    assert state["attempts"] == 2

    summaries = list(boot_dir.glob("*.md"))
    assert summaries, "expected escalation summary to be written"
    summary_text = summaries[0].read_text(encoding="utf-8")
    assert "Self-heal escalation" in summary_text

    log_file = tmp_path / "logs" / "projects-compose.service.log"
    contents = log_file.read_text(encoding="utf-8")
    assert "entering maintenance" in contents


@pytest.mark.parametrize(
    "unit",
    ["cloud-final.service", "cloud-config.service", "cloud-init.service"],
)
def test_cloud_init_recipes_run(unit: str, tmp_path: Path) -> None:
    result = _run(unit, tmp_path)
    assert result.returncode == 0

    state = _load_state(tmp_path, unit)
    assert state["attempts"] == 0

    log_file = tmp_path / "logs" / f"{unit}.log"
    contents = log_file.read_text(encoding="utf-8")
    assert "cloud-init clean --logs" in contents
    assert "status: done" in contents


def test_command_runner_allows_timeout_overrides(monkeypatch, tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("self_heal_service_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.delenv("SELF_HEAL_TEST_MODE", raising=False)
    logger = module.SelfHealLogger(tmp_path / "logs" / "timeout.log")
    runner = module.CommandRunner(logger)
    assert runner.test_mode is False

    timeouts: list[float | int | None] = []

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        timeouts.append(kwargs.get("timeout"))
        return _Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    runner.run(["echo", "default"])
    runner.run(["echo", "override"], timeout=5)
    runner.run(["echo", "none"], timeout=None)

    assert timeouts == [None, 5, None]
