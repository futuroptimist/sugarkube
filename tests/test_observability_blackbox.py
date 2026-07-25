import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUES = ROOT / "clusters/staging/observability/prometheus-blackbox-exporter.values.yaml"
PROBES = ROOT / "clusters/staging/observability/probes/public-apps.yaml"
SCRIPT = ROOT / "scripts/observability_blackbox.sh"


def yaml_documents(path):
    result = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])).compact)", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_pin_values_and_bounded_modules_are_exact():
    assert (ROOT / "platform/observability/helm/prometheus-blackbox-exporter.version").read_text().strip() == "11.15.1"
    values = yaml_documents(VALUES)[0]
    assert values["replicas"] == 1
    assert values["fullnameOverride"] == "prometheus-blackbox-exporter"
    assert values["service"]["type"] == "ClusterIP"
    assert values["ingress"]["enabled"] is False
    assert values["serviceMonitor"]["defaults"]["labels"]["release"] == "kube-prometheus-stack"
    assert set(values["config"]["modules"]) == {"https_2xx", "json_health_2xx", "static_content_2xx"}
    for module in values["config"]["modules"].values():
        assert module["timeout"] == "10s"
        assert module["http"]["fail_if_not_ssl"] is True
        assert module["http"]["tls_config"]["insecure_skip_verify"] is False
    assert values["config"]["modules"]["json_health_2xx"]["http"]["body_size_limit"] == "1MiB"
    assert values["config"]["modules"]["static_content_2xx"]["http"]["body_size_limit"] == "1MiB"
    text = VALUES.read_text()
    assert "secret" not in text.lower()
    assert "networkPolicy" not in text


def test_canonical_staging_probe_matrix_is_exact():
    docs = yaml_documents(PROBES)
    expected = {
        "dspace": {"root": "/", "config": "/config.json", "healthz": "/healthz", "livez": "/livez"},
        "tokenplace": {"root": "/", "healthz": "/healthz", "livez": "/livez", "metadata": "/api/v1/meta"},
        "danielsmith": {"root": "/", "healthz": "/healthz", "livez": "/livez"},
        "jobbot3000": {"root": "/", "healthz": "/healthz", "livez": "/livez", "tracker": "/tracker", "manifest": "/manifest.webmanifest"},
    }
    origins = {"dspace": "https://staging.democratized.space", "tokenplace": "https://staging.token.place", "danielsmith": "https://staging.danielsmith.io", "jobbot3000": "https://staging.jobbot3000.tech"}
    actual = set()
    assert len(docs) == 16
    for probe in docs:
        labels = probe["metadata"]["labels"]
        target_labels = probe["spec"]["targets"]["staticConfig"]["labels"]
        assert labels["release"] == "kube-prometheus-stack"
        assert labels["environment"] == "staging"
        assert all(target_labels[k] == labels[k] for k in ("app", "environment", "route", "criticality"))
        app, route = labels["app"], labels["route"]
        actual.add((app, route, probe["spec"]["targets"]["staticConfig"]["static"][0]))
    wanted = {(app, route, origins[app] + path) for app, routes in expected.items() for route, path in routes.items()}
    # Root URLs canonically retain their trailing slash.
    assert actual == wanted
    assert "environment: prod" not in PROBES.read_text()


def test_lifecycle_is_pinned_guarded_and_has_no_flux_or_reuse_values():
    text = SCRIPT.read_text()
    assert "https://prometheus-community.github.io/helm-charts" in text
    assert '--version "$(version)"' in text
    assert "--reuse-values" not in text
    assert "flux" not in text.lower()
    assert "kubectl apply" in text
    assert text.index('helm "${operation}"') < text.index('kubectl apply')
    assert "cluster_identity.py" in text and "sugar-staging" in text
    assert "uninstall" not in text


def test_missing_and_production_environments_fail_before_tool_or_cluster_access():
    for env in ("", "prod", "production", "dev", "unknown"):
        result = subprocess.run([str(SCRIPT), "install", env], text=True, capture_output=True)
        assert result.returncode == 2
        assert "kubectl" not in result.stdout
        assert "helm repo" not in result.stdout
