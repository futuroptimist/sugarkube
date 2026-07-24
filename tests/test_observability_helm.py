from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "platform/observability/helm/kube-prometheus-stack.version"
COMMON = ROOT / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts/observability_helm.sh"
JUSTFILE = ROOT / "justfile"


def common() -> str:
    return COMMON.read_text(encoding="utf-8")


def staging() -> str:
    return STAGING.read_text(encoding="utf-8")


def test_chart_version_is_exact_pin() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "87.19.0"


def test_staging_prometheus_baseline_and_storage() -> None:
    text = common() + "\n" + staging()
    for snippet in [
        "replicas: 1",
        "retention: 7d",
        "retentionSize: 15GB",
        "enableAdminAPI: false",
        "cpu: 200m",
        "memory: 512Mi",
        "memory: 2Gi",
        "cluster: sugarkube-int",
        "storageClassName: local-path",
        "- ReadWriteOnce",
        "storage: 20Gi",
    ]:
        assert snippet in text
    assert "longhorn" not in staging().lower()


def test_grafana_alertmanager_and_k3s_monitor_values() -> None:
    text = common()
    for snippet in [
        "existingSecret: grafana-admin-credentials",
        "userKey: admin-user",
        "passwordKey: admin-password",
        "persistence:\n    enabled: false",
        "ingress:\n    enabled: false",
        "type: NodePort",
        "nodePort: 30300",
        "alertmanagerSpec:\n    replicas: 1",
        'receiver: "null"',
        '- name: "null"',
        "kubeEtcd:\n  enabled: false",
        "kubeControllerManager:\n  enabled: false",
        "kubeScheduler:\n  enabled: false",
        "kubeProxy:\n  enabled: false",
    ]:
        assert snippet in text
    assert "receiver: null\n" not in text
    assert "null-receiver" not in text


def test_service_discovery_contract_and_clusterip_admin_endpoints() -> None:
    text = common()
    assert "serviceMonitorSelector:\n      matchLabels:\n        release: kube-prometheus-stack" in text
    assert "probeSelector:\n      matchLabels:\n        release: kube-prometheus-stack" in text
    assert "prometheus:\n  service:\n    type: ClusterIP" in text
    assert "alertmanager:\n  service:\n    type: ClusterIP" in text


def test_no_production_values_introduced_for_new_lifecycle() -> None:
    assert not (ROOT / "clusters/prod/observability/kube-prometheus-stack.values.yaml").exists()


def test_lifecycle_uses_pinned_version_complete_values_and_no_reuse_values() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'CHART="prometheus-community/kube-prometheus-stack"' in script
    assert "VERSION_FILE=" in script
    assert 'COMMON_VALUES="${ROOT}/platform/observability/helm/kube-prometheus-stack.values.common.yaml"' in script
    assert 'STAGING_VALUES="${ROOT}/clusters/staging/observability/kube-prometheus-stack.values.yaml"' in script
    assert '--version "$(version)" -f "$COMMON_VALUES" -f "$STAGING_VALUES"' in script
    assert "--reuse-values" not in script
    assert "render_to_temp \"$tmp\"; helm install" in script
    assert "render_to_temp \"$tmp\"; helm upgrade" in script


def test_install_and_upgrade_have_distinct_release_guards() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "if release_exists; then" in script
    assert "already exists" in script
    assert "if ! release_exists; then" in script
    assert "does not exist" in script


@pytest.mark.parametrize("bad_env", ["prod", "production", "dev", "", "qa"])
def test_unsupported_envs_fail_before_mutation(bad_env: str) -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "normalize_env" in script
    assert "Production observability is not yet codified" in script
    mutation_index = min(script.index("helm install"), script.index("helm upgrade"))
    assert script.index("normalize_env") < mutation_index
    assert "prod|production)" in script


def test_context_mismatch_guard_before_mutation() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "cluster_identity.py\" assert" in script
    assert script.index("assert_context; summary") < script.index("helm install")
    assert script.index("assert_context; summary", script.index("cmd_upgrade")) < script.index("helm upgrade")


def test_status_and_verify_are_read_only() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    status = script[script.index("cmd_status") : script.index("ready(){")]
    verify = script[script.index("cmd_verify") :]
    forbidden = ["helm install", "helm upgrade", "kubectl apply", "kubectl create", "kubectl delete", "rollout restart"]
    for section in (status, verify):
        for command in forbidden:
            assert command not in section


def test_just_recipes_reference_only_new_lifecycle_not_legacy_flux_longhorn() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    block = justfile[justfile.index("observability-render") :]
    assert "scripts/observability_helm.sh" in block
    assert "kube-prometheus-stack-values.yaml" not in block
    assert "HelmRelease" not in block
    assert "longhorn" not in block.lower()


def test_no_public_ingress_cloudflare_plaintext_secret_or_embedded_values() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in [COMMON, STAGING, SCRIPT]
    )
    assert "cloudflare" not in combined.lower()
    assert "ingress:\n    enabled: false" in common()
    assert "kind: Secret" not in combined
    assert "admin-password:" not in combined
    assert "password:" not in combined.replace("passwordKey:", "")
