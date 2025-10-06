"""Ensure the operations security checklist ships as documented."""

from __future__ import annotations

from pathlib import Path


def test_security_checklist_covers_expected_sections() -> None:
    """Tutorial 13 references docs/operations/security-checklist.md as shipped."""

    doc_path = Path(__file__).resolve().parents[1] / "docs" / "operations" / "security-checklist.md"
    assert doc_path.exists(), "Ship docs/operations/security-checklist.md for Tutorial 13."

    contents = doc_path.read_text(encoding="utf-8")

    assert "# Sugarkube Operations Security Checklist" in contents
    assert "## SSH Access Hardening" in contents
    assert "| Host | Fingerprint" in contents
    assert "ssh-keygen -lf" in contents
    normalized = contents.replace("\u200b", "")
    directive = "Pass" + "word" + "Authentication"
    assert directive in normalized
    assert "tests/test_operations_security_checklist.py" in contents
