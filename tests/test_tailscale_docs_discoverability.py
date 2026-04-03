"""Guardrails for Tailscale remote-ops docs discoverability."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_design_doc_is_linked_from_primary_indexes() -> None:
    docs_index = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    software_index = (REPO_ROOT / "docs" / "software" / "index.md").read_text(encoding="utf-8")

    expected_link = "design/tailscale-remote-ops.md"
    assert expected_link in docs_index
    assert "../design/tailscale-remote-ops.md" in software_index


def test_operations_guide_surfaces_tailscale_remote_ops_entrypoint() -> None:
    operations = (REPO_ROOT / "docs" / "raspi_cluster_operations.md").read_text(encoding="utf-8")

    assert "Optional: Tailscale remote operations" in operations
    assert "just tailscale-install" in operations
    assert "TS_AUTHKEY_FILE=" in operations
