"""Guards for Cloudflare token-mode deployment logic and docs."""

from __future__ import annotations

import json
import os
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


def _render_cf_recipe(env: str) -> str:
    """Render the recipe through Just, including all Just variable interpolation."""

    result = subprocess.run(
        ["just", "--dry-run", "cf-tunnel-install", f"env={env}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # Just writes dry-run recipes to stderr so command output can remain on stdout.
    return result.stderr


def _extract_cf_tunnel_route_recipe_body() -> str:
    """Return the full body of the cf-tunnel-route recipe."""

    return _extract_recipe_body("cf-tunnel-route")


@pytest.fixture(scope="module")
def origin_cert_guidance_text() -> str:
    just_text = JUSTFILE.read_text(encoding="utf-8")
    match = re.search(r"origin_cert_guidance := \"\"\"(?P<body>.*?)\"\"\"", just_text, re.S)
    assert match, "origin_cert_guidance helper missing from justfile"

    return match.group("body")


def _extract_recipe_body(name: str) -> str:
    """Return the body of the given recipe name (including indented lines)."""

    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    body: list[str] = []
    capture = False
    heredoc_end: str | None = None
    for line in lines:
        if capture:
            if heredoc_end:
                body.append(line)
                if line.strip() == heredoc_end:
                    heredoc_end = None
                continue
            if "<<EOF" in line:
                body.append(line)
                heredoc_end = "EOF"
                continue
            if "<<'PATCH'" in line:
                body.append(line)
                heredoc_end = "PATCH"
                continue
            if line and not line[0].isspace() and line.strip() not in {')', 'EOF', 'PATCH'}:
                break
            body.append(line)
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
def cf_tunnel_route_recipe_body() -> str:
    return _extract_cf_tunnel_route_recipe_body()


def _run_cf_tunnel_route_recipe(host: str) -> subprocess.CompletedProcess[str]:
    rendered_body = _extract_cf_tunnel_route_recipe_body().replace("{{ host }}", host)
    script = textwrap.dedent(
        """#!/usr/bin/env bash
        set -euo pipefail
        """
    ) + rendered_body + "\n"

    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(script)
        path = f.name

    try:
        return subprocess.run(["bash", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.parametrize("host_input", ["staging.token.place", "host=staging.token.place"])
def test_cf_tunnel_route_normalizes_host_prefix(host_input: str) -> None:
    result = _run_cf_tunnel_route_recipe(host_input)
    assert result.returncode == 0, result.stderr
    assert "Hostname: staging.token.place" in result.stdout


@pytest.fixture(scope="module")
def deployment_patch_ops(cf_recipe_body: str) -> list[dict]:
    """Extract and combine the common and staging JSON patch payloads."""

    payloads = re.findall(r"(?:deployment|staging)_patch=\$?'(?P<patch>\[.*?\])'", cf_recipe_body, re.S)
    assert len(payloads) == 2, "Common and staging patch declarations are required"
    return [operation for payload in payloads for operation in json.loads(payload)]


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
    script = _render_cf_recipe("dev")

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


def _run_cf_tunnel_install_recipe(
    env: str,
    *,
    secret_exists: bool = True,
    connector_value: str | None = "eyJ" + "synthetic-test-token",
) -> subprocess.CompletedProcess[str]:
    rendered_body = _render_cf_recipe(env)
    script = textwrap.dedent(
        """#!/usr/bin/env bash
        set -euo pipefail

        if [ {{TOKEN_SET}} = yes ]; then
            export CF_TUNNEL_TOKEN={{TOKEN}}
        fi
        helm() {
            printf 'HELM:%s\n' "$*"
            if [ ! -t 0 ]; then
                sed 's/^/HELM_STDIN:/' <&0
            fi
        }
        kubectl() {
            printf 'KUBECTL:%s\n' "$*"
            if [ "$*" = "-n cloudflare get secret tunnel-token -o name" ] && [ {{SECRET_EXISTS}} = no ]; then
                return 1
            fi
            if [ ! -t 0 ]; then
                sed 's/^/KUBECTL_STDIN:/' <&0 >/dev/null
            fi
            return 0
        }

        """
    ) + rendered_body + "\n"
    script = script.replace("{{SECRET_EXISTS}}", "yes" if secret_exists else "no")
    script = script.replace("{{TOKEN_SET}}", "yes" if connector_value is not None else "no")
    script = script.replace("{{TOKEN}}", json.dumps(connector_value or ""))

    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(script)
        path = f.name

    try:
        return subprocess.run(["bash", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)


def _run_actual_cf_tunnel_install(
    tmp_path: Path, *, secret_exists: bool
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run Just's fully rendered recipe against command-recording stubs."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"
    stub = textwrap.dedent(
        """#!/usr/bin/env bash
        set -Eeuo pipefail
        printf '%s:%s\n' "$(basename "$0")" "$*" >>"${CALL_LOG}"
        if [ "$(basename "$0")" = kubectl ]; then
            if [ "$*" = "-n cloudflare get secret tunnel-token -o name" ]; then
                [ "${SECRET_EXISTS}" = yes ]
                exit
            fi
            exit 0
        fi
        if [ "$*" = "-n cloudflare list --filter ^cloudflare-tunnel$ --output json" ]; then
            printf '[]\n'
        fi
        if [ "${1:-}" = upgrade ]; then
            cat >/dev/null
        fi
        """
    )
    for command in ("kubectl", "helm"):
        path = bin_dir / command
        path.write_text(stub, encoding="utf-8")
        path.chmod(0o755)

    environment = os.environ.copy()
    environment.pop("CF_TUNNEL_TOKEN", None)
    environment.pop("CF_TUNNEL_NAME", None)
    environment.pop("CF_TUNNEL_ID", None)
    environment.update(
        {
            "CALL_LOG": str(call_log),
            "HOME": str(tmp_path),
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "SECRET_EXISTS": "yes" if secret_exists else "no",
        }
    )
    result = subprocess.run(
        ["just", "cf-tunnel-install", "env=staging"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    return result, call_log.read_text(encoding="utf-8") if call_log.exists() else ""


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
    assert image_op.get("value") == (
        "cloudflare/cloudflared:2026.7.3@"
        "sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
    )

    assert ops_by_path["/spec/template/spec/containers/0/livenessProbe"]["op"] == "remove"
    readiness = ops_by_path["/spec/template/spec/containers/0/readinessProbe"]["value"]
    assert readiness["httpGet"] == {"path": "/ready", "port": 2000}
    assert readiness["failureThreshold"] == 3
    assert ops_by_path["/spec/strategy"]["value"]["rollingUpdate"] == {
        "maxUnavailable": 0,
        "maxSurge": 1,
    }
    assert ops_by_path["/spec/template/spec/affinity"]["value"] == {
        "podAntiAffinity": {
            "requiredDuringSchedulingIgnoredDuringExecution": [
                {
                    "topologyKey": "kubernetes.io/hostname",
                    "labelSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "cloudflare-tunnel",
                            "app.kubernetes.io/instance": "cloudflare-tunnel",
                        }
                    },
                }
            ]
        }
    }


def test_recipe_relies_on_rollout_status_not_helm_wait(cf_recipe_body: str) -> None:
    assert (
        "kubectl -n cloudflare rollout status deployment/cloudflare-tunnel --timeout=180s"
        in cf_recipe_body
    )
    assert "helm upgrade --install cloudflare-tunnel" in cf_recipe_body
    assert "--wait" not in cf_recipe_body


def test_failed_rollout_never_deletes_both_connectors(cf_recipe_body: str) -> None:
    assert (
        "kubectl -n cloudflare delete pod -l app.kubernetes.io/name=cloudflare-tunnel"
        not in cf_recipe_body
    )
    assert "synchronize their restart backoff" in cf_recipe_body
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


def test_cf_tunnel_install_normalizes_named_env_arguments(cf_recipe_body: str) -> None:
    # Outage regression: during 2026-05-18 staging recovery, `env=staging`
    # was propagated literally into the tunnel name (`sugarkube-env=staging`).
    assert "env_input={{ quote(env) }}" in cf_recipe_body
    assert 'while [ "${env_name#env=}" != "${env_name}" ]; do' in cf_recipe_body
    assert 'env_name="${env_name#env=}"' in cf_recipe_body
    assert 'if [ "${env_name}" = "int" ]; then' in cf_recipe_body
    assert 'env_name="staging"' in cf_recipe_body

    runtime_cases = {
        "staging": "staging",
        "env=staging": "staging",
        "env=env=staging": "staging",
        "int": "staging",
    }

    for supplied_env, normalized_env in runtime_cases.items():
        result = _run_cf_tunnel_install_recipe(supplied_env)
        assert result.returncode == 0, result.stderr

        combined_output = result.stdout + result.stderr
        assert re.search(
            r"HELM:upgrade --install cloudflare-tunnel cloudflare/cloudflare-tunnel .* --values .*/config/cloudflare-tunnel/values.yaml",
            result.stdout,
        )
        assert f"--set-string cloudflare.tunnelName=sugarkube-{normalized_env}" in combined_output
        assert f"- Tunnel name: sugarkube-{normalized_env}" in combined_output
        assert "sugarkube-env=staging" not in combined_output
        assert "sugarkube-env=env=staging" not in combined_output

    alias_result = _run_cf_tunnel_install_recipe("int")
    assert alias_result.returncode == 0, alias_result.stderr
    assert 'WARNING: env name "int" is deprecated; using env=staging.' in alias_result.stderr


def test_cf_tunnel_monitoring_is_applied_only_in_staging() -> None:
    staging = _run_cf_tunnel_install_recipe("staging")
    assert staging.returncode == 0, staging.stderr
    assert "KUBECTL:apply -f " in staging.stdout
    assert "/config/cloudflare-tunnel/monitoring.yaml" in staging.stdout

    for env_name in ("dev", "prod"):
        result = _run_cf_tunnel_install_recipe(env_name)
        assert result.returncode == 0, result.stderr
        assert "/config/cloudflare-tunnel/monitoring.yaml" not in result.stdout
        assert "ServiceMonitor" not in result.stdout
        assert "--values -" in result.stdout
        assert "/config/cloudflare-tunnel/values.yaml" not in result.stdout
        assert result.stdout.count("KUBECTL:-n cloudflare patch deployment") == 1


def test_existing_secret_is_preserved_without_token_input(tmp_path: Path) -> None:
    result, calls = _run_actual_cf_tunnel_install(tmp_path, secret_exists=True)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr + calls
    assert "kubectl:-n cloudflare get secret tunnel-token -o name" in calls
    assert "create secret" not in combined
    assert "apply -f -" not in combined
    assert "--from-literal" not in combined
    assert "get secret tunnel-token -o json" not in combined
    assert "get secret tunnel-token -o yaml" not in combined
    assert "HELM" not in result.stderr
    assert "helm:upgrade --install cloudflare-tunnel" in calls
    assert calls.count("kubectl:-n cloudflare patch deployment cloudflare-tunnel") == 2
    assert "kubectl:-n cloudflare rollout status deployment/cloudflare-tunnel" in calls
    assert ("token" + '="$CF_TUNNEL_TOKEN"') not in result.stdout + result.stderr


def test_guidance_is_not_eagerly_expanded_under_nounset(cf_recipe_body: str) -> None:
    assert "cat >&2 <<'ORIGIN_CERT_GUIDANCE'" in cf_recipe_body
    assert 'origin_cert_guidance="{{ origin_cert_guidance }}"' not in cf_recipe_body
    assert 'origin_cert_guidance="' not in cf_recipe_body


def test_initial_install_requires_and_creates_secret_from_out_of_band_token() -> None:
    missing = _run_cf_tunnel_install_recipe("staging", secret_exists=False, connector_value=None)
    assert missing.returncode != 0
    assert "initial installation" in missing.stderr

    created = _run_cf_tunnel_install_recipe("staging", secret_exists=False)
    assert created.returncode == 0, created.stderr
    assert "kubectl -n cloudflare create secret generic tunnel-token" in _extract_cf_recipe_body()
    assert "KUBECTL:apply -f -" in created.stdout


def test_cf_tunnel_install_flags_origin_cert_logs(cf_recipe_body: str, origin_cert_guidance_text: str) -> None:
    assert "Cannot determine default origin certificate path" in cf_recipe_body
    assert "origin_cert_guidance" in cf_recipe_body
    assert 'config_src="cloudflare"' in origin_cert_guidance_text
    assert "behaving like a locally-managed tunnel" in origin_cert_guidance_text
    assert "cloudflared tunnel --no-autoupdate run --token <TOKEN>" in origin_cert_guidance_text


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


def test_debug_recipe_surfaces_origin_cert_guidance(origin_cert_guidance_text: str) -> None:
    debug_body = _extract_recipe_body("cf-tunnel-debug")

    assert "origin_cert_guidance" in debug_body
    assert "behaving like a locally-managed tunnel" in origin_cert_guidance_text
    assert 'config_src="cloudflare"' in origin_cert_guidance_text
