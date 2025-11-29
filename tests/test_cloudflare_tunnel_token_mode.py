"""Guards for Cloudflare token-mode deployment logic and docs."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import textwrap
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
            if line and not line[0].isspace() and line.strip() not in {')', 'EOF', 'PATCH'}:
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
        r"deployment_patch.*?<<-?'PATCH'.*?\n[ \t]*(?P<patch>\[.*\])\n[ \t]*PATCH",
        cf_recipe_body,
        re.S,
    )
    if not match:
        match = re.search(
            r"deployment_patch=\$?'(?P<patch>\[.*\])'",
            cf_recipe_body,
            re.S,
        )

    assert match, "Deployment patch declaration missing from cf-tunnel-install"

    patch_text = match.group("patch")
    if "\\n" in patch_text:
        patch_text = patch_text.encode("utf-8").decode("unicode_escape")

    return json.loads(patch_text)


def test_cf_tunnel_install_heredocs_are_well_formed(cf_recipe_body: str) -> None:
    body = cf_recipe_body.splitlines()

    opening_counts: dict[str, int] = {}
    terminator_counts: dict[str, int] = {}
    terminator_allows_tabs: dict[str, bool] = {}

    for line in body:
        line_stripped = line.strip()
        eof_opening = re.search(r"<<-?['\"]?EOF['\"]?", line)
        patch_opening = re.search(r"<<-?['\"]?PATCH['\"]?", line)

        if eof_opening:
            opening_counts["EOF"] = opening_counts.get("EOF", 0) + 1
            if "-" in eof_opening.group(0):
                terminator_allows_tabs["EOF"] = True
        if patch_opening:
            opening_counts["PATCH"] = opening_counts.get("PATCH", 0) + 1
            if "-" in patch_opening.group(0):
                terminator_allows_tabs["PATCH"] = True
        if line_stripped == "EOF":
            terminator_counts["EOF"] = terminator_counts.get("EOF", 0) + 1
        if line_stripped == "PATCH":
            terminator_counts["PATCH"] = terminator_counts.get("PATCH", 0) + 1

    for terminator, expected_count in opening_counts.items():
        actual_count = terminator_counts.get(terminator, 0)
        assert actual_count == expected_count, (
            f"Expected {expected_count} {terminator!r} terminators but found {actual_count}"
        )
        allow_tabs = terminator_allows_tabs.get(terminator, False)
        assert not any(
            _terminator_has_invalid_whitespace(line, terminator, allow_tabs) for line in body
        ), (
            f"Terminator {terminator!r} must not be indented or have trailing whitespace"
        )


def _terminator_has_invalid_whitespace(line: str, terminator: str, allow_tabs: bool) -> bool:
    stripped = line.strip()
    if stripped != terminator:
        return False

    if line.rstrip("\t ") != stripped:
        return True

    prefix = line[: len(line) - len(stripped)]
    if not allow_tabs:
        return prefix != ""

    return any(ch != "\t" for ch in prefix)


def test_cf_tunnel_install_shell_syntax_is_valid(cf_recipe_body: str) -> None:
    script = textwrap.dedent(
        """#!/usr/bin/env bash
        set -euo pipefail

        # Dummy env so expansions don't blow up under bash -n
        printf -v CF_TUNNEL_TOKEN '%s' "example-token"
        printf -v CF_TUNNEL_NAME '%s' "dummy"
        env="dev"

        # Dummy helm/kubectl that never run under bash -n, but define the names
        helm() { :; }
        kubectl() { :; }

        """
    ) + cf_recipe_body + "\n"

    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(script)
        path = f.name

    try:
        result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        assert (
            result.returncode == 0
        ), f"bash -n failed for cf-tunnel-install script: {result.stderr}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_configmap_creation_removed_in_token_mode(cf_recipe_body: str) -> None:
    assert "configmap_yaml" not in cf_recipe_body
    assert "kind: ConfigMap" not in cf_recipe_body
    assert "config.yaml" not in cf_recipe_body


def test_deployment_patch_enforces_token_mode(deployment_patch_ops: list[dict]) -> None:
    ops_by_path = {op["path"]: op for op in deployment_patch_ops}

    volumes = ops_by_path.get("/spec/template/spec/volumes")
    assert volumes and volumes.get("op") == "replace"
    assert volumes.get("value") == []

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
    assert command_op.get("value") == [
        "cloudflared",
        "tunnel",
        "--no-autoupdate",
        "--metrics",
        "0.0.0.0:2000",
        "run",
    ]

    args_op = ops_by_path.get("/spec/template/spec/containers/0/args")
    assert args_op and args_op.get("op") in {"add", "replace"}
    args = args_op.get("value") or []
    assert args == []

    volume_mounts = ops_by_path.get("/spec/template/spec/containers/0/volumeMounts")
    assert volume_mounts and volume_mounts.get("op") in {"add", "replace"}
    assert volume_mounts.get("value") == []

    image_op = ops_by_path.get("/spec/template/spec/containers/0/image")
    assert image_op and image_op.get("op") in {"add", "replace"}
    assert image_op.get("value") == "cloudflare/cloudflared:2024.8.3"


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


def test_deployment_patch_does_not_reference_credentials_file(deployment_patch_ops: list[dict]) -> None:
    patch_text = json.dumps(deployment_patch_ops)
    assert "credentials.json" not in patch_text
    assert "creds" not in patch_text
    assert "/etc/cloudflared/config" not in patch_text
    assert "cloudflare-tunnel-config" not in patch_text


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

    assert (
        "cloudflared tunnel --no-autoupdate run --token" in text
    ), "Docs should call out the no-autoupdate token snippet"
    assert "CF_TUNNEL_TOKEN" in text, "Docs should tie CF_TUNNEL_TOKEN to the connector snippet"


def test_cf_tunnel_install_validates_token_shape(cf_recipe_body: str) -> None:
    assert "CF_TUNNEL_TOKEN" in cf_recipe_body
    assert "token_len=" in cf_recipe_body
    assert "appears too short" in cf_recipe_body
    assert "does not look like a JWT" in cf_recipe_body


def test_cf_tunnel_install_flags_origin_cert_logs(cf_recipe_body: str) -> None:
    assert "Cannot determine default origin certificate path" in cf_recipe_body
    assert "behaving like a locally-managed tunnel" in cf_recipe_body
    assert "config_src=\"cloudflare\"" in cf_recipe_body
    assert "cloudflared tunnel --no-autoupdate run --token <TOKEN>" in cf_recipe_body


def test_reset_and_debug_recipes_exist_and_reset_is_safe() -> None:
    reset_body = _extract_recipe_body("cf-tunnel-reset")
    debug_body = _extract_recipe_body("cf-tunnel-debug")

    assert "kubectl -n cloudflare delete deploy cloudflare-tunnel" in reset_body
    assert "kubectl -n cloudflare delete pod -l app.kubernetes.io/name=cloudflare-tunnel" in reset_body
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
    assert "No ConfigMap created in token-only mode" in debug_body


def test_debug_recipe_surfaces_origin_cert_guidance() -> None:
    debug_body = _extract_recipe_body("cf-tunnel-debug")

    assert "behaving like a locally-managed tunnel" in debug_body
    assert "config_src=\"cloudflare\"" in debug_body
