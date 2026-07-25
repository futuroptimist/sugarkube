import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
PROBES = ROOT / "clusters/staging/observability/probes/public-apps.yaml"
POLICY = (
    ROOT / "clusters/staging/observability/network-policies/prometheus-to-blackbox-exporter.yaml"
)
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
    assert value["replicas"] == 1 and value["service"]["type"] == "ClusterIP"
    assert value["ingress"]["enabled"] is False and value["networkPolicy"]["enabled"] is False
    assert value["serviceMonitor"]["enabled"] is False
    assert value["serviceMonitor"]["selfMonitor"]["enabled"] is True
    assert value["serviceMonitor"]["selfMonitor"]["labels"]["release"] == "kube-prometheus-stack"
    assert value["secretConfig"] is False
    assert all(
        value[key] == []
        for key in (
            "extraConfigmapMounts",
            "extraSecretMounts",
            "extraVolumes",
            "extraVolumeMounts",
        )
    )
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
    assert "observability/probes" not in (ROOT / "clusters/prod/kustomization.yaml").read_text()
    assert (
        "LEGACY/FUTURE ONLY"
        in (ROOT / "platform/observability/prometheus-blackbox-exporter.yaml").read_text()
    )
    assert "LEGACY/FUTURE ONLY" in (ROOT / "monitoring/probes/public-apps.yaml").read_text()


def test_lifecycle_network_policy_is_exact_and_chart_render_backed():
    policy = yaml(POLICY)[0]
    subprocess.run(
        [
            "helm",
            "repo",
            "add",
            "prometheus-community",
            "https://prometheus-community.github.io/helm-charts",
            "--force-update",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    base = subprocess.run(
        [
            "helm",
            "template",
            "kube-prometheus-stack",
            "prometheus-community/kube-prometheus-stack",
            "--namespace",
            "monitoring",
            "--version",
            (ROOT / "platform/observability/helm/kube-prometheus-stack.version")
            .read_text()
            .strip(),
            "-f",
            str(ROOT / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"),
            "-f",
            str(ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    exporter = subprocess.run(
        [
            "helm",
            "template",
            "prometheus-blackbox-exporter",
            "prometheus-community/prometheus-blackbox-exporter",
            "--namespace",
            "monitoring",
            "--version",
            (ROOT / "platform/observability/helm/prometheus-blackbox-exporter.version")
            .read_text()
            .strip(),
            "-f",
            str(VALUES),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    def load_stream(text):
        result = subprocess.run(
            ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(STDIN.read))"],
            input=text,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    prometheus = [
        doc for doc in load_stream(base.stdout) if doc and doc.get("kind") == "Prometheus"
    ]
    deployments = [
        doc
        for doc in load_stream(exporter.stdout)
        if doc
        and doc.get("kind") == "Deployment"
        and doc["metadata"]["name"] == "prometheus-blackbox-exporter"
    ]
    assert len(prometheus) == len(deployments) == 1
    source = {
        "app.kubernetes.io/name": "prometheus",
        "operator.prometheus.io/name": prometheus[0]["metadata"]["name"],
    }
    rendered_labels = deployments[0]["spec"]["template"]["metadata"]["labels"]
    destination = {
        key: rendered_labels[key]
        for key in ("app.kubernetes.io/instance", "app.kubernetes.io/name")
    }
    assert policy == {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": "allow-kube-prometheus-stack-to-blackbox-exporter",
            "namespace": "monitoring",
        },
        "spec": {
            "podSelector": {"matchLabels": source},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [{"podSelector": {"matchLabels": destination}}],
                    "ports": [{"protocol": "TCP", "port": 9115}],
                }
            ],
        },
    }
    assert (POLICY.parent / "kustomization.yaml").read_text().count(POLICY.name) == 1
    for graph in [
        ROOT / "platform/networking/kustomization.yaml",
        *ROOT.glob("clusters/*/kustomization.yaml"),
    ]:
        assert "observability/network-policies" not in graph.read_text()
