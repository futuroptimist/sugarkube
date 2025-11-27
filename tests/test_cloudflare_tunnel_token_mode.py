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
def deployment_patch_json(cf_recipe_body: str) -> str:
    """Extract the deployment patch JSON from the cf-tunnel-install recipe."""
    match = re.search(
        r"deployment_patch=\$\(cat <<-?'PATCH'\n(?P<patch>.*?)\n[ \t]*PATCH\n[ \t]*\)\n",
        cf_recipe_body,
        re.S,
    )
    assert match, "Deployment patch heredoc missing from cf-tunnel-install"
    return match.group("patch")


def test_configmap_patch_strips_credentials_file(cf_recipe_body: str) -> None:
    match = re.search(r"configmap_yaml=\$\(cat <<-?'?EOF'?\n(?P<body>.*?)\n[ \t]*EOF", cf_recipe_body, re.S)
    assert match, "ConfigMap heredoc missing from cf-tunnel-install"

    config_yaml = match.group("body")
    assert "credentials-file" not in config_yaml
    for phrase in (
        "tunnel: \"${CF_TUNNEL_NAME:-sugarkube-{{ env }}}\"",
        "metrics: 0.0.0.0:2000",
        "service: http_status:404",
    ):
        assert phrase in config_yaml, f"Missing expected config fragment: {phrase!r}"


def test_deployment_patch_enforces_token_mode(deployment_patch_json: str) -> None:
    patch = json.loads(deployment_patch_json)
    container = patch["spec"]["template"]["spec"]["containers"][0]

    env_vars = {env["name"]: env for env in container.get("env", [])}
    assert "TUNNEL_TOKEN" in env_vars
    ref = env_vars["TUNNEL_TOKEN"].get("valueFrom", {}).get("secretKeyRef", {})
    assert ref.get("name") == "tunnel-token"
    assert ref.get("key") == "token"

    assert container.get("command") == ["/bin/sh", "-c"]
    args = container.get("args", [])
    assert args and "--token \"$TUNNEL_TOKEN\"" in args[0]

    volume_mounts = container.get("volumeMounts", [])
    mount_names = {mount["name"] for mount in volume_mounts}
    assert mount_names == {"cloudflare-tunnel-config"}

    volumes = patch["spec"]["template"]["spec"].get("volumes", [])
    volume_names = {vol["name"] for vol in volumes}
    assert volume_names == {"cloudflare-tunnel-config"}


def test_recipe_relies_on_rollout_status_not_helm_wait(cf_recipe_body: str) -> None:
    assert "rollout status deployment/cloudflare-tunnel" in cf_recipe_body
    assert "--wait" not in cf_recipe_body


def test_deployment_patch_does_not_reference_credentials_file(deployment_patch_json: str) -> None:
    assert "credentials.json" not in deployment_patch_json


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
