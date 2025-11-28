"""Guards for Cloudflare token-mode deployment logic and docs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"
CLOUDFLARE_DOC = REPO_ROOT / "docs" / "cloudflare_tunnel.md"


def _extract_cf_recipe_body() -> str:
    """Return the full body of the cf-tunnel-install recipe."""

    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    body: list[str] = []
    capture = False
    heredoc_end: str | None = None
    for line in lines:
        if capture:
            body.append(line)
            if heredoc_end:
                if line.strip() == heredoc_end:
                    heredoc_end = None
                continue
            if "<<EOF" in line:
                heredoc_end = "EOF"
                continue
            if "<<'PATCH'" in line:
                heredoc_end = "PATCH"
                continue
            if line and not line[0].isspace() and line.strip() not in {')'}:
                break
            continue
        if line.startswith("cf-tunnel-install"):
            capture = True
    if not body:
        pytest.fail("cf-tunnel-install recipe missing from justfile")
    return "\n".join(body)


@pytest.fixture(scope="module")
def cf_recipe_body() -> str:
    return _extract_cf_recipe_body()


@pytest.fixture(scope="module")
def deployment_patch_text(cf_recipe_body: str) -> str:
    match = re.search(
        r"deployment_patch.*<<-?'PATCH'[^\n]*\n(?P<patch>.*?)\n[ \t]*PATCH",
        cf_recipe_body,
        re.S,
    )
    assert match, "Deployment patch heredoc missing from cf-tunnel-install"
    return match.group("patch")


@pytest.fixture(scope="module")
def deployment_patch(deployment_patch_text: str) -> dict:
    return json.loads(deployment_patch_text)


def test_configmap_patch_strips_credentials_file(cf_recipe_body: str) -> None:
    match = re.search(r"configmap_yaml=\$\(cat <<-?'?EOF'?\n(?P<body>.*?)\n[ \t]*EOF", cf_recipe_body, re.S)
    assert match, "ConfigMap heredoc missing from cf-tunnel-install"

    config_yaml = match.group("body")
    assert "credentials-file" not in config_yaml
    for phrase in (
        "tunnel: \"${CF_TUNNEL_NAME:-sugarkube-{{ env }}}\"",
        "warp-routing:",
        "metrics: 0.0.0.0:2000",
    ):
        assert phrase in config_yaml, f"Missing expected config fragment: {phrase!r}"


def test_deployment_patch_enforces_token_mode(deployment_patch: dict) -> None:
    spec = deployment_patch["spec"]["template"]["spec"]

    volumes = spec["volumes"]
    assert volumes == [
        {
            "name": "cloudflare-tunnel-config",
            "configMap": {
                "name": "cloudflare-tunnel",
                "items": [{"key": "config.yaml", "path": "config.yaml"}],
            },
        }
    ]

    containers = spec["containers"]
    assert len(containers) == 1
    container = containers[0]

    env_vars = container["env"]
    assert env_vars == [
        {
            "name": "TUNNEL_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": "tunnel-token", "key": "token"}},
        }
    ]

    assert container["command"] == ["/bin/sh", "-c"]

    args = container["args"]
    assert any("--token \"$TUNNEL_TOKEN\"" in arg for arg in args)

    volume_mounts = container["volumeMounts"]
    assert volume_mounts == [
        {
            "name": "cloudflare-tunnel-config",
            "mountPath": "/etc/cloudflared/config",
            "readOnly": True,
        }
    ]


def test_recipe_relies_on_rollout_status_not_helm_wait(cf_recipe_body: str) -> None:
    assert "rollout status deployment/cloudflare-tunnel --timeout=180s" in cf_recipe_body
    assert "--wait" not in cf_recipe_body


def test_deployment_patch_does_not_reference_credentials_file(
    deployment_patch_text: str, deployment_patch: dict
) -> None:
    assert "credentials.json" not in deployment_patch_text
    assert "\"name\": \"creds\"" not in deployment_patch_text

    spec = deployment_patch["spec"]["template"]["spec"]
    assert spec["volumes"][0]["name"] == "cloudflare-tunnel-config"


def test_cloudflare_tunnel_docs_call_out_token_mode() -> None:
    text = CLOUDFLARE_DOC.read_text(encoding="utf-8")
    for phrase in (
        "token-based connector mode",
        "CF_TUNNEL_NAME",
        "connector token (JWT)",
        "cloudflared tunnel run --token",
        "credentials.json",
    ):
        assert phrase in text, f"Documentation missing token-mode guidance: {phrase}"
