"""Ensure the NVMe health workflow is wired through automation wrappers."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "nvme_health_check.sh"
DOC_PATH = REPO_ROOT / "docs" / "nvme-health-check.md"


def test_nvme_health_script_exists() -> None:
    """Ship the documented nvme-health-check helper with the repository."""

    assert (
        SCRIPT_PATH.exists()
    ), "Add scripts/nvme_health_check.sh so docs no longer require a manual copy"


def test_justfile_exposes_nvme_health_recipe() -> None:
    """The justfile should delegate nvme-health to the unified CLI."""

    justfile_text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert (
        "nvme-health:" in justfile_text
    ), "Expose a nvme-health recipe so contributors can run checks via just"
    assert (
        '"{{sugarkube_cli}}" nvme health' in justfile_text
    ), "Route the nvme-health recipe through the sugarkube CLI wrapper"
    assert (
        '"{{ sugarkube_cli }}" nvme health' not in justfile_text
    ), "Whitespace inside moustache braces hides CLI detection logic"


def test_makefile_exposes_nvme_health_target() -> None:
    """Make parity keeps the docs accurate for alternate task runners."""

    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert (
        "nvme-health:" in makefile_text
    ), "Add an nvme-health target so docs mirror the shipped helper"
    assert (
        "$(SUGARKUBE_CLI) nvme health" in makefile_text
    ), "Make nvme-health target should invoke the sugarkube CLI"


def test_taskfile_exposes_nvme_health_task() -> None:
    """Task users should gain the same nvme health integration."""

    taskfile_text = (REPO_ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    assert (
        "{{.SUGARKUBE_CLI}} nvme health" in taskfile_text
    ), "Taskfile should delegate NVMe health checks to the sugarkube CLI"


def test_nvme_health_doc_references_cli_wrappers() -> None:
    """The doc should advertise the shipped CLI integrations."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "`sugarkube nvme health`" in text
    ), "Document the sugarkube CLI helper so readers do not recreate the script"
    assert (
        "just nvme-health" in text
    ), "Document the just wrapper so automation matches the guide"
    assert (
        "just nvme-alerts" not in text
    ), "Future enhancements should no longer list just nvme-health as unshipped"
