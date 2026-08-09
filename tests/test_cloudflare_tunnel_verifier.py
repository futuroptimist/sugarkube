import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts/verify_cloudflare_tunnel.sh"


def pod(name, node, *, ready=True, terminating=False):
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


def run_verifier(tmp_path, pods):
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
    responses = {
        "deployment": deployment,
        "pods": {"apiVersion": "v1", "kind": "PodList", "items": pods},
        "pdb": {"spec": {"minAvailable": 1}},
        "service": {
            "spec": {
                "type": "ClusterIP",
                "selector": {
                    "app.kubernetes.io/instance": "cloudflare-tunnel",
                    "app.kubernetes.io/name": "cloudflare-tunnel",
                },
                "ports": [{"name": "metrics", "port": 2000, "protocol": "TCP", "targetPort": 2000}],
            }
        },
        "servicemonitor": {
            "metadata": {"labels": {"release": "kube-prometheus-stack"}},
            "spec": {
                "selector": {
                    "matchLabels": {
                        "app.kubernetes.io/instance": "cloudflare-tunnel",
                        "app.kubernetes.io/name": "cloudflare-tunnel",
                    }
                },
                "endpoints": [{"path": "/metrics"}],
            },
        },
    }
    fixture = tmp_path / "responses.json"
    fixture.write_text(json.dumps(responses))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
    )
    (bin_dir / "kubectl").write_text("""#!/usr/bin/env python3
import json, os, sys
data = json.load(open(os.environ["VERIFIER_RESPONSES"]))
args = sys.argv[1:]
if args == ["config", "current-context"]:
    print("sugar-staging")
elif "--raw" in args:
    path = args[-1]
    if "rules?type=alert" in path:
        print(json.dumps({"data": {"groups": [{"rules": [
            {"name": name, "health": "ok"} for name in (
                "CloudflareTunnelNoHealthyConnections",
                "CloudflareTunnelConnectionsDegraded",
                "CloudflareTunnelMetricsTargetsDown",
            )
        ]}]}}))
    else:
        value = "0" if "ALERTS" in path else "2"
        print(json.dumps({"data": {"result": [{"value": [0, value]}]}}))
elif "deployment" in args:
    print(json.dumps(data["deployment"]))
elif "pods" in args:
    print(json.dumps(data["pods"]))
elif "pdb" in args:
    print(json.dumps(data["pdb"]))
elif "service" in args:
    print(json.dumps(data["service"]))
elif "servicemonitor" in args:
    print(json.dumps(data["servicemonitor"]))
else:
    raise SystemExit(f"unexpected kubectl arguments: {args}")
""")
    for command in (bin_dir / "helm", bin_dir / "kubectl"):
        command.chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "VERIFIER_RESPONSES": str(fixture),
    }
    return subprocess.run(
        ["bash", str(VERIFIER), "env=staging"], text=True, capture_output=True, env=env
    )


def test_two_ready_pods_on_distinct_nodes_pass(tmp_path):
    result = run_verifier(tmp_path, [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-b")])
    assert result.returncode == 0, result.stderr
    assert 'Cannot index array with string "items"' not in result.stderr


@pytest.mark.parametrize(
    "pods",
    [
        [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-a")],
        [pod("tunnel-a", "node-a")],
        [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-b", ready=False)],
        [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-b", terminating=True)],
    ],
    ids=["duplicate-node", "incorrect-count", "not-ready", "terminating"],
)
def test_invalid_pod_sets_fail(tmp_path, pods):
    assert run_verifier(tmp_path, pods).returncode != 0
