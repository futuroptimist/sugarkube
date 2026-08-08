import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path, *, all_documents: bool = False):
    expression = (
        "YAML.load_stream(File.read(ARGV[0]))" if all_documents else "YAML.load_file(ARGV[0])"
    )
    result = subprocess.run(
        ["ruby", "-rjson", "-ryaml", "-e", f"puts JSON.generate({expression})", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_staging_metrics_resources_are_release_scoped() -> None:
    base = ROOT / "clusters/staging/cloudflare-tunnel"
    service = load_yaml(base / "service.yaml")
    monitor = load_yaml(base / "servicemonitor.yaml")
    budget = load_yaml(base / "pdb.yaml")
    labels = {
        "app.kubernetes.io/name": "cloudflare-tunnel",
        "app.kubernetes.io/instance": "cloudflare-tunnel",
    }
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["selector"] == labels
    assert service["spec"]["ports"] == [{"name": "metrics", "port": 2000, "targetPort": 2000}]
    assert monitor["metadata"]["namespace"] == "cloudflare"
    assert monitor["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    assert monitor["spec"]["selector"]["matchLabels"] == labels
    assert monitor["spec"]["endpoints"][0] == {
        "port": "metrics",
        "path": "/metrics",
        "interval": "30s",
        "scrapeTimeout": "10s",
    }
    assert budget["spec"]["minAvailable"] == 1
    assert budget["spec"]["selector"]["matchLabels"] == labels


def test_rules_handle_absence_and_use_bounded_for_durations() -> None:
    values = load_yaml(ROOT / "clusters/staging/observability/kube-prometheus-stack.values.yaml")
    rules = values["additionalPrometheusRulesMap"]["cloudflare-tunnel"]["groups"][0]["rules"]
    by_name = {rule["alert"]: rule for rule in rules}
    assert set(by_name) == {
        "CloudflareTunnelNoHealthyConnections",
        "CloudflareTunnelConnectionsDegraded",
        "CloudflareTunnelMetricsTargetsDown",
    }
    assert "or vector(0)" in by_name["CloudflareTunnelNoHealthyConnections"]["expr"]
    assert (
        "cloudflared_tunnel_ha_connections"
        in by_name["CloudflareTunnelConnectionsDegraded"]["expr"]
    )
    assert "up{" in by_name["CloudflareTunnelMetricsTargetsDown"]["expr"]
    assert {rule["for"] for rule in rules} == {"5m", "10m"}
    routes = values["alertmanager"]["config"]["route"]["routes"]
    tunnel_route = next(
        route for route in routes if "CloudflareTunnelNoHealthyConnections" in route["matchers"][0]
    )
    assert tunnel_route["receiver"] == "pagerduty-dspace"
    assert tunnel_route["matchers"][-1] == 'severity="critical"'

    fixture = load_yaml(ROOT / "tests/prometheus/cloudflare-tunnel-rules.yaml")
    fixture_rules = fixture["groups"][0]["rules"]
    fixture_by_name = {rule["alert"]: rule for rule in fixture_rules}
    assert {name: (rule["expr"], rule["for"]) for name, rule in by_name.items()} == {
        name: (rule["expr"], rule["for"]) for name, rule in fixture_by_name.items()
    }
