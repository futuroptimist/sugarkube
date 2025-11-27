"""Guardrails for cf-tunnel-install token-mode behavior."""

from __future__ import annotations

from pathlib import Path
import re
import textwrap

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _extract_recipe_body(target: str) -> list[str]:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    capture = False
    body: list[str] = []
    header_re = re.compile(r"^[A-Za-z0-9_.-].*:\s*$")
    prefixes = (f"{target}:", f"{target} ")
    for line in lines:
        if capture:
            if header_re.match(line) and not line.startswith("    "):
                break
            if line.startswith("#") and not line.startswith("    "):
                break
            body.append(line[4:] if line.startswith("    ") else line)
            continue
        if any(line.startswith(prefix) for prefix in prefixes):
            capture = True
    if not body:
        pytest.fail(f"Recipe {target} missing from justfile")
    return body


def _extract_block(body: list[str], start: str, end: str) -> str:
    capture = False
    lines: list[str] = []
    for line in body:
        if capture:
            if line == end:
                break
            lines.append(line)
            continue
        if line.startswith(start):
            capture = True
    if not lines:
        pytest.fail(f"Block starting with {start!r} missing from recipe")
    return "\n".join(lines)


def test_cf_tunnel_install_uses_token_mode() -> None:
    body = _extract_recipe_body("cf-tunnel-install")
    body_text = "\n".join(body)

    assert "--wait" not in body_text, "Helm readiness should not block token-mode patching"
    assert (
        "rollout status deployment/cloudflare-tunnel --timeout=180s" in body_text
    ), "Rollout gate should be kubectl rollout status"

    config_block = _extract_block(body, "configmap_yaml=$(cat <<'YAML'", "YAML")
    config_text = config_block.replace('\\"', '"')

    assert "credentials-file" not in config_text
    assert "metrics: 0.0.0.0:2000" in config_text
    assert "warp-routing:" in config_text

    deployment_block = _extract_block(
        body, "read -r -d '' deployment_patch <<'PATCH' || true", "PATCH"
    )
    deployment_text = textwrap.dedent(deployment_block)

    assert '"name":"TUNNEL_TOKEN"' in deployment_text
    assert '--token "$TUNNEL_TOKEN"' in deployment_text
    assert '"command":["/bin/sh","-c"]' in deployment_text
    assert '"creds"' not in deployment_text
