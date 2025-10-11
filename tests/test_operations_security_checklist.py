"""Ensure the operations security checklist delivers the promised guidance."""

from __future__ import annotations

from pathlib import Path


def test_operations_security_checklist_exists_and_guides_rotations() -> None:
    """Tutorial 13 references the checklist; it must exist with key sections."""

    checklist = Path("docs/operations/security-checklist.md")
    text = checklist.read_text(encoding="utf-8")

    assert "# Sugarkube Operations Security Checklist" in text
    assert "## Rotation Checklist" in text
    assert "ssh-keygen -lf" in text, "Fingerprint capture guidance missing"
    assert (
        "~/sugarkube-labs/tutorial-13/operations/security-checklist.md" in text
    ), "Tutorial 13 run log location missing"
    assert "## Verification Checklist" in text
    assert "| Date | Host | Fingerprint | Method | Notes |" in text
    assert "## Evidence Log" in text
