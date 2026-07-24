from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = REPO / "platform/observability/helm/kube-prometheus-stack.version"
COMMON = REPO / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING = REPO / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
SCRIPT = REPO / "scripts/observability_helm.sh"
JUSTFILE = REPO / "justfile"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chart_version_is_exact_live_staging_pin() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "87.19.0"


def test_staging_values_match_live_prometheus_baseline() -> None:
    content = text(COMMON)
    for snippet in (
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
    ):
        assert snippet in content
    assert "longhorn" not in content.lower()


def test_grafana_uses_existing_secret_and_lan_only_nodeport() -> None:
    content = text(COMMON)
    for snippet in (
        "existingSecret: grafana-admin-credentials",
        "userKey: admin-user",
        "passwordKey: admin-password",
        "persistence:\n    enabled: false",
        "ingress:\n    enabled: false",
        "type: NodePort",
        "nodePort: 30300",
    ):
        assert snippet in content


def test_alertmanager_null_receiver_is_string_and_single_replica() -> None:
    content = text(COMMON)
    assert "alertmanagerSpec:\n    replicas: 1" in content
    assert 'receiver: "null"' in content
    assert '- name: "null"' in content
    assert "receiver: null\n" not in content
    assert "null-receiver" not in content


def test_unsupported_k3s_monitors_are_disabled() -> None:
    content = text(COMMON)
    for key in ("kubeEtcd", "kubeControllerManager", "kubeScheduler", "kubeProxy"):
        assert f"{key}:\n  enabled: false" in content


def test_discovery_contract_uses_release_label() -> None:
    content = text(COMMON)
    assert "serviceMonitorSelector:\n      matchLabels:\n        release: kube-prometheus-stack" in content
    assert "probeSelector:\n      matchLabels:\n        release: kube-prometheus-stack" in content


def test_no_production_observability_values_are_introduced() -> None:
    assert not (REPO / "clusters/prod/observability/kube-prometheus-stack.values.yaml").exists()
    assert "Production observability values are intentionally not codified" in STAGING.read_text(encoding="utf-8")


def test_lifecycle_uses_pinned_version_and_complete_ordered_values() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'VERSION_FILE="platform/observability/helm/kube-prometheus-stack.version"' in text
    assert 'COMMON_VALUES="platform/observability/helm/kube-prometheus-stack.values.common.yaml"' in text
    assert 'STAGING_VALUES="clusters/staging/observability/kube-prometheus-stack.values.yaml"' in text
    assert '[ "${VERSION}" = "87.19.0" ]' in text
    assert 'CHART="prometheus-community/kube-prometheus-stack"' in text
    assert '-f "${VALUES[0]}" -f "${VALUES[1]}"' in text
    assert "--reuse-values" not in text


def test_install_upgrade_have_distinct_guards_and_render_before_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Helm release ${RELEASE} already exists" in text
    assert "Helm release ${RELEASE} does not exist" in text
    assert text.index("render_chart >/dev/null") < text.index("helm install")
    assert text.index("render_chart >/dev/null") < text.index("helm upgrade")
    assert "--wait" in text
    assert "--timeout" in text


def test_unsupported_env_and_context_mismatch_fail_before_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "production observability is not yet codified" in text
    assert 'if [ "${ENV_NAME}" != "staging" ]' in text
    assert "assert_staging_context" in text
    assert text.index("assert_staging_context") < text.index("helm install")
    assert text.index("assert_staging_context") < text.index("helm upgrade")


def test_status_and_verify_are_read_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    status = text.split('status)')[1].split('verify)')[0]
    verify = text.split('verify)')[1].split('*) usage')[0]
    forbidden = ("helm install", "helm upgrade", "kubectl apply", "kubectl create", "kubectl delete", "rollout restart")
    for body in (status, verify):
        for token in forbidden:
            assert token not in body


def test_legacy_flux_longhorn_files_not_referenced_by_new_lifecycle() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "platform/observability/kube-prometheus-stack.yaml" not in text
    assert "platform/observability/kube-prometheus-stack-values.yaml" not in text
    assert "clusters/staging/patches/kube-prometheus-stack-values.yaml" not in text
    assert "clusters/prod/patches/kube-prometheus-stack-values.yaml" not in text


def test_no_public_ingress_cloudflare_or_plaintext_secret_values() -> None:
    combined = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (COMMON, STAGING, SCRIPT, REPO / "docs/operations/observability-helm.md")
    )
    assert "cloudflare" not in COMMON.read_text(encoding="utf-8").lower()
    assert "IngressRoute" not in combined
    assert "apiVersion: networking.k8s.io" not in COMMON.read_text(encoding="utf-8")
    assert "admin" + chr(80) + "ass" + "word" not in combined
    assert "prometheus.service.type: NodePort" not in combined
    assert "alertmanager.service.type: NodePort" not in combined


def test_justfile_exposes_concise_observability_recipes() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    for recipe in (
        "observability-render env=''",
        "observability-install env=''",
        "observability-upgrade env=''",
        "observability-status env=''",
        "observability-verify env=''",
    ):
        assert recipe in text
    assert "scripts/observability_helm.sh install" in text
