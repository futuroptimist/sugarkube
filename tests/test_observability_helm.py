import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.version"
COMMON = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.values.common.yaml"
STAGING = ROOT / "clusters" / "staging" / "observability" / "kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts" / "observability_helm.sh"
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
    assert not (ROOT / "clusters" / "prod" / "observability" / "kube-prometheus-stack.values.yaml").exists()
    text = COMMON.read_text(encoding="utf-8") + STAGING.read_text(encoding="utf-8")
    forbidden = ["longhorn", "cloudflare", "IngressRoute", "kind: Ingress", "password:", "adminPassword"]
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
    assert 'VERSION_FILE="${ROOT}/platform/observability/helm/kube-prometheus-stack.version"' in script
    assert 'COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"' in script
    assert 'STAGING_VALUES="${ROOT}/clusters/staging/observability/kube-prometheus-stack.values.yaml"' in script
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
    assert 'expected \'sugar-staging\'' in script
    assert script.index("assert_context") < script.index("helm install")
    assert script.index("assert_context") < script.index("helm upgrade")


def test_status_and_verify_are_read_only():
    script = SCRIPT.read_text(encoding="utf-8")
    status = re.search(r"status\(\).*?\nverify\(", script, re.S).group(0)
    verify = re.search(r"verify\(\).*?\n\ncmd=", script, re.S).group(0)
    mutating = [" helm install", " helm upgrade", "kubectl apply", "kubectl create", "kubectl patch", "kubectl delete"]
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


def test_justfile_exposes_observability_recipes():
    text = JUSTFILE.read_text(encoding="utf-8")
    for recipe in (
        "observability-render",
        "observability-install",
        "observability-upgrade",
        "observability-status",
        "observability-verify",
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
    staging = (ROOT / "clusters" / "staging" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    development = (ROOT / "clusters" / "dev" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    production = (ROOT / "clusters" / "prod" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
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
    attempts="1",
    interval="1",
):
    """Run the lifecycle against deterministic command stubs and return its audit log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    audit = tmp_path / "audit"
    responses = tmp_path / "target-responses"
    if target_responses is not None:
        responses.write_text("\n".join(target_responses) + "\n", encoding="utf-8")
    (bin_dir / "helm").write_text(
        """#!/bin/sh
echo "helm $*" >> "$AUDIT"
case "$*" in
  *"repo add"*|*"repo update"*) exit 0 ;;
  *template*) [ "$HELM_MODE" != render-fail ] || exit 31; echo rendered; exit 0 ;;
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
  *"get daemonset kube-prometheus-stack-prometheus-node-exporter"*) [ "$KUBECTL_MODE" = two-nodes ] && echo '2 2' || echo '3 3' ;;
  *"get pvc -o json"*) printf '%s\n' '{"items":[{"metadata":{"name":"generated-pvc","labels":{"app.kubernetes.io/name":"prometheus"}},"spec":{"storageClassName":"local-path"},"status":{"phase":"Bound"}}]}' ;;
  *"get prometheus kube-prometheus-stack-prometheus"*) echo 1 ;;
  *"get alertmanager kube-prometheus-stack-alertmanager"*) echo 1 ;;
  *"get ingress "*) exit 0 ;;
  *"get svc kube-prometheus-stack-grafana"*) echo 30300 ;;
  *"get servicemonitor dspace"*"metadata.labels.release"*) [ "$KUBECTL_MODE" = wrong-release ] && echo wrong || echo kube-prometheus-stack ;;
  *"get servicemonitor dspace"*"bearerTokenSecret.name"*) [ "$KUBECTL_MODE" != missing-secret-ref ] && echo dspace-token ;;
  *"get secret dspace-token -o name"*) [ "$KUBECTL_MODE" != missing-secret ] || exit 44; echo secret/dspace-token ;;
  *"get --raw "*)
    [ "$KUBECTL_MODE" != query-fail ] || exit 45
    if [ -f "$TARGET_RESPONSES" ]; then
      count=0
      [ ! -f "$TARGET_COUNT" ] || count=$(cat "$TARGET_COUNT")
      count=$((count + 1)); echo "$count" > "$TARGET_COUNT"
      sed -n "${count}p" "$TARGET_RESPONSES"
    elif [ "$KUBECTL_MODE" = mixed-targets ]; then
      printf '%s\n' '{"status":"success","data":{"activeTargets":[{"labels":{"app":"dspace","namespace":"dspace"},"health":"up"},{"labels":{"app":"dspace","namespace":"dspace"},"health":"down"}]}}'
    else
      [ "$KUBECTL_MODE" = unhealthy ] && health=down || health=up
      printf '{"status":"success","data":{"activeTargets":[{"labels":{"app":"dspace","namespace":"dspace"},"health":"%s"}]}}\n' "$health"
    fi
    ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    (bin_dir / "sleep").write_text(
        '#!/bin/sh\necho "sleep $*" >> "$AUDIT"\n', encoding="utf-8"
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
        "TARGET_RESPONSES": str(responses),
        "TARGET_COUNT": str(tmp_path / "target-count"),
        "SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_ATTEMPTS": attempts,
        "SUGARKUBE_OBSERVABILITY_TARGET_HEALTH_INTERVAL_SECONDS": interval,
    }
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
    unsupported = subprocess.run(["bash", str(SCRIPT), "install", "env=prod"], capture_output=True, text=True, check=False)
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


def test_verify_exact_three_nodes_secret_reference_and_target_health(tmp_path):
    healthy, audit = run_helper(tmp_path / "healthy", "verify")
    assert healthy.returncode == 0 and "get --raw /api/v1/namespaces/monitoring/services/http:" in audit
    for mode in (
        "two-nodes",
        "wrong-release",
        "missing-secret-ref",
        "missing-secret",
        "query-fail",
        "unhealthy",
        "mixed-targets",
    ):
        result, _ = run_helper(tmp_path / mode, "verify", kubectl_mode=mode)
        assert result.returncode != 0, mode


def target_payload(*targets, status="success"):
    return json.dumps({"status": status, "data": {"activeTargets": list(targets)}})


def dspace_target(health, *, pod="dspace-0", instance="10.0.0.1:8080", marker=None):
    target = {
        "labels": {
            "app": "dspace",
            "namespace": "dspace",
            "pod": pod,
            "instance": instance,
        },
        "health": health,
        "lastError": "connection refused",
        "lastScrape": "2026-07-25T12:00:00Z",
    }
    if marker is not None:
        target["authorization"] = marker
        target["labels"]["secretValue"] = marker
    return target


def api_calls(audit):
    return audit.count("kubectl get --raw ")


def test_target_health_succeeds_on_first_observation_for_one_or_many_targets(tmp_path):
    one, audit = run_helper(
        tmp_path / "one", "verify", target_responses=[target_payload(dspace_target("up"))]
    )
    assert one.returncode == 0
    assert api_calls(audit) == 1 and "sleep " not in audit

    many, audit = run_helper(
        tmp_path / "many",
        "verify",
        target_responses=[target_payload(dspace_target("up"), dspace_target("up", pod="dspace-1"))],
    )
    assert many.returncode == 0
    assert api_calls(audit) == 1 and "sleep " not in audit


def test_target_health_retries_empty_unknown_and_mixed_then_succeeds(tmp_path):
    healthy = target_payload(dspace_target("up"), dspace_target("up", pod="dspace-1"))
    cases = {
        "empty": [target_payload(), healthy],
        "unknown": [target_payload(dspace_target("unknown")), healthy],
        "mixed": [
            target_payload(dspace_target("up"), dspace_target("down", pod="dspace-1")),
            healthy,
        ],
    }
    for name, responses in cases.items():
        result, audit = run_helper(
            tmp_path / name, "verify", target_responses=responses, attempts="2", interval="7"
        )
        assert result.returncode == 0, name
        assert api_calls(audit) == 2
        assert audit.count("sleep 7") == 1
        assert "attempt 1/2" in result.stderr


def test_target_health_timeout_is_bounded_and_empty_never_passes(tmp_path):
    for name, response in {
        "empty": target_payload(),
        "down": target_payload(dspace_target("down")),
        "mixed": target_payload(dspace_target("up"), dspace_target("down", pod="dspace-1")),
    }.items():
        result, audit = run_helper(
            tmp_path / name,
            "verify",
            target_responses=[response, response, response],
            attempts="3",
            interval="4",
        )
        assert result.returncode != 0, name
        assert api_calls(audit) == 3
        assert audit.count("sleep 4") == 2
        assert "after 3 attempts" in result.stderr


def test_target_health_hard_failures_do_not_retry(tmp_path):
    cases = {
        "malformed": ["not-json"],
        "api-error": [target_payload(status="error")],
        "bad-structure": [json.dumps({"status": "success", "data": {}})],
    }
    for name, responses in cases.items():
        result, audit = run_helper(
            tmp_path / name, "verify", target_responses=responses, attempts="3"
        )
        assert result.returncode != 0, name
        assert api_calls(audit) == 1
        assert "sleep " not in audit

    result, audit = run_helper(
        tmp_path / "transport", "verify", kubectl_mode="query-fail", attempts="3"
    )
    assert result.returncode != 0
    assert api_calls(audit) == 1 and "sleep " not in audit


def test_invalid_target_retry_configuration_fails_before_polling(tmp_path):
    for attempts, interval in (("0", "1"), ("two", "1"), ("1", "0"), ("1", "1.5")):
        result, audit = run_helper(
            tmp_path / f"case-{attempts}-{interval}",
            "verify",
            attempts=attempts,
            interval=interval,
        )
        assert result.returncode != 0
        assert api_calls(audit) == 0


def test_final_target_diagnostics_are_useful_and_privacy_safe(tmp_path):
    sensitive = "do-not-print-this-secret"
    response = target_payload(dspace_target("down", marker=sensitive))
    result, audit = run_helper(
        tmp_path, "verify", target_responses=[response, response], attempts="2"
    )
    assert result.returncode != 0 and api_calls(audit) == 2
    for expected in ("dspace-0", "10.0.0.1:8080", "down", "connection refused", "lastScrape"):
        assert expected in result.stderr
    assert sensitive not in result.stdout + result.stderr
    assert "authorization" not in result.stdout + result.stderr
