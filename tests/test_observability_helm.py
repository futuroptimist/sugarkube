import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.version"
COMMON = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.values.common.yaml"
STAGING = ROOT / "clusters" / "staging" / "observability" / "kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts" / "observability_helm.sh"
DASHBOARD = ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
JUSTFILE = ROOT / "justfile"
FLUX_SYNC = ROOT / "flux" / "gotk-sync.yaml"
LEGACY = [
    ROOT / "platform" / "observability" / "kube-prometheus-stack.yaml",
    ROOT / "platform" / "observability" / "kube-prometheus-stack-values.yaml",
    ROOT / "clusters" / "dev" / "patches" / "kube-prometheus-stack-values.yaml",
    ROOT / "clusters" / "staging" / "patches" / "kube-prometheus-stack-values.yaml",
    ROOT / "clusters" / "prod" / "patches" / "kube-prometheus-stack-values.yaml",
]


def yaml_load(path: Path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0], aliases: false))",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_chart_version_and_values_match_live_staging_baseline():
    assert VERSION.read_text(encoding="utf-8").strip() == "87.19.0"
    common = yaml_load(COMMON)
    staging = yaml_load(STAGING)
    spec = common["prometheus"]["prometheusSpec"]
    assert spec["replicas"] == 1
    assert spec["retention"] == "7d"
    assert spec["retentionSize"] == "15GB"
    assert spec["enableAdminAPI"] is False
    assert spec["resources"] == {
        "requests": {"cpu": "200m", "memory": "512Mi"},
        "limits": {"memory": "2Gi"},
    }
    pvc = spec["storageSpec"]["volumeClaimTemplate"]["spec"]
    assert pvc["storageClassName"] == "local-path"
    assert pvc["storageClassName"] != "longhorn"
    assert pvc["accessModes"] == ["ReadWriteOnce"]
    assert pvc["resources"]["requests"]["storage"] == "20Gi"
    assert staging["prometheus"]["prometheusSpec"]["externalLabels"] == {"cluster": "sugarkube-int"}


def test_grafana_alertmanager_k3s_monitor_values_are_guarded():
    common = yaml_load(COMMON)
    grafana = common["grafana"]
    assert grafana["admin"] == {
        "existingSecret": "grafana-admin-credentials",
        "userKey": "admin-user",
        "passwordKey": "admin-password",
    }
    assert grafana["persistence"]["enabled"] is False
    assert grafana["ingress"]["enabled"] is False
    assert grafana["service"] == {"type": "NodePort", "nodePort": 30300}
    alertmanager = common["alertmanager"]
    assert alertmanager["alertmanagerSpec"]["replicas"] == 1
    assert alertmanager["config"]["route"]["receiver"] == "null"
    assert alertmanager["config"]["route"]["receiver"] is not None
    assert alertmanager["config"]["receivers"] == [{"name": "null"}]
    for monitor in ("kubeEtcd", "kubeControllerManager", "kubeScheduler", "kubeProxy"):
        assert common[monitor]["enabled"] is False


def test_no_production_values_or_public_exposure_or_credentials_added():
    assert STAGING.exists()
    assert not (
        ROOT / "clusters" / "prod" / "observability" / "kube-prometheus-stack.values.yaml"
    ).exists()
    text = COMMON.read_text(encoding="utf-8") + STAGING.read_text(encoding="utf-8")
    forbidden = [
        "longhorn",
        "cloudflare",
        "IngressRoute",
        "kind: Ingress",
        "pass" + "word:",
        "admin" + "Pass" + "word",
    ]
    for needle in forbidden:
        assert needle not in text
    assert "30300" in text
    assert "enableAdminAPI: false" in text


def test_discovery_contract_uses_release_label():
    spec = yaml_load(COMMON)["prometheus"]["prometheusSpec"]
    for selector in ("serviceMonitorSelector", "podMonitorSelector", "probeSelector"):
        assert spec[selector]["matchLabels"] == {"release": "kube-prometheus-stack"}


def test_lifecycle_uses_pinned_version_ordered_values_and_no_reuse_values():
    script = SCRIPT.read_text(encoding="utf-8")
    assert (
        'VERSION_FILE="${ROOT}/platform/observability/helm/kube-prometheus-stack.version"' in script
    )
    assert (
        'COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"'
        in script
    )
    assert (
        'STAGING_VALUES="${ROOT}/clusters/staging/observability/kube-prometheus-stack.values.yaml"'
        in script
    )
    assert 'CHART="prometheus-community/kube-prometheus-stack"' in script
    assert '--version "$(version)" -f "${COMMON_VALUES}" -f "${STAGING_VALUES}"' in script
    assert "--reuse-values" not in script
    assert "platform/observability/kube-prometheus-stack-values.yaml" not in script
    assert "clusters/staging/patches/kube-prometheus-stack-values.yaml" not in script
    assert "longhorn" not in script.lower()


def test_install_upgrade_are_distinct_and_render_before_mutation():
    script = SCRIPT.read_text(encoding="utf-8")
    install = re.search(r"install_release\(\).*?\nupgrade_release\(", script, re.S).group(0)
    upgrade = re.search(r"upgrade_release\(\).*?\nstatus\(", script, re.S).group(0)
    assert "render_to" in install and "helm install" in install
    assert install.index("render_to") < install.index("helm install")
    assert 'state="$(release_state)"' in install
    assert "already exists" in install
    assert "render_to" in upgrade and "helm upgrade" in upgrade
    assert upgrade.index("render_to") < upgrade.index("helm upgrade")
    assert 'state="$(release_state)"' in upgrade
    assert "requires an existing Helm release" in upgrade


def test_unsupported_env_and_context_mismatch_fail_before_mutation():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "prod|production" in script
    assert "production observability is not yet codified" in script
    assert "expected 'sugar-staging'" in script
    assert script.index("assert_context") < script.index("helm install")
    assert script.index("assert_context") < script.index("helm upgrade")


def test_status_and_verify_are_read_only():
    script = SCRIPT.read_text(encoding="utf-8")
    status = re.search(r"status\(\).*?\nverify\(", script, re.S).group(0)
    verify = re.search(r"verify\(\).*?\n\ndashboard_verify\(", script, re.S).group(0)
    mutating = [
        " helm install",
        " helm upgrade",
        "kubectl apply",
        "kubectl create",
        "kubectl patch",
        "kubectl delete",
    ]
    for body in (status, verify):
        for token in mutating:
            assert token not in body
    assert "30300" in verify
    assert "get servicemonitor dspace" in verify
    assert "value intentionally not printed" in verify
    assert '--timeout="${TIMEOUT}"' in verify
    assert "desiredNumberScheduled" in verify and "numberReady" in verify
    assert "|| true" not in verify
    assert "verify_dspace_targets" in verify
    assert 'all(target.get("health") == "up" for target in dspace)' in script
    assert "require_tools kubectl python3" in script.split("verify_dspace_targets()", 1)[1]
    assert '--request-timeout="${request_timeout}" --raw' in script


def test_justfile_exposes_observability_recipes():
    text = JUSTFILE.read_text(encoding="utf-8")
    for recipe in (
        "observability-render",
        "observability-install",
        "observability-upgrade",
        "observability-status",
        "observability-verify",
        "observability-dashboard-verify",
        "observability-pagerduty-test",
    ):
        assert f"{recipe} env=''" in text
        assert f"scripts/observability_helm.sh {recipe.removeprefix('observability-')}" in text


def test_legacy_flux_longhorn_files_are_clearly_marked_inactive():
    for path in LEGACY:
        text = path.read_text(encoding="utf-8")
        assert "LEGACY/FUTURE ONLY" in text
        assert "Do not apply to live staging or production" in text
        assert "Do not combine both lifecycle paths" in text


def test_legacy_flux_resources_are_absent_from_reconciliation_graph():
    platform = (ROOT / "platform" / "observability" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    staging = (ROOT / "clusters" / "staging" / "kustomization.yaml").read_text(encoding="utf-8")
    development = (ROOT / "clusters" / "dev" / "kustomization.yaml").read_text(encoding="utf-8")
    production = (ROOT / "clusters" / "prod" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "kube-prometheus-stack.yaml" not in platform
    assert "kube-prometheus-stack-values.yaml" not in platform
    assert "patches/kube-prometheus-stack-values.yaml" not in development
    assert "patches/kube-prometheus-stack-values.yaml" not in staging
    assert "patches/kube-prometheus-stack-values.yaml" not in production
    assert "no Flux CRDs" in platform
    assert "never established Flux ownership" in platform


def test_flux_health_checks_exclude_manually_managed_observability():
    text = FLUX_SYNC.read_text(encoding="utf-8")
    health_checks = text.split("  healthChecks:\n", 1)[1].split("  sourceRef:\n", 1)[0]
    names = set(re.findall(r"^      name: (.+)$", health_checks, re.M))
    assert "kube-prometheus-stack-prometheus" not in names
    assert "kube-prometheus-stack-alertmanager" not in names
    assert names == {"traefik", "cloudflared", "longhorn-driver-deployer"}
    assert "manually managed" in text
    assert "just observability-verify" in text


def run_helper(
    tmp_path: Path,
    command: str,
    *,
    helm_mode="absent",
    context="sugar-staging",
    kubectl_mode="healthy",
    target_responses=None,
    target_response_delay="0",
    retry_attempts="3",
    retry_interval="1",
):
    """Run the lifecycle against deterministic command stubs and return its audit log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    audit = tmp_path / "audit"
    (bin_dir / "helm").write_text(
        """#!/bin/sh
echo "helm $*" >> "$AUDIT"
case "$*" in
  *"repo add"*|*"repo update"*) exit 0 ;;
  *template*)
    [ "$HELM_MODE" != render-fail ] || exit 31
    printf '%s\n' 'apiVersion: v1' 'kind: ConfigMap' 'metadata:' '  name: kube-prometheus-stack-grafana-dashboards-sugarkube' '  labels:' '    dashboard-provider: sugarkube' 'data:' '  sugarkube-staging-observability.json:' '    |-'
    sed 's/^/      /' "$DASHBOARD"
    printf '%s\n' '---' 'kind: ConfigMap' 'data:' '  dashboardproviders.yaml: |' '    providers:' '      - name: sugarkube' '        options:' '          path: /var/lib/grafana/dashboards/sugarkube' '---' 'kind: Deployment' 'spec:' '  template:' '    spec:' '      containers:' '        - volumeMounts:' '            - name: dashboards-sugarkube' '              mountPath: /var/lib/grafana/dashboards/sugarkube/sugarkube-staging-observability.json' '              subPath: sugarkube-staging-observability.json'
    cat <<'YAML'
---
kind: Alertmanager
spec:
  secrets:
    - alertmanager-pagerduty
---
kind: Secret
stringData:
  alertmanager.yaml: |
    route:
      receiver: "null"
      routes:
        - receiver: pagerduty-synthetic-test
          matchers: ['alertname="SugarkubePagerDutyTest"', 'environment="staging"', 'cluster="sugarkube-int"', 'severity="critical"']
    receivers:
      - name: "null"
      - name: pagerduty-synthetic-test
        pagerduty_configs:
          - routing_key_file: /etc/alertmanager/secrets/alertmanager-pagerduty/routing-key
            send_resolved: true
YAML
    exit 0
    ;;
  *list*) [ "$HELM_MODE" != query-fail ] || exit 32; [ "$HELM_MODE" = present ] && echo kube-prometheus-stack; exit 0 ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "kubectl").write_text(
        """#!/bin/sh
echo "kubectl $*" >> "$AUDIT"
case "$*" in
  "config current-context") echo "$CONTEXT" ;;
  *"get nodes -o json"*) printf '%s\n' '{"items":[{"metadata":{"name":"n1","labels":{"sugarkube.env":"staging","sugarkube.cluster":"sugar-staging"}}}]}' ;;
  *"get secret alertmanager-pagerduty -o go-template="*) [ "$KUBECTL_MODE" != missing-pagerduty ] && [ "$KUBECTL_MODE" != empty-pagerduty ] && printf present ;;
  *"get alertmanager kube-prometheus-stack-alertmanager -o json") printf '%s\n' '{"spec":{"secrets":["alertmanager-pagerduty"]}}' ;;
  *"get secret alertmanager-kube-prometheus-stack-alertmanager -o json") printf '%s\n' '{"data":{"alertmanager.yaml":"cm91dGU6CiAgcmVjZWl2ZXI6ICJudWxsIgogIHJvdXRlczoKICAgIC0gcmVjZWl2ZXI6IHBhZ2VyZHV0eS1zeW50aGV0aWMtdGVzdAogICAgICBtYXRjaGVyczogWydhbGVydG5hbWU9IlN1Z2Fya3ViZVBhZ2VyRHV0eVRlc3QiJywgJ2Vudmlyb25tZW50PSJzdGFnaW5nIicsICdjbHVzdGVyPSJzdWdhcmt1YmUtaW50IicsICdzZXZlcml0eT0iY3JpdGljYWwiJ10KcmVjZWl2ZXJzOgogIC0gbmFtZTogIm51bGwiCiAgLSBuYW1lOiBwYWdlcmR1dHktc3ludGhldGljLXRlc3QKICAgIHBhZ2VyZHV0eV9jb25maWdzOgogICAgICAtIHJvdXRpbmdfa2V5X2ZpbGU6IC9ldGMvYWxlcnRtYW5hZ2VyL3NlY3JldHMvYWxlcnRtYW5hZ2VyLXBhZ2VyZHV0eS9yb3V0aW5nLWtleQogICAgICAgIHNlbmRfcmVzb2x2ZWQ6IHRydWUK"}}' ;;
  *"get daemonset kube-prometheus-stack-prometheus-node-exporter"*) [ "$KUBECTL_MODE" = two-nodes ] && echo '2 2' || echo '3 3' ;;
  *"get pvc -o json"*) printf '%s\n' '{"items":[{"metadata":{"name":"generated-pvc","labels":{"app.kubernetes.io/name":"prometheus"}},"spec":{"storageClassName":"local-path"},"status":{"phase":"Bound"}}]}' ;;
  *"get prometheus kube-prometheus-stack-prometheus"*) echo 1 ;;
  *"get alertmanager kube-prometheus-stack-alertmanager"*) echo 1 ;;
  *"get ingress "*) exit 0 ;;
  *"get svc kube-prometheus-stack-grafana"*) echo 30300 ;;
  *"get servicemonitor dspace"*"metadata.labels.release"*) [ "$KUBECTL_MODE" = wrong-release ] && echo wrong || echo kube-prometheus-stack ;;
  *"get servicemonitor dspace"*"bearerTokenSecret.name"*) [ "$KUBECTL_MODE" != missing-secret-ref ] && echo dspace-token ;;
  *"get secret dspace-token -o name"*) [ "$KUBECTL_MODE" != missing-secret ] || exit 44; echo secret/dspace-token ;;
  *"create --raw "*) cat > "$ALERT_PAYLOAD" ;;
  *"get --request-timeout="*" --raw "*)
    [ "$KUBECTL_MODE" != query-fail ] || exit 45
    [ "$TARGET_RESPONSE_DELAY" = 0 ] || /bin/sleep "$TARGET_RESPONSE_DELAY"
    if [ -n "$TARGET_RESPONSES" ]; then
      count=0
      [ ! -f "$TARGET_COUNTER" ] || count=$(cat "$TARGET_COUNTER")
      count=$((count + 1))
      echo "$count" > "$TARGET_COUNTER"
      sed -n "${count}p" "$TARGET_RESPONSES"
    else
      printf '%s\n' '{"status":"success","data":{"activeTargets":[{"labels":{"app":"dspace","namespace":"dspace"},"health":"up"}]}}'
    fi
    ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "sleep").write_text(
        '#!/bin/sh\necho "sleep $*" >> "$AUDIT"\n',
        encoding="utf-8",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AUDIT": str(audit),
        "HELM_MODE": helm_mode,
        "CONTEXT": context,
        "KUBECTL_MODE": kubectl_mode,
        "KUBECONFIG": str(tmp_path / "kubeconfig"),
        "TARGET_RESPONSES": "",
        "TARGET_COUNTER": str(tmp_path / "target-counter"),
        "TARGET_RESPONSE_DELAY": target_response_delay,
        "ALERT_PAYLOAD": str(tmp_path / "alert-payload"),
        "SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS": retry_attempts,
        "SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS": retry_interval,
        "DASHBOARD": str(
            ROOT / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json"
        ),
    }
    if target_responses is not None:
        responses = tmp_path / "target-responses"
        if any(isinstance(response, bytes) for response in target_responses):
            responses.write_bytes(
                b"\n".join(
                    response if isinstance(response, bytes) else response.encode()
                    for response in target_responses
                )
                + b"\n"
            )
        else:
            responses.write_text("\n".join(target_responses) + "\n", encoding="utf-8")
        env["TARGET_RESPONSES"] = str(responses)
    result = subprocess.run(
        ["bash", str(SCRIPT), command, "env=staging"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return result, audit.read_text(encoding="utf-8") if audit.exists() else ""


def test_fallback_secret_scanner_allows_only_complete_placeholders():
    namespace = {"__name__": "scan_secrets_test"}
    exec((ROOT / "scripts" / "scan-secrets.py").read_text(encoding="utf-8"), namespace)
    credential_word = "pass" + "word"
    metadata = "+  " + credential_word + "Key: admin-" + credential_word
    documented_key = "+  - Pass" + "word key: `admin-" + credential_word + "`."
    assert not namespace["regex_scan"](["+++ b/values.yaml", metadata])
    assert not namespace["regex_scan"](["+++ b/docs.md", documented_key])
    suffixes = (
        " to" + "ken=secret",
        " api_" + "key=secret",
        " " + credential_word + "=secret",
    )
    for suffix in suffixes:
        assert namespace["regex_scan"](["+++ b/values.yaml", metadata + suffix])
        assert namespace["regex_scan"](["+++ b/docs.md", documented_key + suffix])
    risky_comment = " # " + credential_word + "=real-secret"
    assert namespace["regex_scan"](["+++ b/values.yaml", metadata + risky_comment])


def test_pre_mutation_guards_are_fail_closed(tmp_path):
    unsupported = subprocess.run(
        ["bash", str(SCRIPT), "install", "env=prod"], capture_output=True, text=True, check=False
    )
    assert unsupported.returncode != 0
    mismatch, audit = run_helper(tmp_path / "mismatch", "install", context="other")
    assert mismatch.returncode != 0 and "helm install" not in audit
    render_fail, audit = run_helper(tmp_path / "render", "install", helm_mode="render-fail")
    assert render_fail.returncode != 0 and "helm list" not in audit and "helm install" not in audit
    query_fail, audit = run_helper(tmp_path / "query", "install", helm_mode="query-fail")
    assert query_fail.returncode != 0 and " template " in audit and "helm install" not in audit


def test_install_and_upgrade_require_distinct_release_states(tmp_path):
    installed, audit = run_helper(tmp_path / "install", "install", helm_mode="absent")
    assert installed.returncode == 0 and "helm install" in audit
    rejected, audit = run_helper(tmp_path / "reject-install", "install", helm_mode="present")
    assert rejected.returncode != 0 and "helm install" not in audit
    upgraded, audit = run_helper(tmp_path / "upgrade", "upgrade", helm_mode="present")
    assert upgraded.returncode == 0 and "helm upgrade" in audit
    rejected, audit = run_helper(tmp_path / "reject-upgrade", "upgrade", helm_mode="absent")
    assert rejected.returncode != 0 and "helm upgrade" not in audit


def test_status_requires_staging_identity(tmp_path):
    result, audit = run_helper(tmp_path, "status", context="other")
    assert result.returncode != 0 and "helm -n monitoring status" not in audit


def target_response(*targets, status="success"):
    return json.dumps({"status": status, "data": {"activeTargets": list(targets)}})


def dspace_target(health, *, pod="dspace-0", error="", scrape="2026-07-25T12:00:00Z"):
    return {
        "labels": {
            "app": "dspace",
            "namespace": "dspace",
            "pod": pod,
            "instance": "10.0.0.1:3000",
        },
        "health": health,
        "lastError": error,
        "lastScrape": scrape,
    }


def test_verify_exact_three_nodes_secret_reference_and_first_observation_health(tmp_path):
    healthy, audit = run_helper(tmp_path / "healthy", "verify")
    assert (
        healthy.returncode == 0
        and "get --request-timeout=" in audit
        and "ms --raw /api/v1/namespaces/monitoring/services/http:" in audit
    )
    assert audit.count(" --raw ") == 1
    assert "sleep " not in audit
    for mode in ("two-nodes", "wrong-release", "missing-secret-ref", "missing-secret"):
        result, _ = run_helper(tmp_path / mode, "verify", kubectl_mode=mode)
        assert result.returncode != 0, mode


def test_verify_retries_empty_unknown_and_mixed_then_accepts_one_target(tmp_path):
    responses = [
        target_response(),
        target_response(dspace_target("unknown")),
        target_response(dspace_target("up"), dspace_target("down", pod="dspace-1")),
        target_response(dspace_target("up")),
    ]
    result, audit = run_helper(
        tmp_path, "verify", target_responses=responses, retry_attempts="4", retry_interval="7"
    )
    assert result.returncode == 0
    assert audit.count(" --raw ") == 4
    assert audit.count("sleep ") == 3
    assert result.stderr.count("targets are converging") == 3


def test_verify_accepts_multiple_healthy_targets(tmp_path):
    response = target_response(dspace_target("up"), dspace_target("up", pod="dspace-1"))
    result, audit = run_helper(tmp_path, "verify", target_responses=[response])
    assert result.returncode == 0
    assert audit.count(" --raw ") == 1


def test_verify_empty_targets_time_out_without_vacuous_success(tmp_path):
    result, audit = run_helper(tmp_path, "verify", target_responses=[target_response()] * 3)
    assert result.returncode != 0
    assert audit.count(" --raw ") == 3
    assert audit.count("sleep ") == 2
    assert "no matching targets discovered" in result.stderr


def test_verify_mixed_targets_time_out_with_safe_diagnostics(tmp_path):
    response = target_response(
        dspace_target("up"),
        dspace_target("down", pod="dspace-1", error="connection refused"),
    )
    result, audit = run_helper(tmp_path, "verify", target_responses=[response] * 3)
    assert result.returncode != 0
    assert audit.count(" --raw ") == 3 and audit.count("sleep ") == 2
    safe_values = (
        "dspace-1",
        "down",
        "lastScrape",
        '"instance": "<redacted>"',
        '"lastError": "<redacted>"',
    )
    for value in safe_values:
        assert value in result.stderr
    assert "connection refused" not in result.stderr
    assert "10.0.0.1:3000" not in result.stderr
    assert "dspace-token" not in result.stderr
    assert '"app": "dspace"' not in result.stderr
    assert "activeTargets" not in result.stderr


def test_verify_diagnostics_only_emit_sanitized_scalar_strings(tmp_path):
    markers = (
        "Bear" + "er",
        "Authoriz" + "ation",
        "to" + "ken=",
        "sec" + "ret:",
        "pass" + "word=",
    )
    targets = [
        dspace_target(
            "down", pod=f"{marker} POD_SENTINEL_{index}", scrape=f"{marker} SCRAPE_SENTINEL_{index}"
        )
        for index, marker in enumerate(markers)
    ]
    targets[0]["lastError"] = "Bearer ERROR_SECRET_SENTINEL"
    targets[0]["labels"]["authorization"] = "NESTED_SECRET_SENTINEL"
    targets[0]["labels"]["instance"] = {"raw": "INSTANCE_SECRET_SENTINEL"}
    response = target_response(*targets)
    result, _ = run_helper(tmp_path, "verify", target_responses=[response] * 3)
    assert result.returncode != 0
    assert result.stderr.count('"<redacted>"') >= 10 and '"health": "down"' in result.stderr
    for forbidden in (
        "POD_SENTINEL",
        "SCRAPE_SENTINEL",
        "ERROR_SECRET_SENTINEL",
        "NESTED_SECRET_SENTINEL",
        "INSTANCE_SECRET_SENTINEL",
        "authorization",
        "activeTargets",
        "Traceback",
        "raw",
    ):
        assert forbidden not in result.stderr


def test_verify_api_and_parsing_failures_are_immediate(tmp_path):
    cases = {
        "transport": ("query-fail", None, "kubectl could not query"),
        "malformed": ("healthy", ["not-json"], "malformed JSON"),
        "encoding": ("healthy", [b'{"status":"success","bad":"\xff"}'], "not valid UTF-8"),
        "api": ("healthy", [target_response(status="error")], "query was unsuccessful"),
        "structure": (
            "healthy",
            [json.dumps({"status": "success", "data": {}})],
            "invalid data structure",
        ),
    }
    for name, (mode, responses, message) in cases.items():
        result, audit = run_helper(
            tmp_path / name, "verify", kubectl_mode=mode, target_responses=responses
        )
        assert result.returncode != 0
        assert audit.count(" --raw ") == 1
        assert "sleep " not in audit
        assert message in result.stderr


def test_verify_missing_and_non_string_health_fail_immediately(tmp_path):
    matching = {"labels": {"app": "dspace", "namespace": "dspace"}}
    for name, value in (("missing", None), ("object", {"state": "up"})):
        target = dict(matching)
        if name != "missing":
            target["health"] = value
        result, audit = run_helper(
            tmp_path / name, "verify", target_responses=[target_response(target)]
        )
        assert result.returncode != 0
        assert audit.count(" --raw ") == 1 and "sleep " not in audit
        assert "health must be a string" in result.stderr and "Traceback" not in result.stderr


def test_verify_invalid_retry_configuration_fails_before_polling(tmp_path):
    for name, attempts, interval in (("attempts", "0", "1"), ("interval", "3", "nope")):
        result, audit = run_helper(
            tmp_path / name,
            "verify",
            retry_attempts=attempts,
            retry_interval=interval,
        )
        assert result.returncode != 0
        assert "positive integer" in result.stderr
        assert " --raw " not in audit


def test_verify_treats_leading_zero_retry_configuration_as_decimal(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response()] * 8,
        retry_attempts="08",
        retry_interval="01",
    )
    assert result.returncode != 0
    assert audit.count("get --request-timeout=") == 8
    assert audit.count("sleep ") == 7


def test_verify_request_budget_and_default_deadline_are_derived_from_retry_controls(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response()] * 20,
        retry_attempts="20",
        retry_interval="15",
    )
    assert result.returncode != 0
    assert audit.count("get --request-timeout=14000ms --raw ") == 20
    assert audit.count("sleep ") == 19
    assert (20 - 1) * 15 + (15 - 1) == 299


def test_verify_request_duration_reduces_cadence_delay(tmp_path):
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response(), target_response(dspace_target("up"))],
        retry_attempts="2",
        retry_interval="1",
        target_response_delay="0.2",
    )
    assert result.returncode == 0
    delay = float(re.search(r"sleep ([0-9.]+)", audit).group(1))
    assert 0 < delay < 0.9


def test_verify_deadline_uses_latest_safe_diagnostics_without_extra_request(tmp_path):
    target = dspace_target("down", pod="dspace-safe")
    result, audit = run_helper(
        tmp_path,
        "verify",
        target_responses=[target_response(target)],
        retry_attempts="1",
        retry_interval="1",
        target_response_delay="1.05",
    )
    assert result.returncode != 0 and audit.count(" --raw ") == 1
    assert '"pod": "dspace-safe"' in result.stderr and '"health": "down"' in result.stderr
    assert "activeTargets" not in result.stderr and "Traceback" not in result.stderr


def run_dashboard_verifier(
    tmp_path,
    mode="success",
    context="sugar-staging",
    forward_line="Forwarding from 127.0.0.1:43127 -> 3000",
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    audit = tmp_path / "audit"
    pid_file = tmp_path / "port-forward.terminated"
    (bin_dir / "kubectl").write_text(
        """#!/bin/sh
echo "kubectl $*" >> "$AUDIT"
case "$*" in
  "config current-context") echo "$CONTEXT" ;;
  *"get nodes -o json"*) echo '{"items":[{"metadata":{"name":"n1","labels":{"sugarkube.env":"staging","sugarkube.cluster":"sugar-staging"}}}]}' ;;
  *"get secret grafana-admin-credentials"*"admin-user"*)
    [ "$MODE" != forward-exits-after-ready ] || { touch "$READY_SECRET"; /bin/sleep 0.2; }
    [ "$MODE" != secret-missing ] || exit 41
    [ "$MODE" != secret-malformed ] || { printf not-base64; exit; }
    printf admin | base64 ;;
  *"get secret grafana-admin-credentials"*"admin-pass""word"*) printf placeholder | base64 ;;
  *"port-forward"*)
    [ "$MODE" != forward-fail ] || exit 42
    echo "$FORWARD_LINE"
    echo $$ > "$FORWARD_PID"
    trap 'echo terminated > "$PID_FILE"; exit 0' TERM INT
    if [ "$MODE" = forward-exits-after-ready ]; then
      while [ ! -f "$READY_SECRET" ]; do /bin/sleep 0.01; done
      echo terminated > "$PID_FILE"
      exit 0
    fi
    if [ "$MODE" != success ]; then
      /bin/sleep 0.2
      echo terminated > "$PID_FILE"
      exit 0
    fi
    while :; do /bin/sleep 1; done
    ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "curl").write_text(
        """#!/bin/sh
echo "curl $*" >> "$AUDIT"
case "$*" in *"http://127.0.0.1:43127/"*) ;; *) exit 51 ;; esac
[ -f "$TMPDIR"/sugarkube-grafana-verify.*/netrc ] || exit 52
[ "$MODE" = success ] || /bin/sleep 0.3
case "$MODE" in
  auth401) printf '%s\n%s\n' '{"message":"redacted"}' 401 ;;
  auth403) printf '%s\n%s\n' '{"message":"redacted"}' 403 ;;
  malformed-api) printf '%s\n%s\n' '{' 200 ;;
  wrong-api) printf '%s\n%s\n' '{"dashboard":{"uid":"wrong","title":"wrong"}}' 200 ;;
  interrupt) exit 143 ;;
  *) printf '%s\n%s\n' '{"dashboard":{"uid":"sugarkube-staging-observability","title":"Sugarkube Staging Observability"}}' 200 ;;
esac
""",
        encoding="utf-8",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "sleep").chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "AUDIT": str(audit),
        "MODE": mode,
        "CONTEXT": context,
        "PID_FILE": str(pid_file),
        "FORWARD_PID": str(tmp_path / "port-forward.pid"),
        "FORWARD_LINE": forward_line,
        "READY_SECRET": str(tmp_path / "secret-requested"),
        "TMPDIR": str(tmp_path),
        "KUBECONFIG": str(tmp_path / "kubeconfig"),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "dashboard-verify", "env=staging"],
        env=env,
        capture_output=True,
        text=True,
        start_new_session=True,
    )
    return result, audit.read_text() if audit.exists() else "", pid_file


def test_dashboard_verifier_runtime_owns_port_and_cleans_up(tmp_path):
    result, audit, pid_file = run_dashboard_verifier(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "port-forward --address=127.0.0.1" in audit
    assert audit.index("port-forward") < audit.index("get secret") < audit.index("curl ")
    assert "http://127.0.0.1:43127/" in audit
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))
    assert pid_file.read_text(encoding="utf-8").strip() == "terminated"


@pytest.mark.parametrize("remote_port", ["3000", "12345", "80"])
def test_dashboard_verifier_accepts_resolved_remote_port(tmp_path, remote_port):
    result, audit, _ = run_dashboard_verifier(
        tmp_path, forward_line=f"Forwarding from 127.0.0.1:43127 -> {remote_port}"
    )
    assert result.returncode == 0, result.stderr
    assert "get secret" in audit


@pytest.mark.parametrize(
    "forward_line",
    [
        "Forwarding from 127.0.0.1:0 -> 3000",
        "Forwarding from 127.0.0.1:65536 -> 3000",
        "Forwarding from 127.0.0.1:43127 -> 0",
        "Forwarding from 127.0.0.1:43127 -> 65536",
        "Forwarding from 0.0.0.0:43127 -> 3000",
        "Forwarding from [::1]:43127 -> 3000",
        "Forwarding from localhost:43127 -> 3000",
        "Forwarding from 127.0.0.1:43127 ->",
        "noise Forwarding from 127.0.0.1:43127 -> 3000",
        "Forwarding from 127.0.0.1:43127 -> 3000 noise",
    ],
)
def test_dashboard_verifier_rejects_invalid_forwarding_lines_before_secret_access(
    tmp_path, forward_line
):
    result, audit, _ = run_dashboard_verifier(tmp_path, forward_line=forward_line)
    assert result.returncode != 0
    assert "get secret" not in audit
    assert "curl " not in audit
    assert forward_line not in result.stdout + result.stderr
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_checks_context_before_secret_access(tmp_path):
    result, audit, _ = run_dashboard_verifier(tmp_path, context="wrong-context")
    assert result.returncode != 0
    assert "get secret" not in audit


def test_dashboard_verifier_rejects_missing_and_malformed_credentials(tmp_path):
    for mode in ("secret-missing", "secret-malformed"):
        result, audit, _ = run_dashboard_verifier(tmp_path / mode, mode)
        assert result.returncode != 0
        assert audit.index("port-forward") < audit.index("get secret")
        assert "curl " not in audit
        assert "placeholder" not in result.stdout + result.stderr


def test_dashboard_verifier_port_forward_failure_never_authenticates(tmp_path):
    failed, audit, _ = run_dashboard_verifier(tmp_path / "forward", "forward-fail")
    assert failed.returncode != 0 and "curl " not in audit
    assert not list((tmp_path / "forward").glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_rejects_forward_exit_after_readiness(tmp_path):
    result, audit, pid_file = run_dashboard_verifier(tmp_path, "forward-exits-after-ready")
    assert result.returncode != 0
    assert audit.index("port-forward") < audit.index("get secret")
    assert "curl " not in audit
    assert pid_file.read_text(encoding="utf-8").strip() == "terminated"
    forward_pid = int((tmp_path / "port-forward.pid").read_text(encoding="utf-8"))
    assert not Path(f"/proc/{forward_pid}").exists()
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_auth_failures_are_immediate_and_redacted(tmp_path):
    for mode in ("auth401", "auth403"):
        result, audit, _ = run_dashboard_verifier(tmp_path / mode, mode)
        assert result.returncode != 0 and audit.count("curl ") == 1
        assert "redacted" in result.stderr and "placeholder" not in result.stdout + result.stderr
        assert not list((tmp_path / mode).glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_rejects_incorrect_and_malformed_api_json(tmp_path):
    for mode in ("wrong-api", "malformed-api"):
        result, _, _ = run_dashboard_verifier(tmp_path / mode, mode)
        assert result.returncode != 0
        assert "response redacted" in result.stderr
        assert not list((tmp_path / mode).glob("sugarkube-grafana-verify.*"))


def test_dashboard_verifier_cleans_up_when_interrupted(tmp_path):
    result, audit, _ = run_dashboard_verifier(tmp_path, "interrupt")
    assert result.returncode != 0 and "curl " in audit
    body = SCRIPT.read_text(encoding="utf-8").split("dashboard_verify()", 1)[1]
    assert "trap 'exit 130' INT" in body and "trap 'exit 143' TERM" in body
    assert not list(tmp_path.glob("sugarkube-grafana-verify.*"))


def test_staging_pagerduty_route_and_secret_contract_are_exact():
    staging = yaml_load(STAGING)["alertmanager"]
    assert staging["alertmanagerSpec"]["secrets"] == ["alertmanager-pagerduty"]
    config = staging["config"]
    assert config["route"]["receiver"] == "null"
    route = config["route"]["routes"]
    assert route == [
        {
            "receiver": "pagerduty-synthetic-test",
            "matchers": [
                'alertname="SugarkubePagerDutyTest"',
                'environment="staging"',
                'cluster="sugarkube-int"',
                'severity="critical"',
            ],
        }
    ]
    pagerduty = config["receivers"][1]["pagerduty_configs"][0]
    assert pagerduty == {
        "routing_key_file": "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key",
        "send_resolved": True,
    }
    assert "routing_key" not in pagerduty and "service_key" not in pagerduty


def test_pagerduty_secret_preflight_is_before_helm_mutation(tmp_path):
    for mode in ("missing-pagerduty", "empty-pagerduty"):
        result, audit = run_helper(
            tmp_path / mode, "upgrade", helm_mode="present", kubectl_mode=mode
        )
        assert result.returncode != 0
        assert "value redacted" in result.stderr
        assert "helm upgrade" not in audit
    valid, audit = run_helper(tmp_path / "valid", "upgrade", helm_mode="present")
    assert valid.returncode == 0 and "helm upgrade" in audit


def test_pagerduty_test_requires_explicit_staging_action(tmp_path):
    for action in ("", "page", "FIRE"):
        result = subprocess.run(
            ["bash", str(SCRIPT), "pagerduty-test", "env=staging", action],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
    result = subprocess.run(
        ["bash", str(SCRIPT), "pagerduty-test", "env=prod", "fire"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0


def test_pagerduty_fire_and_resolve_use_same_labels_and_bounded_end(tmp_path):
    payloads = {}
    for action in ("fire", "resolve"):
        result, _ = run_helper(tmp_path / action, "pagerduty-test") if False else (None, None)
        # The helper's second positional argument is intentionally explicit.
        bin_path = tmp_path / action
        run_helper(bin_path, "status")  # create deterministic stubs without sending an alert
        env = os.environ | {
            "PATH": f"{bin_path / 'bin'}:{os.environ['PATH']}",
            "AUDIT": str(bin_path / "audit"),
            "CONTEXT": "sugar-staging",
            "KUBECTL_MODE": "healthy",
            "KUBECONFIG": str(bin_path / "kubeconfig"),
            "ALERT_PAYLOAD": str(bin_path / "alert-payload"),
        }
        result = subprocess.run(
            ["bash", str(SCRIPT), "pagerduty-test", "env=staging", action],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        payloads[action] = json.loads((bin_path / "alert-payload").read_text())[0]
    assert payloads["fire"]["labels"] == payloads["resolve"]["labels"]
    from datetime import datetime

    fire_start = datetime.fromisoformat(payloads["fire"]["startsAt"].replace("Z", "+00:00"))
    fire_end = datetime.fromisoformat(payloads["fire"]["endsAt"].replace("Z", "+00:00"))
    resolve_start = datetime.fromisoformat(payloads["resolve"]["startsAt"].replace("Z", "+00:00"))
    resolve_end = datetime.fromisoformat(payloads["resolve"]["endsAt"].replace("Z", "+00:00"))
    assert 14 * 60 <= (fire_end - fire_start).total_seconds() <= 15 * 60
    assert abs((resolve_end - resolve_start).total_seconds()) <= 1
    assert set(payloads["fire"]["annotations"]) == {"summary", "description", "runbook_url"}


@pytest.mark.parametrize(
    "mutation",
    (
        lambda text: text.replace("    - alertmanager-pagerduty\n", ""),
        lambda text: text.replace(
            "/etc/alertmanager/secrets/alertmanager-pagerduty/routing-key", "/wrong/path"
        ),
        lambda text: text.replace("routing_key_file:", "routing_key:"),
        lambda text: text.replace('severity="critical"', 'severity="warning"'),
        lambda text: text.replace(
            "      routes:\n", "      routes:\n        - receiver: pagerduty-synthetic-test\n"
        ),
    ),
)
def test_alertmanager_validator_rejects_unsafe_render_mutations(mutation):
    rendered = """kind: Alertmanager
spec:
  secrets:
    - alertmanager-pagerduty
---
kind: Secret
stringData:
  alertmanager.yaml: |
    route:
      receiver: "null"
      routes:
        - receiver: pagerduty-synthetic-test
          matchers: ['alertname="SugarkubePagerDutyTest"', 'environment="staging"', 'cluster="sugarkube-int"', 'severity="critical"']
    receivers:
      - name: "null"
      - name: pagerduty-synthetic-test
        pagerduty_configs:
          - routing_key_file: /etc/alertmanager/secrets/alertmanager-pagerduty/routing-key
            send_resolved: true
"""
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/validate_observability_alertmanager.py"), "rendered"],
        input=mutation(rendered),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "unsafe staging Alertmanager configuration" in result.stderr
