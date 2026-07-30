"""Stubbed just tests for generic Sugarkube app recipes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import app_chart
from scripts import app_verify
from scripts import dspace_release_manifest as release_manifest
from scripts.app_verify import base_url_from_host, tokenplace_meta_failure

REPO_ROOT = Path(__file__).resolve().parents[1]


def _release_deployment(app: str, body: str = "") -> str:
    container = "relay" if app == "tokenplace" else app
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app}
  labels:
    app.kubernetes.io/instance: {app}
spec:
  template:
    spec:
      containers:
        - name: {container}
          image: ghcr.io/example/{app}:main-deadbee
{body}"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def generic_app_stub_env(tmp_path: Path, ensure_just_available: Path) -> dict[str, str]:
    assert ensure_just_available.exists()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "helm.log"
    smoke = bin_dir / "dspace-smoke"
    _write_executable(smoke, "#!/bin/sh\nexit 0\n")
    runtime_verifier = bin_dir / "dspace-runtime-verifier"
    _write_executable(
        runtime_verifier,
        """#!/usr/bin/env python3
import json
import sys
args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]
if args[0] == "capabilities":
    print(json.dumps({"schemaVersion": 1, "environment": value("--environment"), "release": value("--release"), "namespace": value("--namespace"), "capabilities": ["applicationVersion", "runtimeSourceRevision", "frontendSourceRevision", "defaultProvider", "publicJourneys"]}))
else:
    manifest = json.load(open(value("--manifest"), encoding="utf-8"))
    print(json.dumps({"schemaVersion": 1, "environment": value("--environment"), "release": value("--release"), "namespace": value("--namespace"), "applicationVersion": manifest["applicationVersion"], "runtimeSourceRevision": manifest["sourceRevision"], "frontendSourceRevision": manifest["sourceRevision"], "defaultProvider": manifest["expectedDefaultChatProvider"], "journeys": [{"name": "/build-info.json", "passed": True}, {"name": "/", "passed": True}, {"name": "/chat", "passed": True}]}))
""",
    )
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
printf 'kubectl %s\n' "$*" >> {str(tmp_path / "commands.log")!r}
if [[ "$*" == *"get pods"* && "$*" == *"-o json"* ]]; then
  printf '{{"items":[{{"metadata":{{"name":"dspace-0","labels":{{"app.kubernetes.io/name":"dspace","app.kubernetes.io/instance":"dspace"}},"ownerReferences":[{{"kind":"ReplicaSet","name":"dspace-rs","uid":"rs-uid","controller":true}}]}},"spec":{{"containers":[{{"name":"dspace","image":"ghcr.io/democratizedspace/dspace:main-abcdef0"}}]}},"status":{{"phase":"Running","startTime":"2026-07-26T12:10:00Z","conditions":[{{"type":"Ready","status":"True"}}],"containerStatuses":[{{"name":"dspace","imageID":"ghcr.io/democratizedspace/dspace@sha256:%s","state":{{"running":{{}}}}}}]}}}}]}}\n' "${{SUGARKUBE_STUB_IMAGE_DIGEST_HEX:-1111111111111111111111111111111111111111111111111111111111111111}}"
  exit 0
fi
if [[ "$*" == *"get replicasets,deployments"* && "$*" == *"-o json"* ]]; then
  printf '{{"items":[{{"kind":"ReplicaSet","metadata":{{"name":"dspace-rs","uid":"rs-uid","labels":{{"app.kubernetes.io/name":"dspace","app.kubernetes.io/instance":"dspace"}},"ownerReferences":[{{"kind":"Deployment","name":"dspace","uid":"deploy-uid","controller":true}}]}}}},{{"kind":"Deployment","metadata":{{"name":"dspace","uid":"deploy-uid","labels":{{"app.kubernetes.io/name":"dspace","app.kubernetes.io/instance":"dspace","app.kubernetes.io/managed-by":"Helm"}},"annotations":{{"meta.helm.sh/release-name":"dspace","meta.helm.sh/release-namespace":"dspace"}}}}}}]}}\n'
  exit 0
fi
if [[ "$*" == *"get nodes -o json"* ]]; then
  env_label="${{SUGARKUBE_STUB_NODE_ENV:-staging}}"
  cluster_label="${{SUGARKUBE_STUB_CLUSTER:-sugar}}"
  printf '{{"items":[{{"metadata":{{"name":"sugarkube3","labels":{{"sugarkube.env":"%s","sugarkube.cluster":"%s"}}}}}},{{"metadata":{{"name":"sugarkube4","labels":{{"sugarkube.env":"%s","sugarkube.cluster":"%s"}}}}}}]}}\n' "$env_label" "$cluster_label" "$env_label" "$cluster_label"
  exit 0
fi
if [[ "$*" == *"config current-context"* ]]; then printf 'sugar-prod\n'; exit 0; fi
if [[ "$*" == *"config view"* ]]; then printf 'https://127.0.0.1:6443'; exit 0; fi
if [[ "$*" == *"get deploy,statefulset,daemonset"* ]]; then
  printf 'Deployment/danielsmith\n'
  exit 0
fi
if [[ "$*" == *"get deploy,statefulset"* ]]; then
  printf 'Deployment/tokenplace\n'
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
printf 'helm %s\n' "$*" >> {str(tmp_path / "commands.log")!r}
if [ "${{1:-}}" = upgrade ]; then
  previous=""
  for argument in "$@"; do
    if [ "$previous" = --description ]; then
      printf '%s' "$argument" > {str(tmp_path / "helm-description")!r}
      break
    fi
    previous="$argument"
  done
fi
if [[ "$*" == *"status dspace --namespace dspace -o json" ]]; then
  chart_version=3.1.0
  [ "${{SUGARKUBE_STUB_NODE_ENV:-staging}}" != prod ] || chart_version=3.0.1
  description="$(cat {str(tmp_path / "helm-description")!r} 2>/dev/null || true)"
  printf '{{"name":"dspace","namespace":"dspace","version":7,"info":{{"status":"deployed","description":"%s"}},"chart":{{"metadata":{{"name":"dspace","version":"%s"}}}}}}\n' "$description" "$chart_version"
  exit 0
fi
if [[ "$*" == *"get values"* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_GET_VALUES_FAIL:-}}" = "1" ]; then
    echo 'Error: Kubernetes cluster unreachable for context sugar-staging' >&2
    exit 1
  fi
  printf '{{"ingress":{{"host":"%s"}}}}\n' "${{SUGARKUBE_STUB_HELM_HOST:-example.test}}"
  exit 0
fi
if [[ "$*" == show\ chart* ]]; then
  if [[ "$*" == *"charts/dspace"* ]]; then
    version="${{*: -1}}"
    if [[ "$version" == oci://*@sha256:* ]]; then
      version=3.1.0
      [ "${{SUGARKUBE_STUB_NODE_ENV:-staging}}" != prod ] || version=3.0.1
    fi
    printf 'apiVersion: v2\nname: dspace\nversion: %s\nappVersion: main-abcdef0\n' "$version"
    exit 0
  fi
  printf 'apiVersion: v2\nname: tokenplace\nversion: 0.1.3\nappVersion: main-deadbee\ndigest: sha256:abc123\n'
  exit 0
fi
if [[ "$*" == template* ]]; then
  if [ "${{SUGARKUBE_STUB_HELM_TEMPLATE_FAIL:-}}" = "1" ]; then
    echo 'Error: synthetic helm template failure' >&2
    exit 1
  fi
  if [ "${{SUGARKUBE_STUB_HELM_TEMPLATE_MISSING_META:-}}" = "1" ]; then
    printf 'apiVersion: apps/v1
kind: Deployment
metadata:
  name: tokenplace
  labels:
    app.kubernetes.io/instance: tokenplace
spec:
  template:
    spec:
      containers:
        - name: relay
          image: ghcr.io/example/tokenplace:main-deadbee
---
kind: Ingress
metadata:
  name: tokenplace
spec:
  rules:
    - host: staging.token.place
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
  labels:
    app.kubernetes.io/instance: tokenplace
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
---
kind: Ingress
metadata:
  name: tokenplace
spec:
  rules:
    - host: staging.token.place
'
  else
    release="${{2}}"
    app="${{release}}"
    [ "${{app}}" != tokenplace ] || container=relay
    container="${{container:-${{app}}}}"
    tag=main-deadbee
    previous=""
    for argument in "$@"; do
      if [ "${{previous}}" = --set ] && [[ "${{argument}}" == image.tag=* ]]; then tag="${{argument#image.tag=}}"; fi
      previous="${{argument}}"
    done
    host=example.test
    [[ "$*" != *dspace.values.staging.yaml* ]] || host=staging.democratized.space
    [[ "$*" != *dspace.values.prod.yaml* ]] || host=democratized.space
    [[ "$*" != *dspace.values.prod-subdomain.yaml* ]] || host=prod.democratized.space
    [[ "$*" != *tokenplace.values.staging.yaml* ]] || host=staging.token.place
    [[ "$*" != *tokenplace.values.prod.yaml* ]] || host=token.place
    [[ "$*" != *danielsmith.values.staging.yaml* ]] || host=staging.danielsmith.io
    [[ "$*" != *danielsmith.values.prod.yaml* ]] || host=danielsmith.io
    [[ "$*" != *jobbot3000.values.staging.yaml* ]] || host=staging.jobbot3000.tech
    [[ "$*" != *jobbot3000.values.prod.yaml* ]] || host=jobbot3000.example.test
    cat <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${{release}}
  labels:
    app.kubernetes.io/instance: ${{release}}
spec:
  template:
    spec:
      containers:
        - name: ${{container}}
          image: ghcr.io/example/${{app}}:${{tag}}
          env:
            - name: TOKENPLACE_IMAGE_TAG
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
---
apiVersion: v1
kind: Service
metadata:
  name: ${{release}}
  labels:
    app.kubernetes.io/instance: ${{release}}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${{release}}
  labels:
    app.kubernetes.io/instance: ${{release}}
spec:
  rules:
    - host: ${{host}}
YAML
    if [ "${{app}}" = dspace ] && [[ "$*" == *dspace.values.staging.yaml* ]]; then
      cat <<'YAML'
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: dspace
  labels:
    app.kubernetes.io/instance: dspace
spec:
  endpoints:
    - port: http
      bearerTokenSecret:
        name: dspace-staging-metrics-token
        key: token
YAML
    fi
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
    _write_executable(
        bin_dir / "oras",
        f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

image = "sha256:" + os.environ.get("SUGARKUBE_STUB_RESOLVED_IMAGE", "1" * 64)
chart = "sha256:" + os.environ.get("SUGARKUBE_STUB_RESOLVED_CHART", "2" * 64)
platform = "sha256:" + "3" * 64
image_config = "sha256:" + "4" * 64
chart_config = "sha256:" + "5" * 64
sha = "abcdef0123456789abcdef0123456789abcdef01"
args = sys.argv[1:]
with Path({str(tmp_path / "commands.log")!r}).open("a", encoding="utf-8") as log:
    log.write("oras " + " ".join(args) + "\\n")
ref = args[-1]
if "--descriptor" in args:
    value = {{"digest": chart if "charts/dspace" in ref else image}}
elif args[:2] == ["manifest", "fetch"] and ref.endswith("@" + image):
    value = {{"manifests": [{{"digest": platform}}]}}
elif args[:2] == ["manifest", "fetch"] and ref.endswith("@" + platform):
    value = {{"config": {{"digest": image_config}}}}
elif args[:2] == ["manifest", "fetch"] and ref.endswith("@" + chart):
    value = {{"config": {{"digest": chart_config}}}}
elif args[:2] == ["blob", "fetch"]:
    value = {{"config": {{"Labels": {{"org.opencontainers.image.revision": sha}}}}}}
else:
    raise SystemExit("unexpected oras command: " + " ".join(args))
print(json.dumps(value))
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SUGARKUBE_HELM_ROLLOUT_TIMEOUT"] = "1s"
    env["DSPACE_SMOKE_RUNNER"] = str(smoke)
    env["SUGARKUBE_DSPACE_RUNTIME_VERIFIER"] = str(runtime_verifier)
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
        "apiVersion: v2\nname: \"tokenplace\"\ndigest: 'sha256:abc'\n"
    ) == {
        "apiVersion": "v2",
        "name": "tokenplace",
        "digest": "sha256:abc",
    }
    with pytest.raises(ValueError):
        app_chart.parse_chart_yaml("name: tokenplace\n  malformed: nesting\n")


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
  labels:
    app.kubernetes.io/instance: custom-release
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


def test_app_chart_cmd_preflight_renders_apps_without_specialized_metadata_checks(
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
        lambda cmd: calls.append(" ".join(cmd))
        or subprocess.CompletedProcess(cmd, 0, _release_deployment("danielsmith"), ""),
    )

    assert app_chart.cmd_preflight(args) == 0
    assert calls == [
        "helm template danielsmith oci://ghcr.io/futuroptimist/charts/danielsmith "
        "--namespace danielsmith --version 1.0.0 --set image.tag=main-deadbee "
        "--set image.pullPolicy=Always"
    ]
    assert "app: danielsmith" in capsys.readouterr().out


def test_release_inputs_preserve_exact_versioned_and_digest_template_coordinates() -> None:
    common = dict(
        app="dspace",
        env="staging",
        release="dspace",
        namespace="dspace",
        version="3.1.0",
        values=("base.yaml", "staging.yaml"),
        tag="main-deadbee",
        host="staging.democratized.space",
        pull_policy="IfNotPresent",
    )
    versioned = app_chart.ReleaseInputs(chart="oci://example/charts/dspace", **common)
    digest = app_chart.ReleaseInputs(
        chart="oci://example/charts/dspace@sha256:" + "a" * 64, **common
    )

    assert versioned.helm_template_command() == [
        "helm",
        "template",
        "dspace",
        "oci://example/charts/dspace",
        "--namespace",
        "dspace",
        "--version",
        "3.1.0",
        "-f",
        "base.yaml",
        "-f",
        "staging.yaml",
        "--set",
        "ingress.host=staging.democratized.space",
        "--set",
        "image.tag=main-deadbee",
        "--set",
        "image.pullPolicy=IfNotPresent",
    ]
    assert "--version" not in digest.helm_template_command()
    assert digest.helm_template_command()[3] == digest.chart


def _generic_manifest(
    *,
    release: str = "sample",
    namespace: str = "",
    tag: str = "main-deadbee",
    image_container: str = "sample",
    labels: str = "    app.kubernetes.io/instance: sample",
    host: str = "",
) -> str:
    namespace_line = f"  namespace: {namespace}\n" if namespace else ""
    ingress = ""
    if host:
        ingress = f"""---
kind: Ingress
metadata:
  name: {release}
  labels:
    app.kubernetes.io/instance: {release}
spec:
  rules:
    - host: {host}
"""
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {release}
{namespace_line}  labels:
{labels}
spec:
  template:
    spec:
      initContainers:
        - name: sample
          image: example/sample:ignored-deadbee
      containers:
        - name: {image_container}
          image: example/sample:{tag}
{ingress}"""


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ("kind: ConfigMap\ndata:\n  tag: main-deadbee\n", "no rollout-capable"),
        (_generic_manifest(tag="wrong-deadbee"), "exact requested image tag"),
        (_generic_manifest(image_container="sidecar"), "exact requested image tag"),
        (_generic_manifest(labels="    app.kubernetes.io/instance: other"), "supported label"),
        (_generic_manifest(namespace="wrong"), "has namespace 'wrong'"),
        (_generic_manifest(), "expected host"),
        (_generic_manifest(host="other.example.test"), "expected host"),
    ],
)
def test_generic_render_contract_rejects_structural_mismatches(manifest: str, message: str) -> None:
    inputs = app_chart.ReleaseInputs(
        "sample",
        "staging",
        "sample",
        "sample",
        "oci://example/charts/sample",
        "1.0.0",
        (),
        "main-deadbee",
        "sample.example.test",
    )
    assert any(message in error for error in app_chart.validate_rendered_manifest(manifest, inputs))


@pytest.mark.parametrize("wrong_first", [False, True])
def test_generic_render_contract_rejects_wrong_image_in_any_coherent_workload(
    wrong_first: bool,
) -> None:
    correct = _generic_manifest()
    wrong = _generic_manifest(release="sample-worker", tag="wrong-deadbee").replace(
        "app.kubernetes.io/instance: sample-worker",
        "app.kubernetes.io/instance: sample",
    )
    manifest = "\n---\n".join((wrong, correct) if wrong_first else (correct, wrong))
    inputs = app_chart.ReleaseInputs(
        "sample", "staging", "sample", "sample", "chart", "1.0.0", (), "main-deadbee", ""
    )

    errors = app_chart.validate_rendered_manifest(manifest, inputs)

    assert any("Deployment sample-worker container sample" in error for error in errors)
    assert any("exact requested image tag" in error for error in errors)


def test_generic_render_contract_ignores_wrong_image_in_unassociated_workload() -> None:
    associated = _generic_manifest().replace(
        "image: example/sample:main-deadbee",
        "image: example/sample:main-deadbee\n        - name: metrics\n          image: example/metrics:wrong",
    )
    unrelated = _generic_manifest(
        release="other", tag="wrong-deadbee", labels="    app.kubernetes.io/instance: other"
    )
    inputs = app_chart.ReleaseInputs(
        "sample", "staging", "sample", "sample", "chart", "1.0.0", (), "main-deadbee", ""
    )

    assert app_chart.validate_rendered_manifest(f"{associated}\n---\n{unrelated}", inputs) == []


def test_render_contract_normalizes_quoted_host_and_scopes_namespace_to_metadata() -> None:
    manifest = _generic_manifest(host='"sample.example.test"')
    manifest = manifest.replace("spec:\n  template:", "spec:\n  namespace: unrelated\n  template:")
    inputs = app_chart.ReleaseInputs(
        "sample",
        "staging",
        "sample",
        "sample",
        "oci://example/charts/sample",
        "1.0.0",
        (),
        "main-deadbee",
        "sample.example.test",
    )

    assert app_chart.validate_rendered_manifest(manifest, inputs) == []


def test_values_null_overlay_clears_inherited_scalars(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "ingress:\n  enabled: true\n  host: inherited.example.test\n"
        "metrics:\n  auth:\n    existingSecret: inherited\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "ingress:\n  enabled: false\n  host: null\n" "metrics:\n  auth:\n    existingSecret: ~\n",
        encoding="utf-8",
    )
    values = (str(base), str(overlay))

    assert app_chart.expected_ingress_host(values, "") == ""
    assert app_chart.resolved_values_scalar(values, ("metrics", "auth", "existingSecret")) == ""


@pytest.mark.parametrize("null_value", ["null", "~"])
def test_parent_null_overlay_clears_inherited_ingress(tmp_path: Path, null_value: str) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text("ingress:\n  enabled: true\n  host: inherited.example.test\n", encoding="utf-8")
    overlay.write_text(f"ingress: {null_value}\n", encoding="utf-8")

    assert app_chart.expected_ingress_host((str(base), str(overlay)), "") == ""


@pytest.mark.parametrize("null_value", ["null", "~"])
def test_parent_null_overlay_clears_inherited_metrics(tmp_path: Path, null_value: str) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "metrics:\n  enabled: true\n  auth:\n"
        "    existingSecret: inherited\n    secretKey: token\n",
        encoding="utf-8",
    )
    overlay.write_text(f"metrics: {null_value}\n", encoding="utf-8")
    values = (str(base), str(overlay))

    assert app_chart.resolved_values_scalar(values, ("metrics", "enabled")) == ""
    assert app_chart.resolved_values_scalar(values, ("metrics", "auth", "existingSecret")) == ""
    assert app_chart.resolved_values_scalar(values, ("metrics", "auth", "secretKey")) == ""


def test_later_mapping_repopulates_null_overlay(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    cleared = tmp_path / "cleared.yaml"
    restored = tmp_path / "restored.yaml"
    base.write_text("ingress:\n  enabled: true\n  host: inherited.example.test\n", encoding="utf-8")
    cleared.write_text("ingress: null\n", encoding="utf-8")
    restored.write_text(
        "ingress:\n  enabled: true\n  host: restored.example.test\n", encoding="utf-8"
    )

    assert (
        app_chart.expected_ingress_host((str(base), str(cleared), str(restored)), "")
        == "restored.example.test"
    )


@pytest.mark.parametrize("null_value", ["null", "~"])
def test_dspace_null_overlay_metrics_is_render_safe(tmp_path: Path, null_value: str) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    base.write_text(
        "metrics:\n  enabled: true\n  auth:\n"
        "    existingSecret: inherited\n    secretKey: token\n"
        "serviceMonitor:\n  enabled: true\n",
        encoding="utf-8",
    )
    overlay.write_text(f"metrics: {null_value}\n", encoding="utf-8")
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "staging",
        "dspace",
        "dspace",
        "chart",
        "1.0.0",
        (str(base), str(overlay)),
        "main-deadbee",
    )

    assert app_chart.validate_dspace_values("", inputs) == []


def test_enabled_ingress_requires_resolved_host(tmp_path: Path) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("ingress:\n  enabled: true\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="no nonempty ingress.host"):
        app_chart.expected_ingress_host((str(values),), "")


def test_resolve_host_reports_values_parsing_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("ingress: [invalid\n", encoding="utf-8")
    args = argparse.Namespace(values=str(values), host="")

    assert app_chart.cmd_resolve_host(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: values parsing failed while resolving ingress host:" in captured.err
    assert "Traceback" not in captured.err


def test_resolve_host_reports_missing_enabled_ingress_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("ingress:\n  enabled: true\n", encoding="utf-8")
    args = argparse.Namespace(values=str(values), host="")

    assert app_chart.cmd_resolve_host(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no nonempty ingress.host was resolved" in captured.err
    assert "Traceback" not in captured.err


def test_resolve_host_prints_effective_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text("ingress:\n  host: values.example.test\n", encoding="utf-8")
    args = argparse.Namespace(values=f" , {values}, ", host="override.example.test")

    assert app_chart.cmd_resolve_host(args) == 0
    captured = capsys.readouterr()
    assert captured.out == "override.example.test\n"
    assert captured.err == ""


def test_dspace_render_contract_requires_resources_and_validates_metrics() -> None:
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "staging",
        "dspace",
        "dspace",
        "oci://example/charts/dspace",
        "3.1.0",
        (),
        "main-deadbee",
        "staging.democratized.space",
    )
    deployment = _generic_manifest(
        release="dspace",
        image_container="dspace",
        host="staging.democratized.space",
        labels="    app.kubernetes.io/instance: dspace",
    )
    missing_service = app_chart.validate_rendered_manifest(deployment, inputs)
    assert "DSPACE intended Service did not render" in missing_service
    invalid_monitor = deployment + """---
kind: Service
metadata:
  name: dspace
  labels:
    app.kubernetes.io/instance: dspace
---
kind: ServiceMonitor
metadata:
  name: dspace
  labels:
    app.kubernetes.io/instance: dspace
spec:
  endpoints:
    - port: http
      bearerTokenSecret:
        name: ''
        key: ''
"""
    assert any(
        "bearerTokenSecret" in error
        for error in app_chart.validate_rendered_manifest(invalid_monitor, inputs)
    )


def test_dspace_resources_require_release_association() -> None:
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "staging",
        "dspace",
        "dspace",
        "chart",
        "3.1.0",
        (),
        "main-deadbee",
        "staging.democratized.space",
    )
    manifest = (
        _generic_manifest(
            release="dspace",
            image_container="dspace",
            labels="    app.kubernetes.io/instance: another-release",
        )
        + """---
kind: Service
metadata:
  name: dspace
---
kind: Ingress
metadata:
  name: dspace
spec:
  rules:
    - host: staging.democratized.space
---
kind: ServiceMonitor
metadata:
  name: dspace
spec:
  endpoints:
    - bearerTokenSecret:
        name: dspace-staging-metrics-token
        key: token
"""
    )

    errors = app_chart.validate_rendered_manifest(manifest, inputs)
    assert "DSPACE intended Service did not render" in errors
    assert "DSPACE intended Ingress did not render" in errors
    assert "no Ingress rule exactly matches expected host 'staging.democratized.space'" in errors


def test_dspace_servicemonitor_requires_every_endpoint_authentication() -> None:
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "staging",
        "dspace",
        "dspace",
        "chart",
        "3.1.0",
        (),
        "main-deadbee",
    )
    manifest = """kind: ServiceMonitor
metadata:
  name: dspace
  labels:
    app.kubernetes.io/instance: dspace
spec:
  endpoints:
    - bearerTokenSecret:
        name: dspace-staging-metrics-token
        key: token
    - bearerTokenSecret:
        name: dspace-staging-metrics-token
"""

    assert any(
        "bearerTokenSecret" in error
        for error in app_chart.validate_rendered_manifest(manifest, inputs)
    )


def test_dspace_servicemonitor_uses_rendered_default_token_key(tmp_path: Path) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(
        "metrics:\n  enabled: true\n  auth:\n"
        "    existingSecret: dspace-staging-metrics-token\n"
        "serviceMonitor:\n  enabled: true\n",
        encoding="utf-8",
    )
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "staging",
        "dspace",
        "dspace",
        "chart",
        "3.1.0",
        (str(values),),
        "main-deadbee",
    )
    manifest = """kind: ServiceMonitor
metadata:
  labels:
    app.kubernetes.io/instance: dspace
spec:
  endpoints:
    - bearerTokenSecret:
        name: dspace-staging-metrics-token
        key: token
"""

    assert app_chart.validate_dspace_values(manifest, inputs) == []


def test_dspace_values_ignore_unrelated_servicemonitor(tmp_path: Path) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(
        "metrics:\n  enabled: true\n  auth:\n    existingSecret: expected\n"
        "serviceMonitor:\n  enabled: true\n",
        encoding="utf-8",
    )
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "staging",
        "dspace",
        "dspace",
        "chart",
        "3.1.0",
        (str(values),),
        "main-deadbee",
    )
    unrelated = """kind: ServiceMonitor
metadata:
  labels:
    app.kubernetes.io/instance: unrelated
spec:
  endpoints: []
"""

    assert app_chart.validate_dspace_values(unrelated, inputs) == [
        "DSPACE configured ServiceMonitor did not render"
    ]


def test_dspace_production_rejects_staging_metrics_leaks() -> None:
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "prod",
        "dspace",
        "dspace",
        "oci://example/charts/dspace",
        "3.0.1",
        (),
        "main-deadbee",
        "democratized.space",
    )
    manifest = (
        _generic_manifest(
            release="dspace",
            image_container="dspace",
            host="democratized.space",
            labels="    app.kubernetes.io/instance: dspace",
        )
        + """---
kind: Service
metadata:
  name: dspace
  labels:
    app.kubernetes.io/instance: dspace
---
kind: ConfigMap
metadata:
  name: dspace
  labels:
    app.kubernetes.io/instance: dspace
data:
  leaked-secret: dspace-staging-metrics-token
"""
    )
    assert "DSPACE production rendered staging-only metrics configuration" in (
        app_chart.validate_rendered_manifest(manifest, inputs)
    )


@pytest.mark.parametrize("leak", ["METRICS_TOKEN", "dspace-staging-metrics-token", "sugarkube-int"])
def test_dspace_production_checks_only_release_associated_structure(leak: str) -> None:
    inputs = app_chart.ReleaseInputs(
        "dspace",
        "prod",
        "dspace",
        "dspace",
        "chart",
        "3.1.0",
        (),
        "main-deadbee",
        "democratized.space",
    )
    base = (
        _generic_manifest(
            release="dspace",
            image_container="dspace",
            host="democratized.space",
            labels="    app.kubernetes.io/instance: dspace",
        )
        + """---
kind: Service
metadata:
  labels:
    app.kubernetes.io/instance: dspace
"""
    )
    unrelated = base + f"""---
# {leak}
kind: ConfigMap
metadata:
  labels:
    app.kubernetes.io/instance: unrelated
data:
  value: {leak}
"""
    associated = base + f"""---
kind: ConfigMap
metadata:
  labels:
    app.kubernetes.io/instance: dspace
data:
  value: {leak}
"""

    assert "DSPACE production rendered staging-only metrics configuration" not in (
        app_chart.validate_rendered_manifest(unrelated, inputs)
    )
    assert "DSPACE production rendered staging-only metrics configuration" in (
        app_chart.validate_rendered_manifest(associated, inputs)
    )


def test_app_chart_cmd_preflight_reports_helm_template_failure(
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
        host="staging.example.test",
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
    error = capsys.readouterr().err
    _assert_preflight_failure_context(error, "helm template")
    assert "render failed" in error


def test_app_chart_cmd_preflight_reports_helm_show_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(
        "ingress:\n"
        "  enabled: true\n"
        "  host: staging.example.test\n"
        "unrelatedSecret: sentinel-super-secret\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values=str(values),
    )
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 3, "", "chart missing"),
    )

    assert app_chart.cmd_preflight(args) == 3
    error = capsys.readouterr().err
    _assert_preflight_failure_context(error, "helm show")
    assert "chart missing" in error
    assert "<from-values>" not in error


def test_app_chart_cmd_preflight_values_parsing_failure_stops_before_helm(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(
        "ingress: [invalid\nunrelatedSecret: sentinel-super-secret\n",
        encoding="utf-8",
    )
    args = _preflight_args()
    args.values = str(values)
    args.host = ""
    helm_called = False

    def unexpected_helm_show(chart: str, version: str) -> subprocess.CompletedProcess[str]:
        nonlocal helm_called
        helm_called = True
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(app_chart, "helm_show", unexpected_helm_show)

    assert app_chart.cmd_preflight(args) == 1
    error = capsys.readouterr().err
    assert "values parsing failed" in error
    assert "host=<unresolved>" in error
    assert "sentinel-super-secret" not in error
    assert "Traceback" not in error
    assert not helm_called


def _assert_preflight_failure_context(error: str, operation: str) -> None:
    for expected in (
        operation,
        "app=tokenplace",
        "env=staging",
        "release=tokenplace",
        "namespace=tokenplace",
        "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
        "version=0.1.3",
        "tag=main-deadbee",
        "host=staging.example.test",
    ):
        assert expected in error
    assert "sentinel-super-secret" not in error


def _preflight_args() -> argparse.Namespace:
    return argparse.Namespace(
        app="tokenplace",
        env="staging",
        tag="main-deadbee",
        chart="oci://ghcr.io/futuroptimist/charts/tokenplace",
        version_file="docs/apps/tokenplace.version",
        version="0.1.3",
        release="tokenplace",
        namespace="tokenplace",
        values="",
        host="staging.example.test",
    )


def test_app_chart_cmd_preflight_reports_helm_launch_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing_helm(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("helm executable missing")

    monkeypatch.setattr(subprocess, "run", missing_helm)

    assert app_chart.cmd_preflight(_preflight_args()) == 127
    error = capsys.readouterr().err
    _assert_preflight_failure_context(error, "helm show")
    assert "helm executable missing" in error
    assert "Traceback" not in error


def test_app_chart_cmd_preflight_reports_ruby_psych_launch_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        app_chart,
        "helm_show",
        lambda chart, version: subprocess.CompletedProcess([], 0, "apiVersion: v2\n", ""),
    )

    def missing_ruby(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("ruby executable missing")

    monkeypatch.setattr(subprocess, "run", missing_ruby)

    assert app_chart.cmd_preflight(_preflight_args()) == 1
    error = capsys.readouterr().err
    _assert_preflight_failure_context(error, "chart metadata parsing")
    assert "YAML parser launch failed" in error
    assert "ruby executable missing" in error
    assert "Traceback" not in error


def test_app_chart_cmd_preflight_reports_missing_app_container_envs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app_chart, "validate_rendered_manifest", lambda manifest, inputs: [])
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
            "metadata:\n"
            "  name: tokenplace\n"
            "  labels:\n"
            "    app.kubernetes.io/instance: tokenplace\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "        - name: relay\n"
            "          image: ghcr.io/example/tokenplace:main-deadbee\n"
            "          env:\n"
            "            - name: TOKENPLACE_IMAGE_TAG\n"
            "            - name: TOKENPLACE_RELEASE_VERSION\n"
            "        - name: tokenplace\n"
            "          image: ghcr.io/example/tokenplace:main-deadbee\n"
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
metadata:
  labels:
    app.kubernetes.io/instance: tokenplace
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
metadata:
  labels:
    app.kubernetes.io/instance: tokenplace
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
metadata:
  labels:
    app.kubernetes.io/instance: tokenplace
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


def test_deployment_app_container_env_sets_rejects_name_only_association() -> None:
    manifest = """apiVersion: apps/v1
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
"""

    assert app_chart.deployment_app_container_env_sets(manifest, "tokenplace", "tokenplace") == []


def test_app_chart_cmd_preflight_rejects_metadata_from_unrelated_deployment(
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
    manifest = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: tokenplace
  labels:
    app.kubernetes.io/instance: tokenplace
spec:
  template:
    spec:
      containers:
        - name: relay
          image: ghcr.io/example/tokenplace:main-deadbee
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: unrelated
  labels:
    app.kubernetes.io/instance: unrelated
spec:
  template:
    spec:
      containers:
        - name: relay
          image: ghcr.io/example/tokenplace:main-deadbee
          env:
            - name: TOKENPLACE_IMAGE_TAG
            - name: TOKENPLACE_RELEASE_VERSION
            - name: TOKENPLACE_CHART_VERSION
            - name: TOKENPLACE_DEPLOY_ENV
"""
    monkeypatch.setattr(
        app_chart,
        "run",
        lambda cmd: subprocess.CompletedProcess(cmd, 0, manifest, ""),
    )

    assert app_chart.cmd_preflight(args) == 1
    assert "missing required metadata env vars" in capsys.readouterr().err


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
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  annotations:\n"
            "    meta.helm.sh/release-name: tokenplace\nspec:\n  template:\n    spec:\n"
            "      containers:\n        - name: relay\n"
            "          image: ghcr.io/example/tokenplace:main-deadbee\n          env:\n"
            "            - name: TOKENPLACE_IMAGE_TAG\n"
            "            - name: TOKENPLACE_RELEASE_VERSION\n"
            "            - name: TOKENPLACE_CHART_VERSION\n"
            "            - name: TOKENPLACE_DEPLOY_ENV\n",
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
            "jobbot3000",
            "oci://ghcr.io/futuroptimist/charts/jobbot3000",
            "jobbot3000",
            [
                "docs/examples/jobbot3000.values.dev.yaml",
                "docs/examples/jobbot3000.values.staging.yaml",
            ],
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
    ("app", "staging_host"),
    [
        ("tokenplace", "staging.token.place"),
        ("danielsmith", "staging.danielsmith.io"),
        ("jobbot3000", "staging.jobbot3000.tech"),
    ],
)
def test_standard_app_redeploy_has_authoritative_values_and_render_mutation_parity(
    app: str, staging_host: str, generic_app_stub_env: dict[str, str]
) -> None:
    result = _run_just(
        ["app-redeploy", f"app={app}", "env=staging", "tag=main-deadbee"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    lines = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8").splitlines()
    rendered = next(line.split() for line in lines if line.startswith("template "))
    mutated = next(line.split() for line in lines if line.startswith("upgrade "))
    assert "--reuse-values" not in mutated
    assert "--reset-values" not in mutated
    assert rendered[1:4] == mutated[1:4]

    def release_inputs(command: list[str]) -> list[str]:
        inputs: list[str] = []
        for flag in ("--namespace", "--version", "-f", "--set"):
            for index, argument in enumerate(command[:-1]):
                if argument == flag:
                    inputs.extend(command[index : index + 2])
        return inputs

    assert release_inputs(rendered) == release_inputs(mutated)
    host_override = f"ingress.host={staging_host}"
    assert host_override in rendered
    assert host_override in mutated
    base = f"docs/examples/{app}.values.dev.yaml"
    overlay = f"docs/examples/{app}.values.staging.yaml"
    assert mutated.index(base) < mutated.index(overlay)
    assert "image.tag=main-deadbee" in mutated
    assert "image.pullPolicy=Always" in mutated


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("values_contents", "diagnostic"),
    [
        ("ingress: [invalid\n", "values parsing failed while resolving ingress host"),
        ("ingress:\n  enabled: true\n", "no nonempty ingress.host was resolved"),
    ],
)
def test_app_redeploy_host_resolution_failure_stops_before_release_activity(
    tmp_path: Path,
    values_contents: str,
    diagnostic: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    values = tmp_path / "values.yaml"
    values.write_text(values_contents, encoding="utf-8")
    config = tmp_path / "tokenplace.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=tokenplace",
                "SUGARKUBE_RELEASE=tokenplace",
                "SUGARKUBE_NAMESPACE=tokenplace",
                "SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/tokenplace",
                "SUGARKUBE_VERSION=0.1.3",
                f"SUGARKUBE_VALUES_STAGING={values}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.json"
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CONFIG_DIR"] = str(tmp_path)

    result = _run_just(
        [
            "app-redeploy",
            "app=tokenplace",
            "env=staging",
            "tag=main-deadbee",
            f"evidence={evidence}",
        ],
        env,
    )

    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert "Traceback" not in result.stderr
    helm_log = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log.exists() or helm_log.read_text(encoding="utf-8") == ""
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8")
    assert "helm template" not in commands
    assert "helm upgrade" not in commands
    assert "rollout" not in commands
    assert not evidence.exists()
    assert not Path(f"{evidence}.reservation").exists()


@pytest.mark.usefixtures("ensure_just_available")
def test_helm_oci_install_and_upgrade_keep_authoritative_inputs_identical(
    generic_app_stub_env: dict[str, str],
) -> None:
    common_args = [
        "release=tokenplace",
        "namespace=tokenplace",
        "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
        "values=docs/examples/tokenplace.values.dev.yaml,docs/examples/tokenplace.values.staging.yaml",
        "host=staging.token.place",
        "version=0.1.3",
        "tag=main-deadbee",
        "env=staging",
        "app=tokenplace",
    ]
    mutations: dict[str, list[str]] = {}
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    for recipe in ("helm-oci-install", "helm-oci-upgrade"):
        helm_log_path.unlink(missing_ok=True)
        result = _run_just([recipe, *common_args], generic_app_stub_env)
        assert result.returncode == 0, result.stderr + result.stdout
        lines = helm_log_path.read_text(encoding="utf-8").splitlines()
        mutations[recipe] = next(line.split() for line in lines if line.startswith("upgrade "))

    install = mutations["helm-oci-install"]
    upgrade = mutations["helm-oci-upgrade"]
    assert "--install" in install
    assert "--create-namespace" in install
    assert "--install" not in upgrade
    assert "--create-namespace" not in upgrade
    prohibited = {"--reuse-values", "--reset-values", "--reset-then-reuse-values"}
    assert prohibited.isdisjoint(install)
    assert prohibited.isdisjoint(upgrade)

    def release_inputs(command: list[str]) -> list[str]:
        inputs = command[1:3]
        for flag in ("--namespace", "--version", "-f", "--set"):
            for index, argument in enumerate(command[:-1]):
                if argument == flag:
                    inputs.extend(command[index : index + 2])
        return inputs

    assert release_inputs(install) == release_inputs(upgrade)
    for expected in (
        "docs/examples/tokenplace.values.dev.yaml",
        "docs/examples/tokenplace.values.staging.yaml",
        "ingress.host=staging.token.place",
        "image.tag=main-deadbee",
        "image.pullPolicy=Always",
    ):
        assert expected in install
        assert expected in upgrade
    assert install.index("docs/examples/tokenplace.values.dev.yaml") < install.index(
        "docs/examples/tokenplace.values.staging.yaml"
    )


def test_standard_helm_helper_source_cannot_reintroduce_historical_values() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    helper = justfile.split("_helm-oci-deploy ", 1)[1].split("\nhelm-oci-install ", 1)[0]

    assert "reuse_values" not in helper
    assert "--reuse-values" not in helper
    assert "reset-then-reuse-values" not in helper


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("app", "release", "namespace", "chart"),
    [
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
        (
            "jobbot3000",
            "jobbot3000",
            "jobbot3000",
            "oci://ghcr.io/futuroptimist/charts/jobbot3000",
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
    generic_app_stub_env["SUGARKUBE_STUB_NODE_ENV"] = "prod"
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
@pytest.mark.parametrize("mutable_tag", ["latest", "main-latest"])
def test_app_deploy_rejects_mutable_tag_before_helm(
    mutable_tag: str, generic_app_stub_env: dict[str, str]
) -> None:
    result = _run_just(
        ["app-deploy", "app=jobbot3000", "env=staging", f"tag={mutable_tag}"],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "mutable tag" in result.stderr
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "args"),
    [
        ("app-deploy", ["app=jobbot3000", "env=staging", "tag=v3.0.1"]),
        ("app-redeploy", ["app=jobbot3000", "env=int", "tag=v3.0.1"]),
        ("app-promote-prod", ["app=jobbot3000", "tag=v3.0.1"]),
        ("dspace-oci-deploy", ["env=staging", "tag=v3.0.1"]),
        ("dspace-oci-promote-prod", ["tag=v3.0.1"]),
        ("tokenplace-oci-deploy", ["env=staging", "tag=v3.0.1"]),
        ("tokenplace-oci-redeploy", ["env=staging", "tag=v3.0.1"]),
        ("tokenplace-oci-promote-prod", ["tag=v3.0.1"]),
        ("danielsmith-oci-promote-prod", ["tag=v3.0.1"]),
    ],
)
def test_deployment_entry_points_reject_semantic_tags_before_helm(
    recipe: str, args: list[str], generic_app_stub_env: dict[str, str]
) -> None:
    result = _run_just([recipe, *args], generic_app_stub_env)

    assert result.returncode != 0
    assert "branch-SHA" in result.stderr
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""
    command_log = helm_log_path.with_name("commands.log")
    assert not command_log.exists() or command_log.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_app_promote_prod_rejects_semantic_fallback_before_cluster_access(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    prod_tag = tmp_path / "jobbot3000.prod.tag"
    prod_tag.write_text("v3.0.1\n", encoding="utf-8")
    config = tmp_path / "jobbot3000.env"
    config.write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=jobbot3000",
                "SUGARKUBE_RELEASE=jobbot3000",
                "SUGARKUBE_NAMESPACE=jobbot3000",
                "SUGARKUBE_CHART=oci://ghcr.io/futuroptimist/charts/jobbot3000",
                "SUGARKUBE_VERSION=1.0.0",
                f"SUGARKUBE_PROD_TAG_FILE={prod_tag}",
                "SUGARKUBE_VALUES_DEV=docs/examples/jobbot3000.values.dev.yaml",
                "SUGARKUBE_VALUES_STAGING=docs/examples/jobbot3000.values.staging.yaml",
                "SUGARKUBE_VALUES_PROD=docs/examples/jobbot3000.values.prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run_just(
        ["app-promote-prod", "app=jobbot3000", f"config={config}"],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "branch-SHA" in result.stderr
    for name in ("helm.log", "kubectl.log", "commands.log"):
        log = tmp_path / name
        assert not log.exists() or log.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_oci_deploy_wrapper_propagates_inline_chart_pin(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    config_dir = tmp_path / "app-config"
    config_dir.mkdir()
    (config_dir / "dspace.env").write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=dspace",
                "SUGARKUBE_RELEASE=dspace",
                "SUGARKUBE_NAMESPACE=dspace",
                "SUGARKUBE_CHART=oci://ghcr.io/democratizedspace/charts/dspace",
                "SUGARKUBE_VERSION=3.1.0-rc.1+build.5",
                "SUGARKUBE_VALUES_DEV=docs/examples/dspace.values.dev.yaml",
                "SUGARKUBE_VALUES_STAGING="
                "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml",
                "SUGARKUBE_VALUES_PROD="
                "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CONFIG_DIR"] = str(config_dir)

    result = _run_just(["dspace-oci-deploy", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode != 0
    assert "manifest=<approved-candidate.json> is required" in result.stderr
    assert not Path(env["HELM_LOG"]).exists()


def _write_dspace_candidate(
    path: Path, environment: str, *, image_digest: str | None = None
) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "app": "dspace",
                "applicationVersion": "3.2.0",
                "sourceRevision": "abcdef0123456789abcdef0123456789abcdef01",
                "imageTag": "main-abcdef0",
                "imageDigest": image_digest or "sha256:" + "1" * 64,
                "chartVersion": "3.1.0" if environment == "staging" else "3.0.1",
                "chartDigest": "sha256:" + "2" * 64,
                "semanticTag": "v3.2.0",
                "recordType": "candidate",
                "environment": environment,
                "expectedDefaultChatProvider": "token-place",
                "approvedAt": "2026-07-26T12:00:00Z",
                "approvedBy": "synthetic-test-approver",
            }
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_guarded_deploy_orders_preflight_mutation_and_finalization(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    manifest = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    _write_dspace_candidate(manifest, "staging")

    result = _run_just(
        [
            "app-deploy",
            "dspace",
            "staging",
            "main-abcdef0",
            "",
            str(manifest),
            str(evidence),
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    final = json.loads(evidence.read_text(encoding="utf-8"))
    assert final["recordType"] == "final"
    assert final["helmRevision"] == 7
    assert "reservation" not in json.dumps(final).lower()
    assert not Path(str(evidence.resolve()) + ".reservation").exists()
    coordinate = "oci://ghcr.io/democratizedspace/charts/dspace@sha256:" + "2" * 64
    installed = next(
        item for item in final["verificationResults"] if item["check"] == "installedChart"
    )
    assert coordinate in installed["details"]
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    render_line = next(line for line in helm_log.splitlines() if line.startswith("template "))
    mutation_line = next(line for line in helm_log.splitlines() if line.startswith("upgrade "))
    for expected in (
        coordinate,
        "--namespace dspace",
        "-f docs/examples/dspace.values.dev.yaml",
        "-f docs/examples/dspace.values.staging.yaml",
        "--set ingress.host=staging.democratized.space",
        "--set image.tag=main-abcdef0",
        "--set image.pullPolicy=Always",
    ):
        assert expected in render_line
        assert expected in mutation_line
    assert coordinate in mutation_line
    assert "--reuse-values" not in mutation_line
    assert "--version" not in mutation_line
    assert "--version" not in render_line
    assert "--description sugarkube-release-manifest:" in mutation_line
    commands = (tmp_path / "commands.log").read_text(encoding="utf-8").splitlines()
    preflight = next(i for i, line in enumerate(commands) if line.startswith("oras "))
    mutation = next(i for i, line in enumerate(commands) if line.startswith("helm upgrade "))
    collection = next(i for i, line in enumerate(commands) if " status dspace" in line)
    pods = next(i for i, line in enumerate(commands) if " -n dspace get pods" in line)
    assert preflight < mutation < collection < pods


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_render_failure_stops_before_evidence_reservation_or_mutation(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    manifest = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    reservation = Path(str(evidence.resolve()) + ".reservation")
    _write_dspace_candidate(manifest, "staging")
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_HELM_TEMPLATE_FAIL"] = "1"

    result = _run_just(
        [
            "app-deploy",
            "dspace",
            "staging",
            "main-abcdef0",
            "",
            str(manifest),
            str(evidence),
        ],
        env,
    )

    assert result.returncode != 0
    assert "synthetic helm template failure" in result.stderr
    assert not evidence.exists()
    assert not reservation.exists()
    helm_log = Path(env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "template dspace " in helm_log
    assert "upgrade " not in helm_log
    kubectl_log = tmp_path / "kubectl.log"
    kubectl_commands = kubectl_log.read_text(encoding="utf-8") if kubectl_log.exists() else ""
    assert " apply " not in kubectl_commands
    assert " patch " not in kubectl_commands
    assert " set image " not in kubectl_commands
    assert "rollout" not in kubectl_commands


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_guarded_redeploy_installs_approved_chart_digest(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    candidate_path = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    _write_dspace_candidate(candidate_path, "staging")

    result = _run_just(
        [
            "app-redeploy",
            "dspace",
            "staging",
            "main-abcdef0",
            "",
            str(candidate_path),
            str(evidence),
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    coordinate = "oci://ghcr.io/democratizedspace/charts/dspace@sha256:" + "2" * 64
    mutation_line = next(
        line
        for line in Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8").splitlines()
        if line.startswith("upgrade ")
    )
    assert coordinate in mutation_line
    assert "--version" not in mutation_line
    assert "--description sugarkube-release-manifest:" in mutation_line


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("env_override", "manifest_digest", "expected_check"),
    [
        ({"SUGARKUBE_STUB_RESOLVED_IMAGE": "9" * 64}, None, "imageDigest"),
        ({"SUGARKUBE_STUB_RESOLVED_CHART": "9" * 64}, None, "chartDigest"),
    ],
)
def test_dspace_digest_mismatch_stops_before_helm(
    tmp_path: Path,
    generic_app_stub_env: dict[str, str],
    env_override: dict[str, str],
    manifest_digest: str | None,
    expected_check: str,
) -> None:
    manifest = tmp_path / "candidate.json"
    _write_dspace_candidate(manifest, "staging", image_digest=manifest_digest)
    env = generic_app_stub_env.copy()
    env.update(env_override)

    result = _run_just(
        ["app-deploy", "dspace", "staging", "main-abcdef0", "", str(manifest)],
        env,
    )

    assert result.returncode != 0
    assert expected_check in result.stderr
    helm_log = Path(env["HELM_LOG"])
    assert not helm_log.exists() or "upgrade " not in helm_log.read_text(encoding="utf-8")


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_reservation_collision_stops_before_helm(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    candidate_path = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    _write_dspace_candidate(candidate_path, "staging")
    candidate_record = json.loads(candidate_path.read_text(encoding="utf-8"))
    release_manifest.reserve(evidence, candidate_record, "staging", "dspace", "dspace")

    result = _run_just(
        [
            "app-deploy",
            "dspace",
            "staging",
            "main-abcdef0",
            "",
            str(candidate_path),
            str(evidence),
        ],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "already reserved" in result.stderr
    helm_log = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log.exists() or "upgrade " not in helm_log.read_text(encoding="utf-8")


@pytest.mark.usefixtures("ensure_just_available")
def test_prod_subdomain_wrapper_preserves_canary_overlay_through_guarded_path(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    manifest = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    _write_dspace_candidate(manifest, "prod")
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "prod"

    result = _run_just(
        [
            "dspace-oci-deploy-prod-subdomain",
            "main-abcdef0",
            str(manifest),
            str(evidence),
        ],
        env,
    )

    assert result.returncode != 0
    assert "staging_evidence=<finalized-staging.json> is required" in result.stderr
    assert not evidence.exists()


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "app"),
    [
        ("danielsmith-oci-deploy", "danielsmith"),
        ("tokenplace-oci-deploy", "tokenplace"),
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
    ("recipe", "arguments"),
    [
        ("tokenplace-oci-deploy", ["env=staging", "tag=main-deadbee"]),
        ("tokenplace-oci-redeploy", ["env=staging", "tag=main-deadbee"]),
        ("tokenplace-oci-promote-prod", ["tag=main-deadbee"]),
    ],
)
def test_tokenplace_oci_paths_render_once_before_single_mutation(
    recipe: str, arguments: list[str], generic_app_stub_env: dict[str, str]
) -> None:
    if recipe == "tokenplace-oci-promote-prod":
        generic_app_stub_env["SUGARKUBE_STUB_NODE_ENV"] = "prod"

    result = _run_just([recipe, *arguments], generic_app_stub_env)

    assert result.returncode == 0, result.stderr + result.stdout
    helm_lines = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8").splitlines()
    renders = [index for index, line in enumerate(helm_lines) if line.startswith("template ")]
    mutations = [index for index, line in enumerate(helm_lines) if line.startswith("upgrade ")]
    assert len(renders) == 1
    assert len(mutations) == 1
    assert renders[0] < mutations[0]


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("recipe", "image_heading", "check_heading"),
    [
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
    generic_app_stub_env["SUGARKUBE_STUB_NODE_ENV"] = "prod"
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
        ("jobbot3000", "/,/healthz,/livez"),
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


def test_jobbot3000_example_config_resolves_all_env_values() -> None:
    expected_values = {
        "dev": "docs/examples/jobbot3000.values.dev.yaml",
        "staging": (
            "docs/examples/jobbot3000.values.dev.yaml,"
            "docs/examples/jobbot3000.values.staging.yaml"
        ),
        "prod": (
            "docs/examples/jobbot3000.values.dev.yaml," "docs/examples/jobbot3000.values.prod.yaml"
        ),
    }

    for env, values in expected_values.items():
        result = subprocess.run(
            [
                "python3",
                "scripts/app_config.py",
                "json",
                "--app",
                "jobbot3000",
                "--env",
                env,
                "--config",
                "",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert '"SUGARKUBE_CHART": "oci://ghcr.io/futuroptimist/charts/jobbot3000"' in result.stdout
        assert f'"SUGARKUBE_VALUES": "{values}"' in result.stdout


def test_jobbot3000_staging_values_resolve_real_staging_host() -> None:
    staging_values = (REPO_ROOT / "docs/examples/jobbot3000.values.staging.yaml").read_text(
        encoding="utf-8"
    )
    app_env = (REPO_ROOT / "docs/examples/apps/jobbot3000.env").read_text(encoding="utf-8")

    assert (
        "SUGARKUBE_VALUES_STAGING="
        "docs/examples/jobbot3000.values.dev.yaml,docs/examples/jobbot3000.values.staging.yaml"
    ) in app_env
    assert "host: staging.jobbot3000.tech" in staging_values
    assert "- staging.jobbot3000.tech" in staging_values
    assert "staging.jobbot3000.example.test" not in staging_values


def test_jobbot3000_runbook_first_staging_deploy_is_concrete_and_blocks_prod() -> None:
    runbook = (REPO_ROOT / "docs/apps/jobbot3000.md").read_text(encoding="utf-8")

    assert "staging.jobbot3000.tech" in runbook
    assert "http://traefik.kube-system.svc.cluster.local:80" in runbook
    assert "just app-config app=jobbot3000 env=staging" in runbook
    assert "just app-chart-status app=jobbot3000" in runbook
    assert "just app-deploy app=jobbot3000 env=staging tag=main-b3e6df1a4f68" in runbook
    assert "just app-status app=jobbot3000 env=staging" in runbook
    assert "just app-verify app=jobbot3000 env=staging" in runbook
    assert "Production promotion is explicitly blocked until staging is verified" in runbook


def test_jobbot3000_runbook_troubleshooting_pins_staging_context() -> None:
    runbook = (REPO_ROOT / "docs/apps/jobbot3000.md").read_text(encoding="utf-8")

    assert "kubectl --context sugar-staging get ingress" in runbook
    assert "kubectl --context sugar-staging describe ingress" in runbook
    assert "kubectl --context sugar-staging get svc,endpoints" in runbook
    assert "kubectl --context sugar-staging logs -n kube-system" in runbook
    assert "kubectl --context sugar-staging get certificate,challenge,order" in runbook
    assert "kubectl --context sugar-staging describe certificate" in runbook
    assert "kubectl --context sugar-staging logs -n cert-manager" in runbook
    assert "helm --kube-context sugar-staging -n jobbot3000 get values jobbot3000" in runbook
    assert "helm --kube-context sugar-staging -n jobbot3000 status jobbot3000" in runbook
    assert "kubectl --context sugar-staging get deploy" in runbook
    assert "kubectl get ingress -n jobbot3000" not in runbook
    assert "kubectl describe ingress -n jobbot3000 jobbot3000" not in runbook
    assert "kubectl logs -n cert-manager deploy/cert-manager" not in runbook
    assert "helm get values -n jobbot3000 jobbot3000" not in runbook
    assert "helm get values -n jobbot3000" not in runbook


def test_jobbot3000_values_are_static_only_and_use_immutable_image_example() -> None:
    values_paths = [
        REPO_ROOT / "docs/examples/jobbot3000.values.dev.yaml",
        REPO_ROOT / "docs/examples/jobbot3000.values.staging.yaml",
        REPO_ROOT / "docs/examples/jobbot3000.values.prod.yaml",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in values_paths)
    dev_values = values_paths[0].read_text(encoding="utf-8")

    assert "repository: ghcr.io/futuroptimist/jobbot3000" in dev_values
    assert "tag: main-REPLACE_SHORTSHA" in dev_values
    assert "tag: latest" not in dev_values
    assert "tag: main-latest" not in dev_values
    assert "containerPort: 8080" in dev_values
    assert "port: 80" in dev_values
    assert "persistentVolumeClaim" not in combined
    assert "persistence:" not in combined
    assert "kind: Secret" not in combined
    assert "secretKeyRef" not in combined
    assert "kind: ConfigMap" not in combined
    assert "configMapKeyRef" not in combined
    assert "applications:" not in combined
    assert "outreach" not in combined
    assert "interviews" not in combined
    assert "offers" not in combined


@pytest.mark.usefixtures("ensure_just_available")
def test_app_verify_print_only_jobbot3000_paths(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        ["app-verify", "app=jobbot3000", "env=staging", "print_only=1"],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.splitlines() == [
        "curl -fsS https://example.test/",
        "curl -fsS https://example.test/healthz",
        "curl -fsS https://example.test/livez",
    ]
    assert not Path(generic_app_stub_env["CURL_LOG"]).exists()


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


def test_app_cors_verify_rejects_wildcard_methods_but_accepts_wildcard_headers(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_CORS_METHODS"] = "*"
    env["SUGARKUBE_STUB_CORS_HEADERS"] = "*"

    result = _run_just(["app-cors-verify", "app=tokenplace", "env=staging"], env)

    assert result.returncode != 0
    assert "Access-Control-Allow-Methods must contain POST" in result.stderr


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
    env["SUGARKUBE_STUB_CORS_HEADERS"] = "x-custom-one,x-custom-two,content-type"

    result = _run_just(
        ["app-cors-verify", "app=tokenplace", "env=staging", f"config={config}"], env
    )

    assert result.returncode == 0, result.stderr + result.stdout
    curl_log = Path(generic_app_stub_env["CURL_LOG"]).read_text(encoding="utf-8")
    assert "Access-Control-Request-Headers: x-custom-one,x-custom-two,content-type" in curl_log
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


def test_app_cors_verify_main_rejects_wildcard_methods(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[
            (
                0,
                "204",
                _cors_headers({"access-control-allow-methods": ["*"]}),
                b"",
                "",
            ),
        ],
    )

    assert rc == 1
    assert "Access-Control-Allow-Methods must contain POST" in err


def test_app_cors_verify_main_requires_content_type_with_configured_headers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        env={"SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS": "x-custom-token"},
        responses=[
            (
                0,
                "204",
                _cors_headers({"access-control-allow-headers": ["x-custom-token"]}),
                b"",
                "",
            ),
        ],
    )

    assert rc == 1
    assert "Access-Control-Allow-Headers must contain content-type" in err
    assert "Access-Control-Request-Headers: x-custom-token,content-type" in calls[0]


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


def test_app_cors_verify_main_reports_preflight_status_and_header_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[(0, "503", _cors_headers(), b"", "")],
    )

    assert rc == 1
    assert "status=503" in err
    assert "preflight HTTP status must be successful" in err

    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[
            (0, "204", {"access-control-allow-origin": ["https://cors-smoke.invalid"]}, b"", "")
        ],
    )

    assert rc == 1
    assert "Access-Control-Allow-Origin echoed the test Origin" in err


def test_app_cors_verify_main_reports_missing_host_and_preflight_curl_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        host="",
        errors=["ingress lookup failed"],
    )

    assert rc == 1
    assert calls == []
    assert "ingress lookup failed" in err
    assert "status=000" in err
    assert "could not derive public host" in err

    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[(28, "000", {}, b"", "curl: timed out")],
    )

    assert rc == 1
    assert "status=000" in err
    assert "curl: timed out" in err


def test_app_cors_verify_main_reports_actual_cors_and_body_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[
            (0, "204", _cors_headers(), b"", ""),
            (
                0,
                "400",
                _cors_headers({"access-control-allow-origin": ["https://evil.test"]}),
                b'{"error":{}}',
                "",
            ),
        ],
    )

    assert rc == 1
    assert "Access-Control-Allow-Origin must be literal *" in err

    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[
            (0, "204", _cors_headers(), b"", ""),
            (0, "400", _cors_headers(), b"not json", ""),
        ],
    )

    assert rc == 1
    assert "token.place API error response must be JSON" in err

    rc, _out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        responses=[
            (0, "204", _cors_headers(), b"", ""),
            (0, "400", _cors_headers(), b'{"message":"missing top-level error"}', ""),
        ],
    )

    assert rc == 1
    assert "top-level error object" in err


def test_app_cors_verify_main_allows_non_tokenplace_non_json_actual_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, err, _calls = _run_app_cors_main(
        monkeypatch,
        capsys,
        env={"SUGARKUBE_APP": "otherapp"},
        responses=[
            (0, "204", _cors_headers(), b"", ""),
            (0, "400", _cors_headers(), b"plain text error", ""),
        ],
    )

    assert rc == 0, err + out


def test_app_cors_verify_main_rejects_bad_expected_status_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run_app_cors_main(
            monkeypatch,
            capsys,
            env={"SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES": "400,nope"},
        )

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert (
        "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES must be comma-separated integers" in captured.err
    )

    with pytest.raises(SystemExit) as excinfo:
        _run_app_cors_main(
            monkeypatch,
            capsys,
            env={"SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES": " , "},
        )

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert (
        "SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES must include at least one integer" in captured.err
    )


def test_app_cors_verify_header_parsing_helpers() -> None:
    from scripts import app_cors_verify

    headers = app_cors_verify.headers_from_bytes(
        b"HTTP/1.1 100 Continue\r\nIgnored: yes\r\n\r\n"
        b"HTTP/2 204\r\nAccess-Control-Allow-Origin: *\r\n"
        b"Access-Control-Allow-Headers: content-type, x-custom\r\n"
        b"Access-Control-Allow-Credentials: true\r\n\r\n"
    )

    assert headers["access-control-allow-origin"] == ["*"]
    assert app_cors_verify.single_header(headers, "Access-Control-Allow-Origin") == ("*", "")
    assert app_cors_verify.contains_header_value(
        headers, "Access-Control-Allow-Headers", "X-Custom"
    )
    assert app_cors_verify.credentials_enabled(headers)
    assert app_cors_verify.assert_wildcard(headers, "https://cors-smoke.invalid") == (
        "Access-Control-Allow-Credentials must be absent or not true"
    )
    assert app_cors_verify.curl_quote("two words") == "'two words'"
    assert app_cors_verify.csv(" a, ,b ") == ["a", "b"]


def test_app_cors_verify_run_curl_collects_status_headers_body_and_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import app_cors_verify

    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_CURL_CONNECT_TIMEOUT", "3")
    monkeypatch.setenv("SUGARKUBE_APP_VERIFY_CURL_MAX_TIME", "7")
    seen: dict[str, object] = {}

    class Completed:
        returncode = 18
        stdout = "400"
        stderr = "curl: transfer closed"

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> Completed:
        seen["cmd"] = cmd
        seen["capture_output"] = capture_output
        seen["text"] = text
        seen["check"] = check
        header_path = Path(cmd[cmd.index("-D") + 1])
        body_path = Path(cmd[cmd.index("-o") + 1])
        header_path.write_bytes(
            b"HTTP/1.1 100 Continue\r\nIgnored: yes\r\n\r\n"
            b"HTTP/2 400\r\nAccess-Control-Allow-Origin: *\r\n"
            b"Access-Control-Allow-Headers: content-type\r\n\r\n"
        )
        body_path.write_bytes(b'{"error":{}}')
        return Completed()

    monkeypatch.setattr(app_cors_verify.subprocess, "run", fake_run)

    rc, status, headers, body, stderr = app_cors_verify.run_curl(
        ["-X", "POST", "https://example.test"]
    )

    assert rc == 18
    assert status == "400"
    assert headers["access-control-allow-origin"] == ["*"]
    assert headers["access-control-allow-headers"] == ["content-type"]
    assert body == b'{"error":{}}'
    assert stderr == "curl: transfer closed"
    cmd = seen["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:6] == ["curl", "-sS", "--connect-timeout", "3", "--max-time", "7"]
    assert cmd[-3:] == ["-X", "POST", "https://example.test"]
    assert seen == {**seen, "capture_output": True, "text": True, "check": False}
    assert not Path(cmd[cmd.index("-D") + 1]).exists()
    assert not Path(cmd[cmd.index("-o") + 1]).exists()


def test_app_cors_verify_run_curl_defaults_blank_status_and_missing_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import app_cors_verify

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(
        cmd: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> Completed:
        Path(cmd[cmd.index("-D") + 1]).unlink()
        Path(cmd[cmd.index("-o") + 1]).unlink()
        return Completed()

    monkeypatch.setattr(app_cors_verify.subprocess, "run", fake_run)

    rc, status, headers, body, stderr = app_cors_verify.run_curl(["https://example.test"])

    assert rc == 0
    assert status == "000"
    assert headers == {}
    assert body == b""
    assert stderr == ""


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("recipe", ["helm-oci-install", "helm-oci-upgrade"])
def test_direct_helm_oci_helpers_require_requested_env_before_helm(
    recipe: str, generic_app_stub_env: dict[str, str]
) -> None:
    env = generic_app_stub_env.copy()
    env.pop("SUGARKUBE_ENV", None)
    result = _run_just(
        [
            recipe,
            "release=tokenplace",
            "namespace=tokenplace",
            "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
            "version_file=docs/apps/tokenplace.version",
        ],
        env,
    )

    assert result.returncode != 0
    assert "env is required for helm-oci-install/helm-oci-upgrade" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_direct_helm_oci_helper_mismatch_fails_before_any_helm(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "staging"
    result = _run_just(
        [
            "helm-oci-install",
            "release=tokenplace",
            "namespace=tokenplace",
            "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
            "version_file=docs/apps/tokenplace.version",
            "env=prod",
        ],
        env,
    )

    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_direct_helm_oci_helper_accepts_inline_semver_with_prerelease_and_build(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        [
            "helm-oci-install",
            "release=tokenplace",
            "namespace=tokenplace",
            "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
            "version=1.2.3-rc.1+build.5",
            "tag=main-deadbee",
            "env=staging",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert (
        "show chart oci://ghcr.io/futuroptimist/charts/tokenplace " "--version 1.2.3-rc.1+build.5"
    ) in helm_log
    assert "upgrade tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("recipe", ["helm-oci-install", "helm-oci-upgrade"])
@pytest.mark.parametrize("image_arg", ["tag=v3.0.1", "default_tag=v3.0.1"])
def test_direct_helm_oci_helpers_reject_semantic_image_tag_before_helm(
    recipe: str, image_arg: str, generic_app_stub_env: dict[str, str]
) -> None:
    result = _run_just(
        [
            recipe,
            "release=tokenplace",
            "namespace=tokenplace",
            "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
            "version=1.2.3",
            image_arg,
            "env=staging",
        ],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert "branch-SHA" in result.stderr
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize(
    ("filename", "contents", "message"),
    [
        ("missing.version", None, "does not exist"),
        ("empty.version", "# only comments\n", "is empty"),
        ("bad.version", "not-a-version\n", "malformed version"),
    ],
)
def test_direct_helm_oci_helper_rejects_selected_pin_file_before_helm(
    tmp_path: Path,
    filename: str,
    contents: str | None,
    message: str,
    generic_app_stub_env: dict[str, str],
) -> None:
    pin = tmp_path / filename
    if contents is not None:
        pin.write_text(contents, encoding="utf-8")

    result = _run_just(
        [
            "helm-oci-install",
            "release=tokenplace",
            "namespace=tokenplace",
            "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
            f"version_file={pin}",
            "env=staging",
        ],
        generic_app_stub_env,
    )

    assert result.returncode != 0
    assert message in result.stderr
    helm_log_path = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_oci_deploy_wrapper_propagates_env_specific_chart_pin(
    tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    config_dir = tmp_path / "app-config"
    config_dir.mkdir()
    shared = tmp_path / "shared.version"
    staging = tmp_path / "staging.version"
    shared.write_text("1.0.0\n", encoding="utf-8")
    staging.write_text("3.1.0-rc.1+build.5\n", encoding="utf-8")
    (config_dir / "dspace.env").write_text(
        "\n".join(
            [
                "SUGARKUBE_APP=dspace",
                "SUGARKUBE_RELEASE=dspace",
                "SUGARKUBE_NAMESPACE=dspace",
                "SUGARKUBE_CHART=oci://ghcr.io/democratizedspace/charts/dspace",
                "SUGARKUBE_VERSION=",
                f"SUGARKUBE_VERSION_FILE={shared}",
                f"SUGARKUBE_VERSION_FILE_STAGING={staging}",
                "SUGARKUBE_VALUES_DEV=docs/examples/dspace.values.dev.yaml",
                "SUGARKUBE_VALUES_STAGING="
                "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml",
                "SUGARKUBE_VALUES_PROD="
                "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_APP_CONFIG_DIR"] = str(config_dir)

    result = _run_just(["dspace-oci-deploy", "env=staging", "tag=main-deadbee"], env)

    assert result.returncode != 0
    assert "manifest=<approved-candidate.json> is required" in result.stderr
    assert not Path(env["HELM_LOG"]).exists()


def test_direct_helm_oci_helper_matching_env_succeeds(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        [
            "helm-oci-install",
            "release=tokenplace",
            "namespace=tokenplace",
            "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
            "version_file=docs/apps/tokenplace.version",
            "tag=main-deadbee",
            "env=staging",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "show chart oci://ghcr.io/futuroptimist/charts/tokenplace --version 0.1.3" in helm_log
    assert "upgrade tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in helm_log
    assert "--description" not in helm_log


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("recipe", ["helm-oci-install", "helm-oci-upgrade"])
def test_public_helm_helper_rejects_mutation_marker_without_altering_file(
    recipe: str, tmp_path: Path, generic_app_stub_env: dict[str, str]
) -> None:
    marker = tmp_path / "preexisting-marker"
    marker.write_text("do not alter\n", encoding="utf-8")

    public_args = [
        "release=tokenplace",
        "namespace=tokenplace",
        "chart=oci://ghcr.io/futuroptimist/charts/tokenplace",
        "values=docs/examples/tokenplace.values.staging.yaml",
        "host=staging.token.place",
        "version=0.1.3",
        "version_file=",
        "tag=main-deadbee",
        "default_tag=main-deadbee",
        "env=staging",
        "description=public helper boundary test",
        "app=tokenplace",
    ]
    result = _run_just([recipe, *public_args, f"mutation_marker={marker}"], generic_app_stub_env)

    assert result.returncode != 0
    assert "justfile does not contain recipe" in result.stderr.casefold()
    assert marker.read_text(encoding="utf-8") == "do not alter\n"
    helm_log = Path(generic_app_stub_env["HELM_LOG"])
    assert not helm_log.exists() or helm_log.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_direct_helm_oci_helper_uses_digest_coordinate_without_version(
    generic_app_stub_env: dict[str, str],
) -> None:
    coordinate = "oci://ghcr.io/futuroptimist/charts/tokenplace@sha256:" + "a" * 64
    result = _run_just(
        [
            "helm-oci-install",
            "release=tokenplace",
            "namespace=tokenplace",
            f"chart={coordinate}",
            "version=0.1.3",
            "tag=main-deadbee",
            "env=staging",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    lines = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8").splitlines()
    assert f"show chart {coordinate}" in lines
    mutation = next(line for line in lines if line.startswith("upgrade "))
    assert coordinate in mutation
    assert "--version" not in mutation


@pytest.mark.usefixtures("ensure_just_available")
@pytest.mark.parametrize("recipe", ["tokenplace-deploy", "tokenplace-upgrade"])
def test_tokenplace_compat_wrappers_propagate_explicit_matching_env(
    recipe: str, generic_app_stub_env: dict[str, str]
) -> None:
    result = _run_just(
        [
            recipe,
            "tokenplace",
            "tokenplace",
            "oci://ghcr.io/futuroptimist/charts/tokenplace",
            "docs/examples/tokenplace.values.dev.yaml",
            "docs/apps/tokenplace.version",
            "",
            "main-deadbee",
            "",
            "env=staging",
            "host=example.test",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "upgrade tokenplace oci://ghcr.io/futuroptimist/charts/tokenplace" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_compat_wrapper_custom_release_still_runs_onboarded_preflight(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        [
            "tokenplace-deploy",
            "tokenplace-staging",
            "tokenplace",
            "oci://ghcr.io/futuroptimist/charts/tokenplace",
            "docs/examples/tokenplace.values.dev.yaml",
            "docs/apps/tokenplace.version",
            "",
            "main-deadbee",
            "",
            "env=staging",
            "host=example.test",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "template tokenplace-staging " in helm_log
    assert "upgrade tokenplace-staging " in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_rollback_without_requested_env_fails_before_helm(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env.pop("SUGARKUBE_ENV", None)
    result = _run_just(
        ["tokenplace-rollback", "tokenplace", "tokenplace", "12"],
        env,
    )

    assert result.returncode != 0
    assert "tokenplace-rollback requires a requested environment" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_rollback_mismatch_fails_before_helm(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "staging"
    result = _run_just(
        [
            "tokenplace-rollback",
            "tokenplace",
            "tokenplace",
            "12",
            "env=prod",
        ],
        env,
    )

    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_rollback_matching_env_succeeds(
    generic_app_stub_env: dict[str, str],
) -> None:
    result = _run_just(
        [
            "tokenplace-rollback",
            "tokenplace",
            "tokenplace",
            "12",
            "env=staging",
        ],
        generic_app_stub_env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    helm_log = Path(generic_app_stub_env["HELM_LOG"]).read_text(encoding="utf-8")
    assert "-n tokenplace rollback tokenplace 12" in helm_log


@pytest.mark.usefixtures("ensure_just_available")
def test_tokenplace_rollback_sugarkube_env_invocation_remains_guarded(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_ENV"] = "prod"
    env["SUGARKUBE_STUB_NODE_ENV"] = "staging"
    result = _run_just(
        ["tokenplace-rollback", "tokenplace", "tokenplace", "12"],
        env,
    )

    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_app_deploy_guard_mismatch_fails_before_helm(generic_app_stub_env: dict[str, str]) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "staging"
    result = _run_just(["app-deploy", "app=jobbot3000", "env=prod", "tag=main-deadbee"], env)
    assert result.returncode != 0
    assert "requested env=prod" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_app_redeploy_guard_staging_requested_prod_detected_fails_before_helm(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "prod"
    result = _run_just(["app-redeploy", "app=jobbot3000", "env=staging", "tag=main-deadbee"], env)
    assert result.returncode != 0
    assert "requested env=staging" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("ensure_just_available")
def test_app_chart_bump_remains_cluster_independent(generic_app_stub_env: dict[str, str]) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "prod"
    result = _run_just(["app-chart-bump", "app=tokenplace", "version=0.1.3"], env)
    assert result.returncode == 0, result.stderr + result.stdout
    kubectl_log = Path(env["HOME"]).parent / "kubectl.log"
    assert not kubectl_log.exists() or "get nodes" not in kubectl_log.read_text(encoding="utf-8")


@pytest.mark.usefixtures("ensure_just_available")
def test_dspace_promote_prod_guard_mismatch_fails_before_helm(
    generic_app_stub_env: dict[str, str],
) -> None:
    env = generic_app_stub_env.copy()
    env["SUGARKUBE_STUB_NODE_ENV"] = "staging"
    result = _run_just(["dspace-oci-promote-prod", "tag=main-deadbee"], env)

    assert result.returncode != 0
    assert "manifest=<approved-candidate.json> is required" in result.stderr
    helm_log_path = Path(env["HELM_LOG"])
    assert not helm_log_path.exists() or helm_log_path.read_text(encoding="utf-8") == ""
