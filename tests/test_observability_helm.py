import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.version"
COMMON = ROOT / "platform" / "observability" / "helm" / "kube-prometheus-stack.values.common.yaml"
STAGING = ROOT / "clusters" / "staging" / "observability" / "kube-prometheus-stack.values.yaml"
SCRIPT = ROOT / "scripts" / "observability_helm.sh"
JUSTFILE = ROOT / "justfile"
LEGACY = [
    ROOT / "platform" / "observability" / "kube-prometheus-stack.yaml",
    ROOT / "platform" / "observability" / "kube-prometheus-stack-values.yaml",
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
    assert "if release_exists" in install
    assert "already exists" in install
    assert "render_to" in upgrade and "helm upgrade" in upgrade
    assert upgrade.index("render_to") < upgrade.index("helm upgrade")
    assert "if ! release_exists" in upgrade
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
    assert "release=kube-prometheus-stack" in verify
    assert "value intentionally not printed" in verify
    assert '--timeout="${TIMEOUT}"' in verify
    assert "desiredNumberScheduled" in verify and "numberReady" in verify
    assert "|| true" not in verify
    assert 'target.get("health") != "up" for target in dspace' in verify


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
    production = (ROOT / "clusters" / "prod" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    assert "kube-prometheus-stack.yaml" not in platform
    assert "kube-prometheus-stack-values.yaml" not in platform
    assert "patches/kube-prometheus-stack-values.yaml" not in staging
    assert "patches/kube-prometheus-stack-values.yaml" not in production
