import json
import os
import subprocess
from pathlib import Path

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


def _pod(name, node, *, ready=True, terminating=False):
    metadata = {"name": name}
    if terminating:
        metadata["deletionTimestamp"] = "2026-08-09T00:00:00Z"
    return {
        "metadata": metadata,
        "spec": {"nodeName": node},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


def _run_verifier(tmp_path, pods):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payloads = tmp_path / "payloads"
    payloads.mkdir()
    (payloads / "pods.json").write_text(
        json.dumps({"apiVersion": "v1", "kind": "PodList", "items": pods})
    )

    deployment = {
        "metadata": {"labels": {"app.kubernetes.io/managed-by": "Helm"}},
        "spec": {
            "replicas": 2,
            "strategy": {"rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
            "template": {
                "spec": {
                    "affinity": {
                        "podAntiAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": [
                                {
                                    "topologyKey": "kubernetes.io/hostname",
                                    "labelSelector": {
                                        "matchLabels": {
                                            "app.kubernetes.io/name": "cloudflare-tunnel",
                                            "app.kubernetes.io/instance": "cloudflare-tunnel",
                                        }
                                    },
                                }
                            ]
                        }
                    },
                    "containers": [
                        {
                            "image": "cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf",
                            "readinessProbe": {"httpGet": {"path": "/ready", "port": 2000}},
                            "env": [
                                {
                                    "name": "TUNNEL_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {"name": "tunnel-token", "key": "token"}
                                    },
                                }
                            ],
                        }
                    ],
                    "volumes": [],
                }
            },
        },
    }
    (payloads / "deployment.json").write_text(json.dumps(deployment))

    helm = bin_dir / "helm"
    helm.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
    )
    helm.chmod(0o755)
    kubectl = bin_dir / "kubectl"
    kubectl.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args == ["config", "current-context"]:
    print("sugar-staging")
elif "deployment" in args:
    print(open(os.environ["PAYLOADS"] + "/deployment.json").read())
elif "pods" in args:
    print(open(os.environ["PAYLOADS"] + "/pods.json").read())
elif "pdb" in args:
    print('{"spec":{"minAvailable":1}}')
elif "service" in args and "cloudflare-tunnel-metrics" in args:
    print('{"spec":{"type":"ClusterIP","selector":{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"},"ports":[{"name":"metrics","port":2000,"protocol":"TCP","targetPort":2000}]}}')
elif "servicemonitor" in args:
    print('{"metadata":{"labels":{"release":"kube-prometheus-stack"}},"spec":{"selector":{"matchLabels":{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"}},"endpoints":[{"path":"/metrics"}]}}')
elif any("rules?type=alert" in arg for arg in args):
    print(json.dumps({"data":{"groups":[{"rules":[{"name": name, "health":"ok"} for name in ["CloudflareTunnelNoHealthyConnections","CloudflareTunnelConnectionsDegraded","CloudflareTunnelMetricsTargetsDown"]]}]}}))
elif any("query?query=" in arg for arg in args):
    query = " ".join(args)
    value = "0" if "ALERTS" in query else "2"
    print(json.dumps({"data":{"result":[{"value":[0, value]}]}}))
else:
    raise SystemExit("unexpected kubectl arguments: " + repr(args))
""")
    kubectl.chmod(0o755)
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}", "PAYLOADS": str(payloads)}
    return subprocess.run(
        ["bash", str(ROOT / "scripts/verify_cloudflare_tunnel.sh"), "staging"],
        text=True,
        capture_output=True,
        env=env,
    )


def test_executable_verifier_accepts_two_ready_pods_on_distinct_nodes(tmp_path):
    result = _run_verifier(tmp_path, [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b")])
    assert result.returncode == 0, result.stderr
    assert 'Cannot index array with string "items"' not in result.stderr


def test_executable_verifier_rejects_invalid_pod_contracts(tmp_path):
    cases = [
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-a")],
        [_pod("tunnel-a", "node-a")],
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b", ready=False)],
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b", terminating=True)],
    ]
    for index, pods in enumerate(cases):
        case_path = tmp_path / str(index)
        case_path.mkdir()
        result = _run_verifier(case_path, pods)
        assert result.returncode != 0, f"case {index} unexpectedly passed"
