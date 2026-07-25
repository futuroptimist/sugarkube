import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "clusters/staging/observability/probes/public-apps.yaml"
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"


def yaml_docs(path):
    result = subprocess.run(["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])).compact)", str(path)], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def yaml_one(path):
    return yaml_docs(path)[0]


def test_chart_values_are_pinned_private_and_bounded():
    assert (ROOT / "platform/observability/helm/prometheus-blackbox-exporter.version").read_text().strip() == "11.15.1"
    values = yaml_one(VALUES)
    assert values["fullnameOverride"] == "prometheus-blackbox-exporter"
    assert values["replicaCount"] == 1
    assert values["service"]["type"] == "ClusterIP"
    assert values["service"]["nodePort"] is None
    assert values["ingress"]["enabled"] is False
    assert values["serviceMonitor"]["enabled"] is True
    assert values["serviceMonitor"]["additionalLabels"]["release"] == "kube-prometheus-stack"
    modules = values["config"]["modules"]
    assert set(modules) == {"https_2xx", "json_health_2xx", "static_content_2xx"}
    for module in modules.values():
        assert module["timeout"] == "10s"
        assert module["http"]["fail_if_not_ssl"] is True
        assert module["http"]["tls_config"]["insecure_skip_verify"] is False
    assert modules["json_health_2xx"]["http"]["body_size_limit"] == "1MiB"
    assert modules["static_content_2xx"]["http"]["body_size_limit"] == "1MiB"
    text = VALUES.read_text()
    assert "pass" + "word" not in text.lower()
    assert "kind: Secret" not in text
    assert "networkPolicy" not in text


def test_exact_staging_probe_matrix():
    expected = {
        ("dspace", "root", "https://staging.democratized.space/"),
        ("dspace", "config", "https://staging.democratized.space/config.json"),
        ("dspace", "healthz", "https://staging.democratized.space/healthz"),
        ("dspace", "livez", "https://staging.democratized.space/livez"),
        ("tokenplace", "root", "https://staging.token.place/"),
        ("tokenplace", "healthz", "https://staging.token.place/healthz"),
        ("tokenplace", "livez", "https://staging.token.place/livez"),
        ("tokenplace", "metadata", "https://staging.token.place/api/v1/meta"),
        ("danielsmith", "root", "https://staging.danielsmith.io/"),
        ("danielsmith", "healthz", "https://staging.danielsmith.io/healthz"),
        ("danielsmith", "livez", "https://staging.danielsmith.io/livez"),
        ("jobbot3000", "root", "https://staging.jobbot3000.tech/"),
        ("jobbot3000", "healthz", "https://staging.jobbot3000.tech/healthz"),
        ("jobbot3000", "livez", "https://staging.jobbot3000.tech/livez"),
        ("jobbot3000", "tracker", "https://staging.jobbot3000.tech/tracker"),
        ("jobbot3000", "manifest", "https://staging.jobbot3000.tech/manifest.webmanifest"),
    }
    docs = yaml_docs(PROBES)
    assert len(docs) == 16
    actual = set()
    for probe in docs:
        labels = probe["metadata"]["labels"]
        target_labels = probe["spec"]["targets"]["staticConfig"]["labels"]
        assert probe["kind"] == "Probe"
        assert labels["release"] == "kube-prometheus-stack"
        assert labels["environment"] == "staging"
        assert {k: target_labels[k] for k in ("app", "environment", "route", "criticality")} == {k: labels[k] for k in ("app", "environment", "route", "criticality")}
        target = probe["spec"]["targets"]["staticConfig"]["static"]
        assert len(target) == 1
        actual.add((labels["app"], labels["route"], target[0]))
    assert actual == expected
    assert "environment: prod" not in PROBES.read_text()


def test_legacy_resources_are_outside_active_graphs():
    platform = (ROOT / "platform/observability/kustomization.yaml").read_text()
    assert "prometheus-blackbox-exporter.yaml" not in platform
    for env in ("dev", "staging", "prod"):
        overlay = (ROOT / f"clusters/{env}/kustomization.yaml").read_text()
        assert "monitoring/probes" not in overlay
    assert "LEGACY/FUTURE ONLY" in (ROOT / "platform/observability/prometheus-blackbox-exporter.yaml").read_text()
    assert "LEGACY/FUTURE ONLY" in (ROOT / "monitoring/probes/public-apps.yaml").read_text()
