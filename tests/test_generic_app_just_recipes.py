"""Stubbed just tests for generic Sugarkube app recipes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import app_chart
from scripts import app_verify
from scripts.app_verify import base_url_from_host, tokenplace_meta_failure

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
  printf '{{"ingress":{{"host":"%s"}}}}\n' "${{SUGARKUBE_STUB_HELM_HOST:-example.test}}"
  exit 0
fi
if [[ "$*" == show\ chart* ]]; then
  printf 'apiVersion: v2\nname: tokenplace\nversion: 0.1.3\nappVersion: main-deadbee\ndigest: sha256:abc123\n'
  exit 0
fi
if [[ "$*" == template* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_TEMPLATE_MISSING_META:-}}" = "1" ]; then
    printf 'apiVersion: apps/v1
kind: Deployment
metadata:
  name: tokenplace
'
  elif [ "${{SUGARKUBE_STUB_HELM_TEMPLATE_COMMENT_META:-}}" = "1" ]; then
    printf '# TOKENPLACE_IMAGE_TAG TOKENPLACE_RELEASE_VERSION TOKENPLACE_CHART_VERSION TOKENPLACE_DEPLOY_ENV
kind: ConfigMap
data:
  TOKENPLACE_IMAGE_TAG: main-deadbee
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tokenplace
spec:
  template:
    spec:
      containers:
        - name: tokenplace
          image: ghcr.io/example/tokenplace:main-deadbee
        - name: metrics-sidecar
          env:
            - name: TOKENPLACE_IMAGE_TAG
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
'
  else
    printf 'apiVersion: apps/v1
kind: Deployment
metadata:
  name: tokenplace
spec:
  template:
    spec:
      containers:
        - name: relay
          env:
            - name: TOKENPLACE_IMAGE_TAG
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
        - name: metrics-sidecar
          env:
            - name: SIDECAR_ONLY
'
  fi
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
header_file=""
url=""
method="GET"
origin=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --connect-timeout|--max-time|-w) shift 2 ;;
    -o) body_file="$2"; shift 2 ;;
    -D) header_file="$2"; shift 2 ;;
    -X) method="$2"; shift 2 ;;
    -H)
      case "$2" in
        Origin:*) origin="${{2#Origin: }}" ;;
      esac
      shift 2
      ;;
    --data|--data-raw) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
path="${{url#https://example.test}}"
path="${{path:-/}}"
status=200
body='{{"status":"ok"}}'
headers=$'HTTP/2 200\r\ncontent-type: application/json\r\n'
case "${{url}}" in
  https://api.github.com/orgs/futuroptimist/packages/container/charts%2Ftokenplace/versions*)
    status=404
    body='{{"message":"Not Found"}}'
    ;;
  https://api.github.com/users/futuroptimist/packages/container/charts%2Ftokenplace/versions*)
    status=200
    body='[{{"metadata":{{"container":{{"tags":["0.1.3","0.1.4-rc.1","0.1.4"]}}}}}}]'
    ;;
esac
if [ "${{method}}" = "OPTIONS" ]; then
  status="${{SUGARKUBE_STUB_CORS_PREFLIGHT_STATUS:-204}}"
  acao="${{SUGARKUBE_STUB_CORS_ACAO-*}}"
  methods="${{SUGARKUBE_STUB_CORS_METHODS:-POST, OPTIONS}}"
  allow_headers="${{SUGARKUBE_STUB_CORS_HEADERS:-content-type}}"
  credentials="${{SUGARKUBE_STUB_CORS_CREDENTIALS:-}}"
  if [ "${{acao}}" = "__origin__" ]; then acao="${{origin}}"; fi
  headers="HTTP/2 ${{status}}"$'\r\n'
  if [ "${{acao}}" != "__missing__" ]; then headers+="Access-Control-Allow-Origin: ${{acao}}"$'\r\n'; fi
  headers+="Access-Control-Allow-Methods: ${{methods}}"$'\r\n'
  headers+="Access-Control-Allow-Headers: ${{allow_headers}}"$'\r\n'
  if [ -n "${{credentials}}" ]; then headers+="Access-Control-Allow-Credentials: ${{credentials}}"$'\r\n'; fi
  body=''
fi
case "${{path}}" in
  /) body=$'<!doctype html>\n<html lang="en">\n<body>ok</body>\n</html>' ;;
  /config.json) body='{{"publicConfig":true}}' ;;
  /relay/diagnostics) body='{{"relay":"ok"}}' ;;
  /api/v1/meta) body='{{"label":"staging main-deadbee","version":"main-deadbee"}}' ;;
  /api/v1/chat/completions)
    if [ "${{method}}" != "OPTIONS" ]; then
      status="${{SUGARKUBE_STUB_CORS_ACTUAL_STATUS:-400}}"
      body='{{"error":{{"message":"invalid request"}}}}'
      acao="${{SUGARKUBE_STUB_CORS_ACTUAL_ACAO-${{SUGARKUBE_STUB_CORS_ACAO-*}}}}"
      credentials="${{SUGARKUBE_STUB_CORS_CREDENTIALS:-}}"
      if [ "${{acao}}" = "__origin__" ]; then acao="${{origin}}"; fi
      headers="HTTP/2 ${{status}}"$'\r\n'
      if [ "${{acao}}" != "__missing__" ]; then headers+="Access-Control-Allow-Origin: ${{acao}}"$'\r\n'; fi
      headers+=$'content-type: application/json\r\n'
      if [ -n "${{credentials}}" ]; then headers+="Access-Control-Allow-Credentials: ${{credentials}}"$'\r\n'; fi
    fi
    ;;
esac
if [ "${{SUGARKUBE_STUB_CURL_FAIL_PATH:-}}" = "${{path}}" ]; then
  status=503
  body='{{"status":"down"}}'
  echo 'curl: (22) The requested URL returned error: 503' >&2
fi
if [ "${{method}}" != "OPTIONS" ] && [ -n "${{SUGARKUBE_STUB_CORS_ACTUAL_CURL_EXIT:-}}" ]; then
  echo 'curl: (18) transfer closed with outstanding read data remaining' >&2
  curl_exit="${{SUGARKUBE_STUB_CORS_ACTUAL_CURL_EXIT}}"
else
  curl_exit="${{SUGARKUBE_STUB_CURL_EXIT:-0}}"
fi
if [ -n "${{header_file}}" ]; then
  printf '%s\r\n' "${{headers}}" > "${{header_file}}"
fi
if [ -n "${{body_file}}" ]; then
  printf '%s\n' "${{body}}" > "${{body_file}}"
else
  printf '%s\n' "${{body}}"
fi
printf '%s' "${{status}}"
exit "${{curl_exit}}"
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


def _assert_chart_pin_reminder(output: str, app: str) -> None:
    assert "NOTE: chart pins are explicit. `tag=...` changes only the image tag." in output
    assert f"Run `just app-chart-status app={app}`" in output
    assert f"Use `just app-chart-bump app={app} version=<version>`" in output


def test_app_chart_semver_prefers_final_release_over_matching_prerelease() -> None:
    assert sorted(["1.2.3", "1.2.3-rc.1"], key=app_chart.semver_key)[-1] == "1.2.3"


def test_app_chart_latest_version_prefers_production_safe_stable_over_prerelease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            '[{"metadata":{"container":{"tags":["1.0.0","1.0.1-alpha"]}}}]',
            "",
        )

    monkeypatch.delenv("SUGARKUBE_APP_CHART_LATEST_STUB", raising=False)
    monkeypatch.setattr(app_chart, "run", fake_run)

    latest, source = app_chart.latest_version("oci://ghcr.io/futuroptimist/charts/tokenplace")

    assert latest == "1.0.0"
    assert source == "GitHub/GHCR API"


def test_app_chart_read_pin_rejects_empty_version_file_path() -> None:
    with pytest.raises(SystemExit, match="--version-file must not be empty"):
        app_chart.read_pin("")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"{}", "non-empty label"),
        (b"<html>ok</html>", "valid JSON"),
        (b'{"version":"dev"}', "non-empty label"),
        (b'{"label":"staging dev"}', "non-empty version"),
        (
            b'{"label":"staging main-deadbee","version":"dev"}',
            "staging metadata must include the immutable image tag",
        ),
        (
            b'{"label":"staging dev","version":"main-deadbee"}',
            "staging metadata must include the immutable image tag",
        ),
    ],
)
def test_tokenplace_meta_failure_rejects_invalid_or_missing_metadata(
    body: bytes, expected: str
) -> None:
    assert expected in tokenplace_meta_failure("staging", body)


def test_app_chart_parse_chart_yaml_strips_quotes_and_ignores_nested_lines() -> None:
    assert app_chart.parse_chart_yaml(
        "apiVersion: v2\nname: \"tokenplace\"\n  nested: ignored\ndigest: 'sha256:abc'\n"
    ) == {
        "apiVersion": "v2",
        "name": "tokenplace",
        "digest": "sha256:abc",
    }


def test_app_chart_latest_version_reports_unsupported_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUGARKUBE_APP_CHART_LATEST_STUB", raising=False)

    latest, source = app_chart.latest_version("https://charts.example.test/tokenplace")

    assert latest == ""
    assert "unsupported chart registry" in source


def test_app_chart_latest_version_handles_bad_api_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, "not json", "")

    monkeypatch.delenv("SUGARKUBE_APP_CHART_LATEST_STUB", raising=False)
    monkeypatch.setattr(app_chart, "run", fake_run)

    latest, source = app_chart.latest_version("oci://ghcr.io/futuroptimist/charts/tokenplace")

    assert latest == ""
    assert "no semver tags found" in source


def test_app_chart_latest_version_uses_stub_without_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUGARKUBE_APP_CHART_LATEST_STUB", "2.0.0")

    latest, source = app_chart.latest_version("oci://ghcr.io/futuroptimist/charts/tokenplace")

    assert latest == "2.0.0"
    assert source == "SUGARKUBE_APP_CHART_LATEST_STUB"


def test_app_chart_deployment_env_parser_accepts_quoted_release_container() -> None:
    manifest = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: custom-release
spec:
  template:
    spec:
      initContainers:
        - name: tokenplace
          env:
            - name: INIT_ONLY
      containers:
        - name: "custom-release"
          env:
            - name: "TOKENPLACE_IMAGE_TAG"
            - name: 'TOKENPLACE_RELEASE_VERSION'
        - name: metrics-sidecar
          env:
            - name: TOKENPLACE_CHART_VERSION
"""

    envs = app_chart.deployment_app_container_envs(manifest, "tokenplace", "custom-release")

    assert envs == {"TOKENPLACE_IMAGE_TAG", "TOKENPLACE_RELEASE_VERSION"}


def test_app_chart_cmd_status_reports_helm_show_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
    )
    monkeypatch.setattr(app_chart, "read_pin", lambda path: "0.1.3")
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 1, "", "missing chart"),
    )

    assert app_chart.cmd_status(args) == 1
    assert "missing chart" in capsys.readouterr().err


def test_app_chart_cmd_status_prints_metadata_without_stale_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
    )
    monkeypatch.setattr(app_chart, "read_pin", lambda path: "0.1.3")
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess(
            [], 0, "apiVersion: v2\nappVersion: main-deadbee\ndigest: sha256:abc\n", ""
        ),
    )
    monkeypatch.setattr(app_chart, "latest_version", lambda chart: ("0.1.3", "test"))

    assert app_chart.cmd_status(args) == 0
    out = capsys.readouterr().out
    assert "chart appVersion: main-deadbee" in out
    assert "latest version: 0.1.3 (test)" in out
    assert "Pinned chart appears stale" not in out


def test_app_chart_cmd_bump_adds_pin_when_file_has_only_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin = tmp_path / "empty.version"
    pin.write_text("# comment only\n", encoding="utf-8")
    args = argparse.Namespace(
        app="tokenplace",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file=str(pin),
        version="0.2.0",
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "apiVersion: v2\n", ""),
    )

    assert app_chart.cmd_bump(args) == 0
    assert pin.read_text(encoding="utf-8") == "# comment only\n0.2.0\n"
    assert "just app-deploy app=tokenplace env=staging tag=<APP_TAG>" in capsys.readouterr().out


def test_app_chart_cmd_preflight_skips_manifest_render_for_apps_without_required_envs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="danielsmith",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/danielsmith",
        version_file="docs/apps/danielsmith.version",
        version="1.0.0",
        release="danielsmith",
        namespace="danielsmith",
        values="",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "apiVersion: v2\n", ""),
    )
    monkeypatch.setattr(
        app_chart,
        "run",
        lambda cmd: calls.append(cmd[0]) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    assert app_chart.cmd_preflight(args) == 0
    assert calls == []
    assert "app: danielsmith" in capsys.readouterr().out


def test_app_chart_cmd_preflight_reports_template_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values="values-a.yaml, values-b.yaml",
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "", ""),
    )
    monkeypatch.setattr(
        app_chart,
        "run",
        lambda cmd: subprocess.CompletedProcess(cmd, 2, "", "render failed"),
    )

    assert app_chart.cmd_preflight(args) == 2
    assert "render failed" in capsys.readouterr().err


def test_app_chart_cmd_preflight_reports_helm_show_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values="",
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 3, "", "chart missing"),
    )

    assert app_chart.cmd_preflight(args) == 3
    assert "chart missing" in capsys.readouterr().err


def test_app_chart_cmd_preflight_reports_missing_app_container_envs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values="values-a.yaml, values-b.yaml",
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "apiVersion: v2\n", ""),
    )
    monkeypatch.setattr(
        app_chart,
        "run",
        lambda cmd: subprocess.CompletedProcess(
            cmd,
            0,
            "apiVersion: apps/v1\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n        - name: relay\n          env:\n            - name: TOKENPLACE_IMAGE_TAG\n",
            "",
        ),
    )

    assert app_chart.cmd_preflight(args) == 1
    err = capsys.readouterr().err
    assert "missing required metadata env vars" in err
    assert "TOKENPLACE_RELEASE_VERSION" in err
    assert "just app-chart-bump app=tokenplace" in err


def test_app_chart_cmd_preflight_rejects_envs_split_across_candidate_containers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values="",
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "apiVersion: v2\n", ""),
    )
    monkeypatch.setattr(
        app_chart,
        "run",
        lambda cmd: subprocess.CompletedProcess(
            cmd,
            0,
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: relay\n"
            "          env:\n"
            "            - name: TOKENPLACE_IMAGE_TAG\n"
            "            - name: TOKENPLACE_RELEASE_VERSION\n"
            "        - name: tokenplace\n"
            "          env:\n"
            "            - name: TOKENPLACE_CHART_VERSION\n"
            "            - name: TOKENPLACE_DEPLOY_ENV\n",
            "",
        ),
    )

    assert app_chart.cmd_preflight(args) == 1
    err = capsys.readouterr().err
    assert "missing required metadata env vars" in err
    assert "TOKENPLACE_IMAGE_TAG" in err
    assert "TOKENPLACE_DEPLOY_ENV" in err


def test_deployment_app_container_env_sets_handles_container_name_after_image() -> None:
    manifest = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - image: ghcr.io/example/tokenplace:main-deadbee
          name: relay
          env:
            - name: "TOKENPLACE_IMAGE_TAG"
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
"""

    assert app_chart.deployment_app_container_env_sets(manifest, "tokenplace", "tokenplace") == [
        (
            "relay",
            {
                "TOKENPLACE_IMAGE_TAG",
                "TOKENPLACE_RELEASE_VERSION",
                "TOKENPLACE_CHART_VERSION",
                "TOKENPLACE_DEPLOY_ENV",
            },
        )
    ]


def test_deployment_app_container_env_sets_ignores_nested_names_before_container_name() -> None:
    manifest = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - image: ghcr.io/example/tokenplace:main-deadbee
          volumeMounts:
            - name: tmp
              mountPath: /tmp
          ports:
            - name: http
              containerPort: 8080
          env:
            - name: TOKENPLACE_IMAGE_TAG
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
          name: relay
"""

    assert app_chart.deployment_app_container_env_sets(manifest, "tokenplace", "tokenplace") == [
        (
            "relay",
            {
                "TOKENPLACE_IMAGE_TAG",
                "TOKENPLACE_RELEASE_VERSION",
                "TOKENPLACE_CHART_VERSION",
                "TOKENPLACE_DEPLOY_ENV",
            },
        )
    ]


def test_deployment_app_container_env_sets_handles_env_before_container_name() -> None:
    manifest = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - env:
            - name: TOKENPLACE_IMAGE_TAG
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
          image: ghcr.io/example/tokenplace:main-deadbee
          name: relay
"""

    assert app_chart.deployment_app_container_env_sets(manifest, "tokenplace", "tokenplace") == [
        (
            "relay",
            {
                "TOKENPLACE_IMAGE_TAG",
                "TOKENPLACE_RELEASE_VERSION",
                "TOKENPLACE_CHART_VERSION",
                "TOKENPLACE_DEPLOY_ENV",
            },
        )
    ]


def test_app_chart_cmd_preflight_passes_when_relay_envs_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values="",
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "apiVersion: v2\n", ""),
    )
    monkeypatch.setattr(
        app_chart,
        "run",
        lambda cmd: subprocess.CompletedProcess(
            cmd,
            0,
            "apiVersion: apps/v1\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n        - name: relay\n          env:\n            - name: TOKENPLACE_IMAGE_TAG\n            - name: TOKENPLACE_RELEASE_VERSION\n            - name: TOKENPLACE_CHART_VERSION\n            - name: TOKENPLACE_DEPLOY_ENV\n",
            "",
        ),
    )

    assert app_chart.cmd_preflight(args) == 0
    assert "chart version: 0.1.3" in capsys.readouterr().out


def test_app_chart_cmd_bump_reports_empty_version_and_show_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        app="tokenplace",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version=" ",
    )
    assert app_chart.cmd_bump(args) == 2
    assert "version must not be empty" in capsys.readouterr().err

    args.version = "0.2.0"
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 4, "", "no such chart"),
    )
    assert app_chart.cmd_bump(args) == 4
    assert "no such chart" in capsys.readouterr().err


def test_app_chart_main_dispatches_status(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_status(args: argparse.Namespace) -> int:
        seen["app"] = args.app
        return 7

    monkeypatch.setattr(app_chart, "cmd_status", fake_status)
    monkeypatch.setattr(
        "sys.argv",
        [
            "app_chart.py",
            "status",
            "--app",
            "tokenplace",
            "--chart",
            "oci://example",
            "--version-file",
            "docs/apps/tokenplace.version",
        ],
    )

    assert app_chart.main() == 7
    assert seen == {"app": "tokenplace"}


def test_app_verify_helpers_cover_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    assert app_verify.env_flag("MISSING_FLAG", default=True) is True
    monkeypatch.setenv("BOOL_FLAG", "off")
    assert app_verify.env_flag("BOOL_FLAG", default=True) is False
    assert app_verify.normalize_path(" livez ") == "/livez"
    assert app_verify.normalize_path("   ") == "/"
    assert app_verify.host_from_values("not json", "ingress.host") == ""
    assert app_verify.host_from_values('{"ingress":"bad"}', "ingress.host") == ""
    assert (
        app_verify.host_from_values('{"ingress":{"host":"example.test"}}', "ingress.host")
        == "example.test"
    )
    assert app_verify.base_url_from_host("") == ""
    assert app_verify.preview_text(b"one\ntwo\nthree", 7, 1) == (["one"], True)
    monkeypatch.setenv("INT_FLAG", "not-int")
    assert app_verify.int_env("INT_FLAG", 12) == 12
    monkeypatch.setenv("INT_FLAG", "-5")
    assert app_verify.int_env("INT_FLAG", 12) == 0


def test_app_verify_discover_host_uses_kubectl_after_helm_without_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUGARKUBE_RELEASE", "tokenplace")
    monkeypatch.setenv("SUGARKUBE_NAMESPACE", "tokenplace")
    monkeypatch.setattr(app_verify, "shutil_which", lambda name: f"/bin/{name}")

    def fake_run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "helm":
            return subprocess.CompletedProcess(args, 0, '{"ingress":{}}', "")
        return subprocess.CompletedProcess(args, 0, "kubectl.example.test", "")

    monkeypatch.setattr(app_verify, "run_capture", fake_run_capture)

    assert app_verify.discover_host("sugar-staging") == ("kubectl.example.test", [])


def test_app_verify_run_curl_captures_body_and_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(
        args: list[str], capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        body_path = Path(args[args.index("-o") + 1])
        body_path.write_text("payload", encoding="utf-8")
        return subprocess.CompletedProcess(args, 22, "503", "curl failed")

    monkeypatch.setattr(app_verify.subprocess, "run", fake_run)

    assert app_verify.run_curl("https://example.test/") == (22, "503", b"payload", "curl failed")


def test_app_verify_main_print_only_and_placeholder_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SUGARKUBE_APP", "tokenplace")
    monkeypatch.setenv("SUGARKUBE_ENV", "staging")
    monkeypatch.setenv("SUGARKUBE_VERIFY_PATHS", " , livez")
    monkeypatch.setattr(app_verify, "discover_host", lambda context: ("", ["no ingress"]))

    assert app_verify.main(["--print-only"]) == 0
    captured = capsys.readouterr()
    assert "Could not derive a host for tokenplace" in captured.err
    assert "curl -fsS https://<host>/livez" in captured.out

    monkeypatch.setattr(app_verify, "discover_host", lambda context: ("example.test", []))
    assert app_verify.main(["--print-only"]) == 0
    assert "curl -fsS https://example.test/livez" in capsys.readouterr().out


def test_app_verify_main_reports_meta_and_http_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SUGARKUBE_APP", "tokenplace")
    monkeypatch.setenv("SUGARKUBE_ENV", "staging")
    monkeypatch.setenv("SUGARKUBE_VERIFY_PATHS", "/api/v1/meta,/down,/empty")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES", "12")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_LINES", "1")
    monkeypatch.setattr(app_verify, "discover_host", lambda context: ("example.test", []))

    def fake_run_curl(url: str) -> tuple[int, str, bytes, str]:
        if url.endswith("/api/v1/meta"):
            return 0, "200", b"{}", ""
        if url.endswith("/down"):
            return 0, "503", b"line1\nline2", "server said no"
        return 0, "200", b"", ""

    monkeypatch.setattr(app_verify, "run_curl", fake_run_curl)

    assert app_verify.main([]) == 1
    captured = capsys.readouterr()
    assert (
        "metadata error: token.place metadata endpoint must include a non-empty label"
        in captured.out
    )
    assert "Status: FAILED (HTTP 503)" in captured.out
    assert "Body preview:" in captured.out
    assert "Body: <empty>" in captured.out
    assert "Verification failed: 2/3 checks failed." in captured.err


def test_app_verify_main_success_without_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SUGARKUBE_APP", "danielsmith")
    monkeypatch.setenv("SUGARKUBE_ENV", "staging")
    monkeypatch.setenv("SUGARKUBE_VERIFY_PATHS", "/")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_SHOW_BODY", "false")
    monkeypatch.setattr(app_verify, "discover_host", lambda context: ("https://example.test", []))
    monkeypatch.setattr(app_verify, "run_curl", lambda url: (0, "200", b"ok", ""))

    assert app_verify.main([]) == 0
    out = capsys.readouterr().out
    assert "Status: OK (HTTP 200)" in out
    assert "Body:" not in out
    assert "Verification passed: 1/1 checks succeeded." in out


def test_chart_recipes_are_listed(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(["--list"], generic_app_stub_env)

    assert result.returncode == 0
    assert "app-chart-status" in result.stdout
    assert "app-chart-bump" in result.stdout


def test_app_chart_status_reports_pin_and_stale_latest(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CHART_LATEST_STUB"] = "9.9.9"

    result = _run_just(["app-chart-status", "app=tokenplace"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "app: tokenplace" in result.stdout
    assert "chart ref: oci://ghcr.io/futuroptimist/charts/tokenplace" in result.stdout
    assert "pinned version: 0.1.3" in result.stdout
    assert "chart appVersion: main-deadbee" in result.stdout
    assert "Pinned chart appears stale: 0.1.3 < 9.9.9" in result.stdout
    assert "Run: just app-chart-bump app=tokenplace version=9.9.9" in result.stdout


def test_app_chart_latest_version_falls_back_to_user_owned_ghcr_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args[-1])
        if "/orgs/" in args[-1]:
            return subprocess.CompletedProcess(args, 22, "", "not found")
        return subprocess.CompletedProcess(
            args,
            0,
            '[{"metadata":{"container":{"tags":["0.1.3","0.1.4-rc.1","0.1.4"]}}}]',
            "",
        )

    monkeypatch.delenv("SUGARKUBE_APP_CHART_LATEST_STUB", raising=False)
    monkeypatch.setattr(app_chart, "run", fake_run)

    latest, source = app_chart.latest_version("oci://ghcr.io/futuroptimist/charts/tokenplace")

    assert latest == "0.1.4"
    assert source == "GitHub/GHCR API"
    assert "/orgs/futuroptimist/packages/container/charts%2Ftokenplace/versions" in calls[0]
    assert "/users/futuroptimist/packages/container/charts%2Ftokenplace/versions" in calls[1]


def test_app_chart_bump_updates_only_pin_file_in_temp_config(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    pin = tmp_path / "tokenplace.version"
    pin.write_text("# Default tokenplace chart version.\n0.1.0\n", encoding="utf-8")
    config = tmp_path / "tokenplace.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=tokenplace",
                "SUGARKUBE_RELEASE=tokenplace",
                "SUGARKUBE_NAMESPACE=tokenplace",
                "SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/tokenplace",
                f"SUGARKUBE_VERSION_FILE={pin}",
                "SUGARKUBE_PROD_TAG_FILE=docs/apps/tokenplace.prod.tag",
                "SUGARKUBE_VALUES_DEV=docs/examples/tokenplace.values.dev.yaml",
                "SUGARKUBE_VALUES_STAGING=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml",
                "SUGARKUBE_VALUES_PROD=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CONFIG_DIR"] = str(tmp_path)
    result = _run_just(
        ["app-chart-bump", "app=tokenplace", "version=0.1.3"],
        env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert pin.read_text(encoding="utf-8") == "# Default tokenplace chart version.\n0.1.3\n"
    assert "git add" in result.stdout
    helm_log = Path(env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.3" in helm_log


def test_app_chart_bump_refuses_empty_version(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(["app-chart-bump", "app=tokenplace", "version="], generic_app_stub_env)

    assert result.returncode != 0
    assert "version must not be empty" in result.stderr


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
    if app == "tokenplace":
        assert (
            "show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.3" in helm_log
        )
        assert "template tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in helm_log
        assert "--version 0.1.3" in helm_log
        assert "--version 9.9.9" not in helm_log


def test_app_deploy_fails_tokenplace_when_manifest_metadata_env_missing(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_TEMPLATE_MISSING_META"] = "1"

    result = _run_just(["app-deploy", "app=tokenplace", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode != 0
    assert "missing required metadata env vars" in result.stderr
    assert "TOKENPLACE_IMAGE_TAG" in result.stderr
    assert "just app-chart-status app=tokenplace" in result.stderr
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "upgrade tokenplace" not in helm_log


def test_app_deploy_fails_tokenplace_when_metadata_names_only_in_comments(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_TEMPLATE_COMMENT_META"] = "1"

    result = _run_just(["app-deploy", "app=tokenplace", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode != 0
    assert "missing required metadata env vars" in result.stderr
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "upgrade tokenplace" not in helm_log


def test_app_deploy_passes_tokenplace_when_manifest_metadata_env_present(
    generic_app_stub_env: dict[str, str],
) -> None:
    pin_path = REPO_ROOT / "docs/apps/tokenplace.version"
    before_pin = pin_path.read_text(encoding="utf-8")
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CHART_LATEST_STUB"] = "9.9.9"

    result = _run_just(["app-deploy", "app=tokenplace", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "chart pin: docs/apps/tokenplace.version" in result.stdout
    _assert_chart_pin_reminder(result.stdout, "tokenplace")
    assert "9.9.9" not in result.stdout
    assert pin_path.read_text(encoding="utf-8") == before_pin
    helm_log = Path(env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--version 0.1.3" in helm_log
    assert "--version 9.9.9" not in helm_log


def test_app_redeploy_prints_chart_pin_reminder_without_latest_lookup_or_pin_mutation(
    generic_app_stub_env: dict[str, str],
) -> None:
    pin_path = REPO_ROOT / "docs/apps/tokenplace.version"
    before_pin = pin_path.read_text(encoding="utf-8")
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CHART_LATEST_STUB"] = "9.9.9"

    result = _run_just(["app-redeploy", "app=tokenplace", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode == 0, result.stderr + result.stdout
    _assert_chart_pin_reminder(result.stdout, "tokenplace")
    assert "9.9.9" not in result.stdout
    assert pin_path.read_text(encoding="utf-8") == before_pin
    helm_log = Path(env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "upgrade tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in helm_log
    assert "--version 0.1.3" in helm_log
    assert "--version 9.9.9" not in helm_log


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
    if recipe == "tokenplace-oci-deploy":
        _assert_chart_pin_reminder(result.stdout, "tokenplace")
        assert result.stdout.count("NOTE: chart pins are explicit") == 1


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
        "curl -fsS https://example.test/api/v1/meta",
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
        ("tokenplace", "/,/livez,/healthz,/relay/diagnostics,/api/v1/meta"),
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


@pytest.mark.usefixtures("ensure_just_available")
def test_app_cors_verify_tokenplace_staging_options_and_actual_curl(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "CORS verification passed" in result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "--kube-context sugar-staging" in helm_log
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "-X OPTIONS" in curl_log
    assert "Origin: https://cors-smoke.invalid" in curl_log
    assert "Access-Control-Request-Method: POST" in curl_log
    assert "Access-Control-Request-Headers: content-type" in curl_log
    assert "https://example.test/api/v1/chat/completions" in curl_log
    assert "--data-raw {}" in curl_log


def test_app_cors_verify_arbitrary_origin_propagates(generic_app_stub_env: dict[str, str]) -> None:
    result = _run_just(
        [
            "app-cors-verify",
            "app=tokenplace",
            "env=staging",
            "origin=https://unrelated-client.example",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "Origin: https://unrelated-client.example" in curl_log


@pytest.mark.parametrize(
    ("env_key", "env_value", "message"),
    [
        ("SUGARKUBE_STUB_CORS_ACAO", "__missing__", "missing Access-Control-Allow-Origin"),
        ("SUGARKUBE_STUB_CORS_ACAO", "__origin__", "echoed the test Origin"),
        ("SUGARKUBE_STUB_CORS_CREDENTIALS", "true", "Access-Control-Allow-Credentials"),
        (
            "SUGARKUBE_STUB_CORS_METHODS",
            "GET, OPTIONS",
            "Access-Control-Allow-Methods must contain POST",
        ),
        (
            "SUGARKUBE_STUB_CORS_HEADERS",
            "authorization",
            "Access-Control-Allow-Headers must contain content-type",
        ),
    ],
)
def test_app_cors_verify_preflight_failures(
    generic_app_stub_env: dict[str, str], env_key: str, env_value: str, message: str
) -> None:
    env = generic_app_stub_env.copy()
    env[env_key] = env_value

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    assert message in result.stderr
    assert "just app-status app=tokenplace env=staging" in result.stderr
    assert "intended immutable image tag" in result.stderr


@pytest.mark.parametrize("status", ["403", "404", "405", "500", "503"])
def test_app_cors_verify_actual_rejects_forbidden_missing_method_and_5xx(
    generic_app_stub_env: dict[str, str], status: str
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CORS_ACTUAL_STATUS"] = status

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    assert f"status={status}" in result.stderr
    assert "actual status must be one of [400, 429]" in result.stderr


def test_app_cors_verify_actual_400_with_wildcard_succeeds(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CORS_ACTUAL_STATUS"] = "400"
    env["SUGARKUBE_STUB_CORS_ACAO"] = "*"

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode == 0, result.stderr + result.stdout


def test_app_cors_verify_accepts_wildcard_methods_and_headers(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CORS_METHODS"] = "*"
    env["SUGARKUBE_STUB_CORS_HEADERS"] = "*"

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode == 0, result.stderr + result.stdout


def test_app_cors_verify_actual_sends_configured_request_headers(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    config = tmp_path / "tokenplace.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=tokenplace",
                "SUGARKUBE_RELEASE=tokenplace",
                "SUGARKUBE_NAMESPACE=tokenplace",
                "SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/tokenplace",
                "SUGARKUBE_VERSION=0.1.3",
                "SUGARKUBE_VALUES_STAGING=deploy/helm/tokenplace/values.staging.yaml",
                "SUGARKUBE_CORS_VERIFY_PATH=/api/v1/chat/completions",
                "SUGARKUBE_CORS_VERIFY_METHOD=POST",
                "SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS=x-custom-one,x-custom-two",
                "SUGARKUBE_CORS_VERIFY_BODY={}",
                "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES=400,429",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CORS_HEADERS"] = "x-custom-one,x-custom-two"

    result = _run_just(
        ["app-cors-verify", "app=tokenplace", "env=staging", f"config={config}"], env
    )

    assert result.returncode == 0, result.stderr + result.stdout
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "Access-Control-Request-Headers: x-custom-one,x-custom-two" in curl_log
    assert "x-custom-one: cors-smoke" in curl_log
    assert "x-custom-two: cors-smoke" in curl_log
    assert "Content-Type: application/json" in curl_log


def test_app_cors_verify_rejects_any_curl_error(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CURL_EXIT"] = "18"

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    assert "CORS verification failed" in result.stderr


def test_app_cors_verify_actual_rejects_nonzero_curl_with_expected_response(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CORS_ACTUAL_STATUS"] = "400"
    env["SUGARKUBE_STUB_CORS_ACTUAL_ACAO"] = "*"
    env["SUGARKUBE_STUB_CORS_ACTUAL_CURL_EXIT"] = "18"

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    assert "CORS verification failed" in result.stderr
    assert "app=tokenplace env=staging host=https://example.test" in result.stderr
    assert "path=/api/v1/chat/completions" in result.stderr
    assert "origin=https://cors-smoke.invalid status=400" in result.stderr
    assert "transfer closed with outstanding read data remaining" in result.stderr


def test_app_cors_verify_bad_expected_statuses_is_operator_error(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    config = tmp_path / "tokenplace.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=tokenplace",
                "SUGARKUBE_RELEASE=tokenplace",
                "SUGARKUBE_NAMESPACE=tokenplace",
                "SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/tokenplace",
                "SUGARKUBE_VERSION=0.1.3",
                "SUGARKUBE_VALUES_STAGING=deploy/helm/tokenplace/values.staging.yaml",
                "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES=400,abc",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_just(
        ["app-cors-verify", "app=tokenplace", "env=staging", f"config={config}"],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "must be comma-separated integers" in result.stderr
    assert "Traceback" not in result.stderr


def test_app_cors_verify_config_third_argument_remains_config(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    config = tmp_path / "tokenplace.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=tokenplace",
                "SUGARKUBE_RELEASE=tokenplace",
                "SUGARKUBE_NAMESPACE=tokenplace",
                "SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/tokenplace",
                "SUGARKUBE_VERSION=0.1.3",
                "SUGARKUBE_VALUES_STAGING=deploy/helm/tokenplace/values.staging.yaml",
                "SUGARKUBE_CORS_VERIFY_PATH=/custom-cors",
                "SUGARKUBE_CORS_VERIFY_METHOD=POST",
                "SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS=content-type",
                "SUGARKUBE_CORS_VERIFY_BODY={}",
                "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES=200",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_just(
        ["app-cors-verify", "app=tokenplace", "env=staging", f"config={config}", "print_only=1"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "https://example.test/custom-cors" in result.stdout
    assert "Origin: https://cors-smoke.invalid" in result.stdout


def test_app_cors_verify_print_only_performs_no_network_calls(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-cors-verify", "app=tokenplace", "env=staging", "print_only=1"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "curl -i -sS -X OPTIONS" in result.stdout
    assert "Access-Control-Request-Headers: content-type" in result.stdout
    assert "curl -i -sS -X POST" in result.stdout
    assert "--data-raw '{}'" in result.stdout
    assert not Path(generic_app_stub_env["CURL_LOG"]).exists()


def test_app_config_emits_generic_cors_fields_safely() -> None:
    result = subprocess.run(
        [
            "python3",
            "scripts/app_config.py",
            "shell",
            "--app",
            "tokenplace",
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
    assert "export SUGARKUBE_CORS_VERIFY_PATH=/api/v1/chat/completions" in result.stdout
    assert "export SUGARKUBE_CORS_VERIFY_BODY='{}'" in result.stdout
    assert "export SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES=400,429" in result.stdout


def test_app_config_rejects_unknown_app_config_keys(tmp_path: Path) -> None:
    config = tmp_path / "bad.env"
    config.write_text(
        "SUGARKUBE_APP=bad\nSUGARKUBE_RELEASE=bad\nSUGARKUBE_NAMESPACE=bad\nSUGARKUBE_CHART=oci://example/bad\nSUGARKUBE_VERSION=0.1.0\nSUGARKUBE_VALUES_STAGING=values.yaml\nSUGARKUBE_UNKNOWN=1\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            "scripts/app_config.py",
            "json",
            "--app",
            "bad",
            "--env",
            "staging",
            "--config",
            str(config),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "unknown app config key 'SUGARKUBE_UNKNOWN'" in result.stderr


def _cors_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "SUGARKUBE_APP": "tokenplace",
        "SUGARKUBE_ENV": "staging",
        "SUGARKUBE_CORS_VERIFY_PATH": "/api/v1/chat/completions",
        "SUGARKUBE_CORS_VERIFY_METHOD": "POST",
        "SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS": "content-type",
        "SUGARKUBE_CORS_VERIFY_BODY": "{}",
        "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES": "400,429",
    }
    if overrides:
        env.update(overrides)
    return env


def _cors_headers(extra: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    headers = {
        "access-control-allow-origin": ["*"],
        "access-control-allow-methods": ["POST, OPTIONS"],
        "access-control-allow-headers": ["content-type"],
    }
    if extra:
        headers.update(extra)
    return headers


def _run_app_cors_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    env: dict[str, str] | None = None,
    responses: list[tuple[int, str, dict[str, list[str]], bytes, str]] | None = None,
    host: str = "example.test",
    errors: list[str] | None = None,
    argv: list[str] | None = None,
) -> tuple[int, str, str, list[list[str]]]:
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from scripts import app_cors_verify

    for key in [
        "SUGARKUBE_APP",
        "SUGARKUBE_ENV",
        "SUGARKUBE_CORS_VERIFY_PATH",
        "SUGARKUBE_CORS_VERIFY_METHOD",
        "SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS",
        "SUGARKUBE_CORS_VERIFY_BODY",
        "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES",
        "SUGARKUBE_CORS_VERIFY_PRINT_ONLY",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in _cors_env(env).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(app_cors_verify, "discover_host", lambda kube_context: (host, errors or []))
    calls: list[list[str]] = []
    pending = list(
        responses
        or [
            (0, "204", _cors_headers(), b"", ""),
            (0, "400", _cors_headers(), b'{"error":{"message":"invalid request"}}', ""),
        ]
    )

    def fake_run_curl(args: list[str]) -> tuple[int, str, dict[str, list[str]], bytes, str]:
        calls.append(args)
        return pending.pop(0)

    monkeypatch.setattr(app_cors_verify, "run_curl", fake_run_curl)

    rc = app_cors_verify.main(argv or [])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err, calls


def test_app_cors_verify_main_success_exercises_preflight_and_actual(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, calls = _run_app_cors_main(monkeypatch, capsys)

    assert rc == 0, err + out
    assert "Verifying CORS for tokenplace env=staging" in out
    assert "CORS verification passed" in out
    assert len(calls) == 2
    assert calls[0][:2] == ["-X", "OPTIONS"]
    assert calls[1][:2] == ["-X", "POST"]
    assert "--data-raw" in calls[1]


def test_app_cors_verify_main_rejects_authorization_wildcard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        env={"SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS": "authorization"},
        responses=[
            (
                0,
                "204",
                _cors_headers({"access-control-allow-headers": ["*"]}),
                b"",
                "",
            ),
        ],
    )

    assert rc == 1
    assert "Access-Control-Allow-Headers must contain authorization" in err
    assert "app=tokenplace env=staging host=https://example.test" in err


def test_app_cors_verify_main_accepts_non_authorization_wildcard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        env={"SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS": "x-custom-token"},
        responses=[
            (
                0,
                "204",
                _cors_headers({"access-control-allow-headers": ["*"]}),
                b"",
                "",
            ),
            (0, "400", _cors_headers(), b'{"error":{"message":"invalid request"}}', ""),
        ],
    )

    assert rc == 0, err + out


def test_app_cors_verify_main_reports_bad_actual_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[
            (0, "204", _cors_headers(), b"", ""),
            (0, "503", _cors_headers(), b'{"error":{"message":"unavailable"}}', ""),
        ],
    )

    assert rc == 1
    assert "status=503" in err
    assert "actual status must be one of [400, 429]" in err


def test_app_cors_verify_main_print_only_uses_placeholder_when_host_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        host="",
        errors=["helm get values failed"],
        argv=["--print-only"],
    )

    assert rc == 0
    assert calls == []
    assert "helm get values failed" in err
    assert "https://<host>/api/v1/chat/completions" in out
    assert "curl -i -sS" in out
