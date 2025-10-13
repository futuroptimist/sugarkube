"""Ensure the Taskfile mirrors core automation helpers and documentation."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKFILE = REPO_ROOT / "Taskfile.yml"
README = REPO_ROOT / "README.md"
START_HERE = REPO_ROOT / "docs" / "start-here.md"
CONTRIBUTOR_MAP = REPO_ROOT / "docs" / "contributor_script_map.md"
PI_QUICKSTART = REPO_ROOT / "docs" / "pi_image_quickstart.md"


def test_taskfile_exposes_cli_wrappers() -> None:
    """Key CLI wrappers should appear in the Taskfile."""

    text = TASKFILE.read_text(encoding="utf-8")
    expected_snippets = {
        "docs:verify": "{{.SUGARKUBE_CLI}} docs verify",
        "docs:simplify": "{{.SUGARKUBE_CLI}} docs simplify",
        "docs:start-here": "{{.SUGARKUBE_CLI}} docs start-here",
        "doctor": "{{.SUGARKUBE_CLI}} doctor",
        "pi:download": "{{.SUGARKUBE_CLI}} pi download",
        "pi:install": "{{.SUGARKUBE_CLI}} pi install",
        "pi:flash": "{{.SUGARKUBE_CLI}} pi flash",
        "pi:report": "{{.SUGARKUBE_CLI}} pi report",
        "pi:smoke": "{{.SUGARKUBE_CLI}} pi smoke",
        "pi:rehearse": "{{.SUGARKUBE_CLI}} pi rehearse",
        "pi:support-bundle": "{{.SUGARKUBE_CLI}} pi support-bundle",
        "pi:cluster": "{{.SUGARKUBE_CLI}} pi cluster",
        "notify:workflow": "{{.SUGARKUBE_CLI}} notify workflow",
        "mac:setup": "{{.PYTHON}} {{.MAC_SETUP_SCRIPT}}",
    }

    for task_name, snippet in expected_snippets.items():
        assert f"{task_name}:" in text, f"Taskfile should define {task_name}"
        assert snippet in text, f"Taskfile {task_name} command should include `{snippet}`"


def test_taskfile_includes_make_style_aliases() -> None:
    """Taskfile should mirror the download/install shortcuts documented in the README."""

    text = TASKFILE.read_text(encoding="utf-8")

    assert (
        "download-pi-image:" in text
    ), "Taskfile should expose a download-pi-image alias for go-task users"
    assert (
        "task: pi:download" in text
    ), "download-pi-image alias should delegate to the pi:download helper"

    assert (
        "install-pi-image:" in text
    ), "Taskfile should expose an install-pi-image alias for go-task users"
    assert (
        "task: pi:install" in text
    ), "install-pi-image alias should delegate to the pi:install helper"


def test_docs_reference_taskfile_shortcuts() -> None:
    """Docs should point readers to the Taskfile equivalents."""

    readme_text = README.read_text(encoding="utf-8")
    assert "task docs:verify" in readme_text
    assert "task docs:simplify" in readme_text
    assert "sudo task pi:flash" in readme_text

    start_here_text = START_HERE.read_text(encoding="utf-8")
    assert "task docs:start-here" in start_here_text

    contributor_map_text = CONTRIBUTOR_MAP.read_text(encoding="utf-8")
    assert "Taskfile.yml" in contributor_map_text
    assert "task docs:verify" in contributor_map_text

    quickstart_text = PI_QUICKSTART.read_text(encoding="utf-8")
    assert "task mac:setup" in quickstart_text
