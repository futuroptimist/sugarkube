import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
PROBES = ROOT / "clusters/staging/observability/probes/public-apps.yaml"
PROD_PROBES = ROOT / "clusters/prod/observability/probes/public-apps.yaml"
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
    (
        "jobbot3000",
        "manifest",
        "https://staging.jobbot3000.tech/manifest.webmanifest",
        "static_content_2xx",
    ),
}


def yaml(path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_pinned_chart_values_are_private_and_bounded():
    value = yaml(VALUES)[0]
    assert (
        ROOT / "platform/observability/helm/prometheus-blackbox-exporter.version"
    ).read_text().strip() == "11.15.1"
    assert value["fullnameOverride"] == "prometheus-blackbox-exporter"
    assert value["replicaCount"] == 1 and value["service"]["type"] == "ClusterIP"
    assert value["ingress"]["enabled"] is False and value["networkPolicy"]["enabled"] is False
    assert value["serviceMonitor"]["defaults"]["labels"]["release"] == "kube-prometheus-stack"
    modules = value["config"]["modules"]
    assert set(modules) == {"https_2xx", "json_health_2xx", "static_content_2xx"}
    for module in modules.values():
        assert module["timeout"] == "10s"
        assert module["http"]["fail_if_not_ssl"] is True
        assert module["http"]["tls_config"]["insecure_skip_verify"] is False
    assert modules["json_health_2xx"]["http"]["body_size_limit"] == "1MiB"
    assert modules["static_content_2xx"]["http"]["body_size_limit"] == "1MiB"


def test_staging_probe_matrix_is_exact():
    docs = yaml(PROBES)
    assert len(docs) == 16
    actual = set()
    for doc in docs:
        labels = doc["metadata"]["labels"]
        target_labels = doc["spec"]["targets"]["staticConfig"]["labels"]
        assert labels["release"] == "kube-prometheus-stack" and labels["environment"] == "staging"
        assert all(
            target_labels[k] == labels[k] for k in ("app", "environment", "route", "criticality")
        )
        actual.add(
            (
                labels["app"],
                labels["route"],
                doc["spec"]["targets"]["staticConfig"]["static"][0],
                doc["spec"]["module"],
            )
        )
    assert actual == EXPECTED
    assert "production" not in PROBES.read_text() and "environment: prod" not in PROBES.read_text()


def test_legacy_resources_are_outside_active_graphs():
    platform = (ROOT / "platform/observability/kustomization.yaml").read_text()
    assert "prometheus-blackbox-exporter.yaml" not in platform
    for env in ("dev", "staging", "prod"):
        overlay = (ROOT / f"clusters/{env}/kustomization.yaml").read_text()
        assert "monitoring/probes" not in overlay
    assert "observability/probes" in (ROOT / "clusters/prod/kustomization.yaml").read_text()
    prod_docs = yaml(PROD_PROBES)
    assert prod_docs
    assert all(doc["metadata"]["labels"]["environment"] == "prod" for doc in prod_docs)
    assert all("-prod-" in doc["metadata"]["name"] for doc in prod_docs)
    assert (
        "LEGACY/FUTURE ONLY"
        in (ROOT / "platform/observability/prometheus-blackbox-exporter.yaml").read_text()
    )
    assert "LEGACY/FUTURE ONLY" in (ROOT / "monitoring/probes/public-apps.yaml").read_text()


def test_network_policy_allows_prometheus_to_scrape_exporter():
    policies = yaml(ROOT / "platform/networking/platform-allow.yaml")
    policy = next(
        p for p in policies if p["metadata"]["name"] == "allow-prometheus-to-blackbox-exporter"
    )
    assert policy["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "prometheus"
    rule = policy["spec"]["egress"][0]
    assert (
        rule["to"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
        == "prometheus-blackbox-exporter"
    )
    assert rule["ports"] == [{"port": 9115, "protocol": "TCP"}]
