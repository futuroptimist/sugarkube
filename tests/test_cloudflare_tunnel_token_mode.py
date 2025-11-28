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

    return _extract_recipe_body("cf-tunnel-install")


def _extract_recipe_body(name: str) -> str:
    """Return the body of the given recipe name (including indented lines)."""

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
        if line.startswith(f"{name} ") or line.startswith(f"{name}:"):
            capture = True
    if not body:
        pytest.fail(f"{name} recipe missing from justfile")
    return "\n".join(body)


@pytest.fixture(scope="module")
def cf_recipe_body() -> str:
    return _extract_cf_recipe_body()


@pytest.fixture(scope="module")
def deployment_patch_ops(cf_recipe_body: str) -> list[dict]:
    """Extract and parse the deployment patch JSON patch payload."""

    match = re.search(
        r"deployment_patch.*?<<'PATCH'.*?\n[ \t]*(?P<patch>\[.*\])\n[ \t]*PATCH",
        cf_recipe_body,
        re.S,
    )
    assert match, "Deployment patch heredoc missing from cf-tunnel-install"
    return json.loads(match.group("patch"))


def test_configmap_patch_strips_credentials_file(cf_recipe_body: str) -> None:
    configmap_regex = (
        r"configmap_yaml=\$\(cat <<-?'?EOF'?\n(?P<body>.*?)\n"
        r"[ \t]*EOF"
    )
    match = re.search(configmap_regex, cf_recipe_body, re.S)
    assert match, "ConfigMap heredoc missing from cf-tunnel-install"

    config_yaml = match.group("body")
    expected = """
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: cloudflare-tunnel
      namespace: cloudflare
    data:
      config.yaml: |
        tunnel: "${CF_TUNNEL_NAME:-sugarkube-{{ env }}}"
        warp-routing:
          enabled: false
        metrics: 0.0.0.0:2000
        no-autoupdate: true
        ingress:
          - service: http_status:404
    """
    assert config_yaml.strip() == expected.strip()
    assert "credentials-file" not in config_yaml
    assert "secret containing" not in config_yaml


def test_deployment_patch_enforces_token_mode(deployment_patch_ops: list[dict]) -> None:
    ops_by_path = {op["path"]: op for op in deployment_patch_ops}

    volumes = ops_by_path.get("/spec/template/spec/volumes")
    assert volumes and volumes.get("op") == "replace"
    volume_list = volumes.get("value")
    assert isinstance(volume_list, list)
    assert volume_list == []

    env_op = ops_by_path.get("/spec/template/spec/containers/0/env")
    assert env_op and env_op.get("op") in {"add", "replace"}
    assert env_op.get("value") == [
        {
            "name": "TUNNEL_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": "tunnel-token", "key": "token"}},
        }
    ]

    command_op = ops_by_path.get("/spec/template/spec/containers/0/command")
    assert command_op and command_op.get("op") in {"add", "replace"}
    assert command_op.get("value") == ["/bin/sh", "-c"]

    args_op = ops_by_path.get("/spec/template/spec/containers/0/args")
    assert args_op and args_op.get("op") in {"add", "replace"}
    args = args_op.get("value") or []
    assert args == [
        (
            "exec cloudflared tunnel --no-autoupdate --metrics 0.0.0.0:2000 run "
            '--token "$TUNNEL_TOKEN"'
        )
    ]

    volume_mounts = ops_by_path.get("/spec/template/spec/containers/0/volumeMounts")
    assert volume_mounts and volume_mounts.get("op") in {"add", "replace"}
    mounts = volume_mounts.get("value") or []
    assert mounts == []


def test_recipe_relies_on_rollout_status_not_helm_wait(cf_recipe_body: str) -> None:
    assert (
        "kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=180s"
        in cf_recipe_body
    )
    assert "helm upgrade --install cloudflare-tunnel" in cf_recipe_body
    assert "--wait" not in cf_recipe_body


def test_teardown_retry_is_baked_into_cf_tunnel_install(cf_recipe_body: str) -> None:
    assert (
        "kubectl -n cloudflare delete pod -l app.kubernetes.io/name=cloudflare-tunnel"
        in cf_recipe_body
    )

    rollout_calls = re.findall(
        r"kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=\d+s",
        cf_recipe_body,
    )
    assert len(rollout_calls) >= 2, "Expected two rollout status calls (initial + retry)"
    assert "cloudflare-tunnel still failing after teardown+retry" in cf_recipe_body
    assert "exit 1" in cf_recipe_body


def test_deployment_patch_does_not_reference_credentials_file(
    deployment_patch_ops: list[dict],
) -> None:
    patch_text = json.dumps(deployment_patch_ops)
    assert "credentials.json" not in patch_text
    assert "creds" not in patch_text
    assert "/etc/cloudflared/config" not in patch_text


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


def test_reset_and_debug_recipes_exist_and_reset_is_safe() -> None:
    reset_body = _extract_recipe_body("cf-tunnel-reset")
    debug_body = _extract_recipe_body("cf-tunnel-debug")

    assert "kubectl -n cloudflare delete deploy cloudflare-tunnel" in reset_body
    assert (
        "kubectl -n cloudflare delete pod -l app.kubernetes.io/name=cloudflare-tunnel"
        in reset_body
    )
    assert "helm -n cloudflare uninstall cloudflare-tunnel" in reset_body

    # Secret deletion must remain optional/commented.
    for line in reset_body.splitlines():
        if "delete secret tunnel-token" in line:
            assert line.strip().startswith("#"), "Secret deletion should be commented/optional"

    assert (
        "kubectl -n cloudflare get deploy,po -l app.kubernetes.io/name=cloudflare-tunnel"
        in debug_body
    )
    assert "kubectl -n cloudflare logs \"$POD\" --tail=50" in debug_body
