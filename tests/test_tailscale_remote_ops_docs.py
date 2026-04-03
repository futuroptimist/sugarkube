"""Guardrails for Tailscale remote-operations discoverability and recipe coverage."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"
DESIGN_DOC = REPO_ROOT / "docs" / "design" / "tailscale-remote-ops.md"
SOFTWARE_INDEX = REPO_ROOT / "docs" / "software" / "index.md"


def test_tailscale_recipes_exist_in_justfile() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    for recipe in (
        "tailscale-install:",
        "tailscale-up auth_key='':",
        "tailscale-status:",
        "tailscale-ssh-check target:",
    ):
        assert recipe in text, f"Missing just recipe: {recipe}"



def test_design_doc_contains_quick_reference_and_failure_modes() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "## Operator quick reference" in text
    assert "## Failure modes and remediation" in text
    assert "just tailscale-ssh-check" in text



def test_tailscale_doc_is_discoverable_from_core_indexes() -> None:
    expected_link = "design/tailscale-remote-ops.md"
    # docs/index.md has linked this design page prior to this PR; keep the regression
    # guard focused on the new discoverability path added under docs/software/.
    assert expected_link in SOFTWARE_INDEX.read_text(encoding="utf-8")
