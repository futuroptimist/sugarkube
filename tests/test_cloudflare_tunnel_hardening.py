from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def docs(path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "docs=[]; YAML.load_stream(File.read(ARGV[0])) { |d| docs << d }; puts JSON.generate(docs)",
            str(ROOT / path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_values_preserve_remote_managed_ha_contract():
    values = docs("config/cloudflare-tunnel/values.yaml")[0]
    assert values["replicaCount"] == 2
    assert values["image"] == {
        "repository": "cloudflare/cloudflared",
        "tag": "2026.7.3",
        "pullPolicy": "IfNotPresent",
    }
    assert values["cloudflare"]["secretName"] == "tunnel-token"
    assert values["cloudflare"]["ingress"] == []
    anti = values["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert anti[0]["topologyKey"] == "kubernetes.io/hostname"


def test_private_metrics_discovery_and_pdb_contract():
    service, monitor, pdb = docs("config/cloudflare-tunnel/monitoring.yaml")
    selector = {
        "app.kubernetes.io/name": "cloudflare-tunnel",
        "app.kubernetes.io/instance": "cloudflare-tunnel",
    }
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["selector"] == selector
    assert service["spec"]["ports"] == [
        {"name": "metrics", "port": 2000, "targetPort": 2000, "protocol": "TCP"}
    ]
    assert monitor["metadata"]["namespace"] == "cloudflare"
    assert monitor["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    assert monitor["spec"]["selector"]["matchLabels"] == selector
    assert monitor["spec"]["endpoints"] == [
        {"port": "metrics", "path": "/metrics", "interval": "30s", "scrapeTimeout": "10s"}
    ]
    assert pdb["spec"]["minAvailable"] == 1
    assert pdb["spec"]["selector"]["matchLabels"] == selector


def test_verifier_is_read_only_and_secret_safe():
    script = (ROOT / "scripts/verify_cloudflare_tunnel.sh").read_text()
    subprocess.run(["bash", "-n", str(ROOT / "scripts/verify_cloudflare_tunnel.sh")], check=True)
    for mutation in (
        "kubectl apply",
        "kubectl patch",
        "kubectl delete",
        "helm upgrade",
        ".data.token",
    ):
        assert mutation not in script
    assert "sugar-staging" in script
    assert "Secret values were not read" in script
