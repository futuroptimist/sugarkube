"""Execution regressions for the read-only Cloudflare Tunnel verifier."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_cloudflare_tunnel.sh"


def _pod(name: str, node: str, *, ready: bool = True, terminating: bool = False) -> dict:
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


def _run_verifier(tmp_path: Path, pods: list[dict]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' "
        '\'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
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
                            "image": (
                                "cloudflare/cloudflared:2026.7.3@sha256:"
                                "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
                            ),
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
    payloads = {
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
    (tmp_path / "payloads.json").write_text(json.dumps(payloads))
    (bin_dir / "kubectl").write_text("""#!/usr/bin/env python3
import json, os, sys
payloads = json.load(open(os.environ["TEST_PAYLOADS"]))
args = " ".join(sys.argv[1:])
if args == "config current-context": print("sugar-staging")
elif " get deployment " in f" {args} ": print(json.dumps(payloads["deployment"]))
elif " get pods " in f" {args} ": print(json.dumps(payloads["pods"]))
elif " get pdb " in f" {args} ": print(json.dumps(payloads["pdb"]))
elif " get service " in f" {args} ": print(json.dumps(payloads["service"]))
elif " get servicemonitor " in f" {args} ": print(json.dumps(payloads["servicemonitor"]))
elif "rules?type=alert" in args:
    print(json.dumps({"data":{"groups":[{"rules":[
        {"name":"CloudflareTunnelNoHealthyConnections","health":"ok"},
        {"name":"CloudflareTunnelConnectionsDegraded","health":"ok"},
        {"name":"CloudflareTunnelMetricsTargetsDown","health":"ok"}] }]}}))
elif "query?query=" in args:
    value = "0" if "ALERTS" in args else "2"
    print(json.dumps({"data":{"result":[{"value":[0,value]}]}}))
else: raise SystemExit(f"unexpected kubectl call: {args}")
""")
    for command in (bin_dir / "helm", bin_dir / "kubectl"):
        command.chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TEST_PAYLOADS": str(tmp_path / "payloads.json"),
    }
    return subprocess.run(
        ["bash", str(VERIFIER), "staging"], capture_output=True, text=True, env=env
    )


def test_two_ready_current_pods_on_distinct_nodes_pass(tmp_path: Path) -> None:
    result = _run_verifier(tmp_path, [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b")])
    assert result.returncode == 0, result.stderr
    assert 'Cannot index array with string "items"' not in result.stderr


@pytest.mark.parametrize(
    "pods",
    [
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-a")],
        [_pod("tunnel-a", "node-a")],
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b", ready=False)],
        [
            _pod("tunnel-a", "node-a"),
            _pod("tunnel-b", "node-b"),
            _pod("tunnel-surge", "node-c", ready=False),
        ],
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b", terminating=True)],
    ],
    ids=["duplicate-node", "incorrect-count", "not-ready", "unready-surge", "terminating"],
)
def test_invalid_pod_contract_fails(tmp_path: Path, pods: list[dict]) -> None:
    result = _run_verifier(tmp_path, pods)
    assert result.returncode != 0
