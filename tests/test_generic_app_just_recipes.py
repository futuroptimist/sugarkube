"""Stubbed just tests for generic Sugarkube app recipes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.app_verify import base_url_from_host

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
printf '%s
' "$*" >> {str(log_path)!r}
if [[ "$*" == *"show chart"* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_SHOW_FAIL:-}}" = "1" ]; then
    echo 'Error: chart not found' >&2
    exit 1
  fi
  printf 'apiVersion: v2\n'
  printf 'name: tokenplace\n'
  printf 'version: 0.1.3\n'
  printf 'appVersion: 0.1.3\n'
  printf 'digest: sha256:abc123\n'
  exit 0
fi
if [[ "$*" == *"template"* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_TEMPLATE_MISSING_TOKENPLACE_ENV:-}}" = "1" ]; then
    printf 'apiVersion: apps/v1\nkind: Deployment\n'
  else
    printf 'env:\n'
    printf -- '- name: TOKENPLACE_IMAGE_TAG\n'
    printf -- '- name: TOKENPLACE_RELEASE_VERSION\n'
    printf -- '- name: TOKENPLACE_CHART_VERSION\n'
    printf -- '- name: TOKENPLACE_DEPLOY_ENV\n'
  fi
  exit 0
fi
if [[ "$*" == *"get values"* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_GET_VALUES_FAIL:-}}" = "1" ]; then
    echo 'Error: Kubernetes cluster unreachable for context sugar-staging' >&2
    exit 1
  fi
  printf '{{{{"ingress":{{{{"host":"%s"}}}}}}}}\n' "${{SUGARKUBE_STUB_HELM_HOST:-example.test}}"
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
body_file=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --connect-timeout|--max-time|-w) shift 2 ;;
    -o) body_file="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
path="${{url#https://example.test}}"
path="${{path:-/}}"
status=200
body='{{"status":"ok"}}'
case "${{path}}" in
  /) body=$'<!doctype html>\n<html lang="en">\n<body>ok</body>\n</html>' ;;
  /config.json) body='{{"publicConfig":true}}' ;;
  /relay/diagnostics) body='{{"relay":"ok"}}' ;;
esac
if [ "${{SUGARKUBE_STUB_CURL_FAIL_PATH:-}}" = "${{path}}" ]; then
  status=503
  body='{{"status":"down"}}'
  echo 'curl: (22) The requested URL returned error: 503' >&2
fi
if [ -n "${{body_file}}" ]; then
  printf '%s\n' "${{body}}" > "${{body_file}}"
else
  printf '%s\n' "${{body}}"
fi
printf '%s' "${{status}}"
if [ "${{status}}" -ge 400 ]; then
  exit 22
fi
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
def test_app_chart_recipes_exist(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(["--list"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr
    assert "app-chart-status" in result.stdout
    assert "app-chart-bump" in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_app_deploy_prints_and_uses_pinned_chart_without_latest(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CHART_LATEST"] = "9.9.9"

    result = _run_just(["app-deploy", "app=tokenplace", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "app: tokenplace" in result.stdout
    assert "image tag: main-deadbee" in result.stdout
    assert "chart ref: oci://ghcr.io/futuroptimist/charts/tokenplace" in result.stdout
    assert "chart version: 0.1.3" in result.stdout
    assert "chart pin: docs/apps/tokenplace.version" in result.stdout
    helm_log = Path(env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--version 0.1.3" in helm_log
    assert "9.9.9" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_chart_status_reports_stale_pin(generic_app_stub_env: dict[str, str]) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CHART_LATEST"] = "0.1.4"

    result = _run_just(["app-chart-status", "app=tokenplace"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "pinned version: 0.1.3" in result.stdout
    assert "chart ref: oci://ghcr.io/futuroptimist/charts/tokenplace" in result.stdout
    assert "chart appVersion: 0.1.3" in result.stdout
    assert "WARNING: Pinned chart appears stale: 0.1.3 < 0.1.4" in result.stdout
    assert "Run: just app-chart-bump app=tokenplace version=0.1.4" in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_app_chart_bump_refuses_empty_version(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(["app-chart-bump", "app=tokenplace", "version="], generic_app_stub_env)

    assert result.returncode != 0
    assert "version must not be empty" in result.stderr


@pytest.mark.usefixtures("ensure_just_available")
def test_app_chart_bump_validates_chart(generic_app_stub_env: dict[str, str]) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_SHOW_FAIL"] = "1"

    result = _run_just(["app-chart-bump", "app=tokenplace", "version=0.1.3"], env)

    assert result.returncode != 0
    assert "chart not found" in result.stderr


def test_app_chart_bump_updates_only_version_file_in_temp_fixture(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    pin = tmp_path / "tokenplace.version"
    pin.write_text(
        "# Default tokenplace chart version. Update when new chart releases are published.\n"
        "0.1.0  # keep this comment\n",
        encoding="utf-8",
    )
    config = tmp_path / "tokenplace.env"
    staging_values = (
        "docs/examples/tokenplace.values.dev.yaml,"
        "docs/examples/tokenplace.values.staging.yaml"
    )
    prod_values = (
        "docs/examples/tokenplace.values.dev.yaml,"
        "docs/examples/tokenplace.values.prod.yaml"
    )
    config.write_text(
        f"""SUGARKUBE_APP=tokenplace
SUGARKUBE_RELEASE=tokenplace
SUGARKUBE_NAMESPACE=tokenplace
SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/tokenplace
SUGARKUBE_VERSION_FILE={pin}
SUGARKUBE_VALUES_DEV=docs/examples/tokenplace.values.dev.yaml
SUGARKUBE_VALUES_STAGING={staging_values}
SUGARKUBE_VALUES_PROD={prod_values}
""",
        encoding="utf-8",
    )

    before = {path: path.read_text(encoding="utf-8") for path in (pin, config)}
    result = _run_just(
        ["app-chart-bump", "app=tokenplace", "version=0.1.3", f"config={config}"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert pin.read_text(encoding="utf-8").splitlines() == [
        "# Default tokenplace chart version. Update when new chart releases are published.",
        "0.1.3  # keep this comment",
    ]
    assert config.read_text(encoding="utf-8") == before[config]
    assert "git add" in result.stdout
    assert "just app-deploy app=tokenplace env=staging tag=<APP_TAG>" in result.stdout


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_preflight_fails_when_metadata_env_missing(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_TEMPLATE_MISSING_TOKENPLACE_ENV"] = "1"

    result = _run_just(["app-deploy", "app=tokenplace", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode != 0
    assert "missing required metadata env vars" in result.stderr
    assert "TOKENPLACE_IMAGE_TAG" in result.stderr
    assert "TOKENPLACE_RELEASE_VERSION" in result.stderr
    assert "TOKENPLACE_CHART_VERSION" in result.stderr
    assert "TOKENPLACE_DEPLOY_ENV" in result.stderr
    assert "just app-chart-status app=tokenplace" in result.stderr


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_preflight_passes_when_metadata_env_present(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-deploy", "app=tokenplace", "env=staging", "tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "template tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in helm_log


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
def test_app_verify_does_not_rewrite_kubeconfig_for_read_only_checks(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(["app-verify", "app=tokenplace", "env=staging"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (Path(generic_app_stub_env["HOME"]) / ".kube" / "config").exists()
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--kube-context sugar-staging" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_executes_curl_by_default_and_prints_summary(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(["app-verify", "app=danielsmith", "env=staging"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "https://example.test/" in curl_log
    assert "https://example.test/livez" in curl_log
    assert "https://example.test/healthz" in curl_log
    assert "https://example.test/runtime/github-metrics.json" not in curl_log
    assert result.stdout.startswith(
        "Verifying danielsmith env=staging\nHost: https://example.test\n\n"
    )
    assert "\n[1/3] GET /\n" in result.stdout
    assert "\n[2/3] GET /livez\n" in result.stdout
    assert "\n[3/3] GET /healthz\n" in result.stdout
    assert "  URL: https://example.test/livez\n" in result.stdout
    assert "  Status: OK (HTTP 200)" in result.stdout
    assert '  Body:\n  {"status":"ok"}' in result.stdout
    assert "Verification passed: 3/3 checks succeeded." in result.stdout


def test_app_verify_adds_curl_timeouts(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(["app-verify", "app=danielsmith", "env=staging"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "--connect-timeout 10 --max-time 30" in curl_log


@pytest.mark.parametrize(
    ("host", "expected_base_url"),
    [
        ("example.test", "https://example.test"),
        ("http://example.test", "https://example.test"),
        ("https://example.test", "https://example.test"),
    ],
)
def test_app_verify_normalizes_hosts_to_https(host: str, expected_base_url: str) -> None:
    assert base_url_from_host(host) == expected_base_url


def test_app_verify_normalizes_http_host_values_to_https(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_HOST"] = "http://example.test"

    result = _run_just(["app-verify", "app=danielsmith", "env=staging"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Host: https://example.test" in result.stdout
    curl_log = Path(env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "https://example.test/livez" in curl_log
    assert "http://example.test" not in curl_log


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_failure_checks_all_paths_and_exits_nonzero(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CURL_FAIL_PATH"] = "/livez"

    result = _run_just(["app-verify", "app=danielsmith", "env=staging"], env)

    assert result.returncode != 0
    curl_log = Path(env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "https://example.test/" in curl_log
    assert "https://example.test/livez" in curl_log
    assert "https://example.test/healthz" in curl_log
    assert "https://example.test/runtime/github-metrics.json" not in curl_log
    assert "[2/3] GET /livez" in result.stdout
    assert "Status: FAILED (HTTP 503)" in result.stdout
    assert "curl exit status: 22" in result.stdout
    assert '{"status":"down"}' in result.stdout
    assert "Verification failed: 1/3 checks failed." in result.stderr
    assert "/livez (https://example.test/livez)" in result.stderr


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_print_only_prints_commands_without_curl(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-verify", "app=tokenplace", "env=staging", "print_only=1"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.splitlines() == [
        "curl -fsS https://example.test/",
        "curl -fsS https://example.test/livez",
        "curl -fsS https://example.test/healthz",
        "curl -fsS https://example.test/relay/diagnostics",
    ]
    assert not Path(generic_app_stub_env["CURL_LOG"]).exists()


@pytest.mark.parametrize("false_env_value", ["0", "false", ""])
def test_app_verify_print_only_argument_overrides_false_environment_value(
    generic_app_stub_env: dict[str, str], false_env_value: str
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_VERIFY_PRINT_ONLY"] = false_env_value

    result = _run_just(["app-verify", "app=danielsmith", "env=staging", "print_only=1"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.splitlines() == [
        "curl -fsS https://example.test/",
        "curl -fsS https://example.test/livez",
        "curl -fsS https://example.test/healthz",
    ]
    assert not Path(env["CURL_LOG"]).exists()


def test_app_verify_print_only_environment_prints_commands_without_curl(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_VERIFY_PRINT_ONLY"] = "1"

    result = _run_just(["app-verify", "app=danielsmith", "env=staging"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.splitlines() == [
        "curl -fsS https://example.test/",
        "curl -fsS https://example.test/livez",
        "curl -fsS https://example.test/healthz",
    ]
    assert not Path(env["CURL_LOG"]).exists()


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_show_body_can_be_disabled(generic_app_stub_env: dict[str, str]) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_VERIFY_SHOW_BODY"] = "0"

    result = _run_just(["app-verify", "app=dspace", "env=staging"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "Body:" not in result.stdout
    assert "https://example.test/config.json" in result.stdout
    assert "Verification passed: 3/3 checks succeeded." in result.stdout


@pytest.mark.parametrize(
    ("app", "expected_paths"),
    [
        ("danielsmith", "/,/livez,/healthz"),
        ("tokenplace", "/,/livez,/healthz,/relay/diagnostics"),
        ("dspace", "/config.json,/healthz,/livez"),
    ],
)
def test_example_app_configs_preserve_verify_paths(app: str, expected_paths: str) -> None:
    result = subprocess.run(
        [
            "python3",
            "scripts/app_config.py",
            "json",
            "--app",
            app,
            "--env",
            "staging",
            "--config",
            "",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f'"SUGARKUBE_VERIFY_PATHS": "{expected_paths}"' in result.stdout


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
    assert "Suggested next steps: just app-status app=tokenplace env=staging" in result.stderr
    assert "curl -fsS https://<host>/" in result.stdout
