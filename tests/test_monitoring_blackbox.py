import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "clusters/staging/observability/probes/public-apps.yaml"
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
EXPECTED = {
    ("dspace", "root", "https://staging.democratized.space/", "https_2xx"),
    ("dspace", "config", "https://staging.democratized.space/config.json", "static_content_2xx"),
    ("dspace", "healthz", "https://staging.democratized.space/healthz", "json_health_2xx"),
    ("dspace", "livez", "https://staging.democratized.space/livez", "json_health_2xx"),
    ("tokenplace", "root", "https://staging.token.place/", "https_2xx"),
    ("tokenplace", "healthz", "https://staging.token.place/healthz", "json_health_2xx"),
    ("tokenplace", "livez", "https://staging.token.place/livez", "json_health_2xx"),
    ("tokenplace", "metadata", "https://staging.token.place/api/v1/meta", "static_content_2xx"),
    ("danielsmith", "root", "https://staging.danielsmith.io/", "https_2xx"),
    ("danielsmith", "healthz", "https://staging.danielsmith.io/healthz", "json_health_2xx"),
    ("danielsmith", "livez", "https://staging.danielsmith.io/livez", "json_health_2xx"),
    ("jobbot3000", "root", "https://staging.jobbot3000.tech/", "https_2xx"),
    ("jobbot3000", "healthz", "https://staging.jobbot3000.tech/healthz", "json_health_2xx"),
    ("jobbot3000", "livez", "https://staging.jobbot3000.tech/livez", "json_health_2xx"),
    ("jobbot3000", "tracker", "https://staging.jobbot3000.tech/tracker", "static_content_2xx"),
    ("jobbot3000", "manifest", "https://staging.jobbot3000.tech/manifest.webmanifest", "static_content_2xx"),
}

def yaml_docs(path):
    result = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])).compact)", str(path)], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)

def yaml_one(path):
    return yaml_docs(path)[0]

def test_pinned_chart_values_are_internal_and_bounded():
    assert (ROOT / "platform/observability/helm/prometheus-blackbox-exporter.version").read_text().strip() == "11.15.1"
    values = yaml_one(VALUES)
    assert values["fullnameOverride"] == "prometheus-blackbox-exporter"
    assert values["replicaCount"] == 1
    assert values["service"]["type"] == "ClusterIP"
    assert values["ingress"]["enabled"] is False
    assert values["serviceMonitor"]["enabled"] is True
    assert values["serviceMonitor"]["defaults"]["labels"]["release"] == "kube-prometheus-stack"
    assert set(values["config"]["modules"]) == {"https_2xx", "json_health_2xx", "static_content_2xx"}
    for module in values["config"]["modules"].values():
        assert module["timeout"] == "10s"
        assert module["http"]["fail_if_not_ssl"] is True
        assert module["http"]["tls_config"]["insecure_skip_verify"] is False
    assert values["config"]["modules"]["json_health_2xx"]["http"]["body_size_limit"] == "1MiB"
    assert values["config"]["modules"]["static_content_2xx"]["http"]["body_size_limit"] == "1MiB"
    text = VALUES.read_text()
    assert all(word not in text for word in ("NetworkPolicy", "NodePort", "Secret", "persistence"))

def test_exact_staging_probe_matrix_and_labels():
    docs = yaml_docs(PROBES)
    assert len(docs) == 16
    actual = set()
    for probe in docs:
        labels = probe["metadata"]["labels"]
        target_labels = probe["spec"]["targets"]["staticConfig"]["labels"]
        assert probe["kind"] == "Probe"
        assert labels["release"] == "kube-prometheus-stack"
        assert labels["environment"] == "staging"
        assert labels["criticality"] in {"critical", "warning"}
        for key in ("app", "environment", "route", "criticality"):
            assert target_labels[key] == labels[key]
        targets = probe["spec"]["targets"]["staticConfig"]["static"]
        assert len(targets) == 1
        actual.add((labels["app"], labels["route"], targets[0], probe["spec"]["module"]))
    assert actual == EXPECTED
    assert "prod" not in PROBES.read_text()

def test_legacy_resources_are_outside_active_kustomize_graphs():
    platform = (ROOT / "platform/observability/kustomization.yaml").read_text()
    assert "prometheus-blackbox-exporter.yaml" not in platform
    for env in ("dev", "staging", "prod"):
        overlay = (ROOT / f"clusters/{env}/kustomization.yaml").read_text()
        assert "monitoring/probes" not in overlay
    assert (ROOT / "platform/observability/prometheus-blackbox-exporter.yaml").read_text().startswith("# LEGACY/FUTURE ONLY:")
    assert (ROOT / "monitoring/probes/public-apps.yaml").read_text().startswith("# LEGACY/FUTURE ONLY:")
