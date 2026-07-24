from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "platform/observability/helm/kube-prometheus-stack.version"
COMMON = ROOT / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"
STAGING = ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts/observability_helm.sh"
JUSTFILE = ROOT / "justfile"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chart_version_is_exact_live_pin() -> None:
    assert VERSION.read_text(encoding="utf-8").strip() == "87.19.0"


def test_staging_prometheus_baseline() -> None:
    body = text(STAGING)
    for needle in (
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
        assert needle in body
    assert "longhorn" not in body.lower()


def test_common_grafana_alertmanager_and_k3s_monitor_values() -> None:
    body = text(COMMON)
    for needle in (
        "existingSecret: grafana-admin-credentials",
        "userKey: admin-user",
        "passwordKey: admin-password",
        "persistence:\n    enabled: false",
        "ingress:\n    enabled: false",
        "type: NodePort",
        "nodePort: 30300",
        "replicas: 1",
        "receiver: \"null\"",
        '- name: "null"',
        "kubeEtcd:\n  enabled: false",
        "kubeControllerManager:\n  enabled: false",
        "kubeScheduler:\n  enabled: false",
        "kubeProxy:\n  enabled: false",
    ):
        assert needle in body
    assert "null-receiver" not in body


def test_discovery_contract_is_preserved() -> None:
    body = text(COMMON)
    for key in ("serviceMonitorSelector", "probeSelector", "podMonitorSelector", "ruleSelector"):
        assert f"{key}:\n      matchLabels:\n        release: kube-prometheus-stack" in body


def test_no_production_observability_values_are_introduced() -> None:
    assert not (ROOT / "clusters/prod/observability").exists()


def test_lifecycle_uses_pinned_version_complete_ordered_values_and_no_reuse_values() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "VERSION_FILE=" in text
    assert "COMMON_VALUES=" in text and "STAGING_VALUES=" in text
    assert "--version \"$(version)\" -f \"$COMMON_VALUES\" -f \"$STAGING_VALUES\"" in text
    assert "--reuse-values" not in text
    assert "helm template" in text
    assert "helm install" in text
    assert "helm upgrade" in text


def test_install_and_upgrade_have_distinct_guards_and_render_first() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "if release_exists; then" in text
    assert "if ! release_exists; then" in text
    install_pos = text.index("helm install")
    upgrade_pos = text.index("helm upgrade")
    render_pos = text.index("render_to \"$tmp\"", text.index("install|upgrade)"))
    assert render_pos < install_pos
    assert render_pos < upgrade_pos


def test_unsupported_env_and_context_mismatch_fail_before_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "production observability is not yet codified" in text
    assert "expected Kubernetes context sugar-staging" in text
    assert text.index("assert_context") < text.index("helm install")
    assert text.index("assert_context") < text.index("helm upgrade")


def test_status_and_verify_paths_are_read_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    status = text.split("  status)", 1)[1].split("    ;;", 1)[0]
    verify = text.split("  verify)", 1)[1].split("    ;;", 1)[0]
    forbidden = re.compile(r"\b(install|upgrade|apply|create|delete|patch|replace|scale|rollout restart)\b")
    assert not forbidden.search(status)
    assert not forbidden.search(verify)


def test_new_lifecycle_does_not_reference_legacy_flux_longhorn_files() -> None:
    text = SCRIPT.read_text(encoding="utf-8") + JUSTFILE.read_text(encoding="utf-8").split("observability-render", 1)[1]
    assert "kube-prometheus-stack-values.yaml" not in text
    assert "HelmRelease" not in text
    assert "longhorn" not in text.lower()


def test_no_public_ingress_cloudflare_or_plaintext_secret_values() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (COMMON, STAGING, SCRIPT))
    assert "cloudflare" not in combined.lower()
    assert "IngressRoute" not in combined
    assert "route53" not in combined.lower()
    assert "pass" + "word:" not in combined.lower()
    assert "admin" + "pass" + "word" not in combined.lower()
