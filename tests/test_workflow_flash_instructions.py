from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "workflow_flash_instructions.py"
SPEC = importlib.util.spec_from_file_location("workflow_flash_instructions", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://github.com/futuroptimist/sugarkube/actions/runs/123456789",
            MODULE.WorkflowInfo("futuroptimist", "sugarkube", "123456789"),
        ),
        (
            "https://github.com/futuroptimist/sugarkube/actions/runs/987654321/attempts/3",
            MODULE.WorkflowInfo("futuroptimist", "sugarkube", "987654321"),
        ),
        (
            "https://github.com/futuroptimist/sugarkube/actions/workflows/"
            "pi-image-release.yml/runs/555",
            MODULE.WorkflowInfo("futuroptimist", "sugarkube", "555"),
        ),
    ],
)
def test_parse_workflow_url_variants(url: str, expected: MODULE.WorkflowInfo) -> None:
    assert MODULE.parse_workflow_url(url) == expected


def test_parse_workflow_url_rejects_invalid() -> None:
    with pytest.raises(MODULE.WorkflowFlashError):
        MODULE.parse_workflow_url("")
    with pytest.raises(MODULE.WorkflowFlashError):
        MODULE.parse_workflow_url("https://example.com/not-a-run")


@pytest.mark.parametrize("os_key", ["linux", "mac", "windows"])
def test_instructions_include_run_id(os_key: str) -> None:
    info = MODULE.WorkflowInfo("owner", "repo", "111")
    steps = MODULE.instructions_for(os_key, info)
    flattened = "\n".join(
        [line for step in steps for line in ([step["title"], *step["body"], *step["commands"]])]
    )
    assert "111" in flattened
    assert "owner/repo" in MODULE.render_text(os_key, info)


def test_instructions_reject_unknown_os() -> None:
    info = MODULE.WorkflowInfo("owner", "repo", "111")
    with pytest.raises(MODULE.WorkflowFlashError):
        MODULE.instructions_for("solaris", info)


def test_render_text_orders_steps() -> None:
    info = MODULE.WorkflowInfo("owner", "repo", "222")
    text = MODULE.render_text("linux", info)
    lines = text.splitlines()
    first_step = next(line for line in lines if line.startswith("1. "))
    assert first_step.startswith("1. ")
    assert "Platform   :" in text


def test_cli_json_output() -> None:
    run = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--url",
            "https://github.com/futuroptimist/sugarkube/actions/runs/222",
            "--os",
            "linux",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(run.stdout)
    assert payload["workflow"]["run_id"] == "222"
    assert payload["platform"]["key"] == "linux"
    assert payload["steps"]


def test_cli_text_output() -> None:
    run = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--url",
            "https://github.com/futuroptimist/sugarkube/actions/runs/333",
            "--os",
            "mac",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Run URL" in run.stdout
    assert "Platform" in run.stdout


def test_cli_reports_errors() -> None:
    run = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--url",
            "not-a-url",
            "--os",
            "linux",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2
    assert "error" in run.stderr.lower()
