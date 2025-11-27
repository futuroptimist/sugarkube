"""Guardrail tests to ensure critical dspace documentation and recipes remain."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"
CLOUDFLARE_DOC = REPO_ROOT / "docs" / "cloudflare_tunnel.md"
RASPI_OPERATIONS_DOC = REPO_ROOT / "docs" / "raspi_cluster_operations.md"
DSPACE_APP_DOC = REPO_ROOT / "docs" / "apps" / "dspace.md"


def test_dspace_just_recipes_survive() -> None:
    assert DSPACE_APP_DOC.exists(), "dspace app guide vanished."

    text = JUSTFILE.read_text(encoding="utf-8")
    phrases = (
        "helm-oci-install",
        "helm-oci-upgrade",
    )

    for phrase in phrases:
        assert phrase in text, "`just` app helpers should stay available for dspace rollouts."

    dspace_doc = DSPACE_APP_DOC.read_text(encoding="utf-8")
    for phrase in ("just helm-oci-install", "just helm-oci-upgrade"):
        assert phrase in dspace_doc, "dspace quickstart should keep its just-based workflows."


def test_cloudflare_tunnel_doc_and_recipe_remain() -> None:
    assert CLOUDFLARE_DOC.exists(), "Cloudflare Tunnel guide vanished."

    text = JUSTFILE.read_text(encoding="utf-8")
    for phrase in ("cf-tunnel-install", "cloudflare-tunnel"):
        assert phrase in text, "Cloudflare Tunnel just recipes should remain discoverable."

    operations_text = RASPI_OPERATIONS_DOC.read_text(encoding="utf-8")
    assert "cloudflare_tunnel.md" in operations_text, "Operations guide should reference the Cloudflare Tunnel documentation."

    doc_text = CLOUDFLARE_DOC.read_text(encoding="utf-8")
    for phrase in (
        "TUNNEL_TOKEN",
        "token-based",
        "CF_TUNNEL_NAME",
        "credentials.json",
    ):
        assert phrase in doc_text, f"Cloudflare doc should mention {phrase} token workflow."


def test_raspi_operations_dspace_onboarding_persists() -> None:
    operations_text = RASPI_OPERATIONS_DOC.read_text(encoding="utf-8")

    for phrase in ("## Step 4: Deploy dspace", "helm upgrade --install dspace"):
        assert phrase in operations_text, f"Operations guide should retain '{phrase}' for dspace onboarding."
