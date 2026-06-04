"""Stubbed just tests for generic Sugarkube app recipes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def generic_app_stub_env(tmp_path: Path, ensure_just_available: Path) -> dict[str, str]:
    assert ensure_just_available.exists()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "helm.log"
    kubeconfig = """apiVersion: v1
clusters:
- cluster:
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
users:
- name: default
  user: {}
"""
    _write_executable(
        bin_dir / "sudo",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "${{1:-}}" = "cp" ]; then
  mkdir -p "$(dirname "${{3}}")"
  cat > "${{3}}" <<'KUBECONFIG'
{kubeconfig}KUBECONFIG
  exit 0
fi
if [ "${{1:-}}" = "chown" ]; then
  exit 0
fi
"$@"
""",
    )
    _write_executable(
        bin_dir / "kubectl",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> {str(tmp_path / "kubectl.log")!r}
if [[ "$*" == *"get deploy,statefulset,daemonset"* ]]; then
  printf 'Deployment/danielsmith\n'
  exit 0
fi
if [[ "$*" == *"get ingress"* && "$*" == *"jsonpath"* ]]; then
  if [ "${{SUGARKUBE_STUB_KUBECTL_INGRESS_FAIL:-}}" = "1" ]; then
    echo 'error: context sugar-staging does not exist' >&2
    exit 1
  fi
  printf 'example.test'
  exit 0
fi
if [[ "$*" == *"get deploy/tokenplace"* || "$*" == *"get deploy dspace"* ]]; then
  printf 'app=ghcr.io/example/app:main-deadbee\n'
  exit 0
fi
if [[ "$*" == *"get Deployment/danielsmith"* ]]; then
  printf 'app=ghcr.io/example/app:main-deadbee\n'
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "helm",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> {str(log_path)!r}
if [[ "$*" == *"get values"* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_GET_VALUES_FAIL:-}}" = "1" ]; then
    echo 'Error: Kubernetes cluster unreachable for context sugar-staging' >&2
    exit 1
  fi
  printf '{{"ingress":{{"host":"example.test"}}}}\n'
  exit 0
fi
if [[ "$*" == *" status "* ]]; then
  printf 'STATUS: deployed\n'
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> {str(tmp_path / "curl.log")!r}
out=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
url_without_scheme="${{url#*://}}"
if [ "${{url_without_scheme#*/}}" = "${{url_without_scheme}}" ]; then
  path="/"
else
  path="/${{url_without_scheme#*/}}"
fi
if [ "${{SUGARKUBE_STUB_CURL_FAIL_PATH:-}}" = "${{path}}" ]; then
  printf '{{"status":"fail"}}\n' > "${{out}}"
  printf '503'
  exit 0
fi
case "${{path}}" in
  /) printf '<!doctype html>\n<html lang="en">\n<body>ok</body>\n</html>\n' > "${{out}}" ;;
  /config.json) printf '{{"app":"dspace"}}\n' > "${{out}}" ;;
  /relay/diagnostics) printf '{{"relay":"ok"}}\n' > "${{out}}" ;;
  *) printf '{{"status":"ok"}}\n' > "${{out}}" ;;
esac
printf '200'
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SUGARKUBE_HELM_ROLLOUT_TIMEOUT"] = "1s"
    env["HELM_LOG"] = str(log_path)
    env["KUBECTL_LOG"] = str(tmp_path / "kubectl.log")
    env["CURL_LOG"] = str(tmp_path / "curl.log")
    return env


def _run_just(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.usefixtures("ensure_just_available")
def test_app_deploy_danielsmith_passes_image_tag(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(
        ["app-deploy", "app=danielsmith", "env=env=staging", "tag=tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "upgrade danielsmith oci://ghcr.io/futuroptimist/charts/danielsmith" in helm_log
    assert "--namespace danielsmith" in helm_log
    assert "-f docs/examples/danielsmith.values.dev.yaml" in helm_log
    assert "-f docs/examples/danielsmith.values.staging.yaml" in helm_log
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("app", "chart", "namespace", "values"),
    [
        (
            "tokenplace",
            "oci://ghcr.io/futuroptimist/charts/tokenplace",
            "tokenplace",
            [
                "docs/examples/tokenplace.values.dev.yaml",
                "docs/examples/tokenplace.values.staging.yaml",
            ],
        ),
        (
            "dspace",
            "oci://ghcr.io/democratizedspace/charts/dspace",
            "dspace",
            ["docs/examples/dspace.values.dev.yaml", "docs/examples/dspace.values.staging.yaml"],
        ),
    ],
)
def test_app_deploy_uses_app_release_namespace_chart_values(
    app: str,
    chart: str,
    namespace: str,
    values: list[str],
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-deploy", f"app={app}", "env=staging", "tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"upgrade {app} {chart}" in helm_log
    assert f"--namespace {namespace}" in helm_log
    for value in values:
        assert f"-f {value}" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("app", "release", "namespace", "chart"),
    [
        (
            "dspace",
            "dspace",
            "dspace",
            "oci://ghcr.io/democratizedspace/charts/dspace",
        ),
        (
            "tokenplace",
            "tokenplace",
            "tokenplace",
            "oci://ghcr.io/futuroptimist/charts/tokenplace",
        ),
        (
            "danielsmith",
            "danielsmith",
            "danielsmith",
            "oci://ghcr.io/futuroptimist/charts/danielsmith",
        ),
    ],
)
def test_app_promote_prod_delegates_to_prod_deploy_coordinates(
    app: str,
    release: str,
    namespace: str,
    chart: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-promote-prod", f"app={app}", "tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"upgrade {release} {chart}" in helm_log
    assert f"--namespace {namespace}" in helm_log
    assert f"-f docs/examples/{app}.values.dev.yaml" in helm_log
    assert f"-f docs/examples/{app}.values.prod.yaml" in helm_log
    assert "--set image.tag=main-deadbee" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_deploy_rejects_mutable_tag_before_helm(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(
        ["app-deploy", "app=tokenplace", "env=staging", "tag=latest"],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "app"),
    [
        ("danielsmith-oci-deploy", "danielsmith"),
        ("tokenplace-oci-deploy", "tokenplace"),
        ("dspace-oci-deploy", "dspace"),
    ],
)
def test_existing_app_specific_deploy_wrappers_still_work(
    recipe: str,
    app: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just([recipe, "env=staging", "tag=main-deadbee"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert f"--namespace {app}" in helm_log
    assert "--set image.tag=main-deadbee" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "image_heading", "check_heading"),
    [
        (
            "dspace-oci-promote-prod",
            "Resolved deployment image(s):",
            "Post-deploy verification commands",
        ),
        (
            "tokenplace-oci-promote-prod",
            "Resolved images for deployment/tokenplace:",
            "Post-deploy checks:",
        ),
        (
            "danielsmith-oci-promote-prod",
            "Resolved images for danielsmith workloads:",
            "Post-deploy checks:",
        ),
    ],
)
def test_promote_wrappers_preserve_app_specific_output(
    recipe: str,
    image_heading: str,
    check_heading: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just([recipe, "tag=main-deadbee"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert image_heading in result.stdout
    assert check_heading in result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--set image.tag=main-deadbee" in helm_log
    assert "--set image.tag=tag=main-deadbee" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_status_does_not_rewrite_kubeconfig_for_read_only_checks(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(["app-status", "app=tokenplace", "env=staging"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (Path(generic_app_stub_env["HOME"]) / ".kube" / "config").exists()
    kubectl_log = Path(generic_app_stub_env["KUBECTL_LOG"]).read_text(encoding="utf-8")
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--context sugar-staging" in kubectl_log
    assert "--kube-context sugar-staging" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_executes_checks_with_readable_output_and_preserves_kubeconfig(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(["app-verify", "app=tokenplace", "env=staging"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (Path(generic_app_stub_env["HOME"]) / ".kube" / "config").exists()
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--kube-context sugar-staging" in helm_log
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "https://example.test/" in curl_log
    assert "https://example.test/livez" in curl_log
    assert "https://example.test/healthz" in curl_log
    assert "https://example.test/relay/diagnostics" in curl_log
    assert "Verifying tokenplace env=staging" in result.stdout
    assert "Host: https://example.test" in result.stdout
    assert "\n[1/4] GET /\n  URL: https://example.test/\n  Status: OK" in result.stdout
    assert "\n[2/4] GET /livez" in result.stdout
    assert "  Body:" in result.stdout
    assert "Verification passed: 4/4 checks succeeded." in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_continues_all_paths_and_fails_at_end(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CURL_FAIL_PATH"] = "/livez"

    result = _run_just(["app-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    curl_log = Path(env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "https://example.test/" in curl_log
    assert "https://example.test/livez" in curl_log
    assert "https://example.test/healthz" in curl_log
    assert "https://example.test/relay/diagnostics" in curl_log
    assert "[2/4] GET /livez" in result.stdout
    assert "  Status: FAILED" in result.stdout
    assert "  HTTP status: 503" in result.stdout
    assert "Verification failed: 3/4 checks succeeded." in result.stdout
    assert "Failing paths: /livez" in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_print_only_prints_curl_commands_without_calling_curl(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-verify", "app=danielsmith", "env=staging", "print_only=1"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.splitlines() == [
        "curl -fsS https://example.test/",
        "curl -fsS https://example.test/livez",
        "curl -fsS https://example.test/healthz",
    ]
    curl_log_path = Path(generic_app_stub_env["CURL_LOG"])
    assert not curl_log_path.exists() or curl_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_can_suppress_response_bodies(generic_app_stub_env: dict[str, str]) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_VERIFY_SHOW_BODY"] = "0"

    result = _run_just(["app-verify", "app=dspace", "env=staging"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Body:" not in result.stdout
    assert "Body preview:" not in result.stdout
    assert "URL: https://example.test/config.json" in result.stdout
    assert "Verification passed: 3/3 checks succeeded." in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_fails_closed_when_context_host_discovery_fails(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_GET_VALUES_FAIL"] = "1"
    env["SUGARKUBE_STUB_KUBECTL_INGRESS_FAIL"] = "1"

    result = _run_just(["app-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    assert "Could not derive a host for tokenplace using context sugar-staging" in result.stderr
    assert "helm get values failed for context sugar-staging" in result.stderr
    assert "kubectl ingress lookup failed for context sugar-staging" in result.stderr
    assert "just app-status app=tokenplace env=staging" in result.stderr
    assert "curl -fsS https://<host>/livez" in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_print_only_succeeds_with_placeholder_when_host_discovery_fails(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_GET_VALUES_FAIL"] = "1"
    env["SUGARKUBE_STUB_KUBECTL_INGRESS_FAIL"] = "1"

    result = _run_just(
        ["app-verify", "app=tokenplace", "env=staging", "print_only=1"],
        env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "curl -fsS https://<host>/relay/diagnostics" in result.stdout
    curl_log_path = Path(env["CURL_LOG"])
    assert not curl_log_path.exists() or curl_log_path.read_text(encoding="utf-8") == ""
