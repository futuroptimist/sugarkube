"""Execution-level regression tests for the Cloudflare Tunnel verifier."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_cloudflare_tunnel.sh"
EXPECTED_IMAGE = (
    "cloudflare/cloudflared:2026.7.3@sha256:"
    "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)


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


@pytest.fixture()
def mock_commands(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' "
        '\'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
    )
    (bin_dir / "kubectl").write_text("""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
if args == ["config", "current-context"]:
    print("sugar-staging")
elif "pods" in args:
    print(os.environ["PODS_JSON"])
elif "deployment" in args:
    print(os.environ["DEPLOYMENT_JSON"])
elif "pdb" in args:
    print('{"spec":{"minAvailable":1}}')
elif "service" in args and "cloudflare-tunnel-metrics" in args:
    print(os.environ["SERVICE_JSON"])
elif "servicemonitor" in args:
    print(os.environ["MONITOR_JSON"])
elif "--raw" in args:
    path = args[args.index("--raw") + 1]
    if "rules?type=alert" in path:
        print(os.environ["RULES_JSON"])
    else:
        value = "0" if "ALERTS" in path else "2"
        print(json.dumps({"data": {"result": [{"value": [0, value]}]}}))
else:
    raise SystemExit(f"unexpected kubectl arguments: {args}")
""")
    for command in ("helm", "kubectl"):
        (bin_dir / command).chmod(0o755)
    return bin_dir


def _run_verifier(mock_commands: Path, pods: list[dict]) -> subprocess.CompletedProcess[str]:
    labels = {
        "app.kubernetes.io/name": "cloudflare-tunnel",
        "app.kubernetes.io/instance": "cloudflare-tunnel",
    }
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{mock_commands}:{env['PATH']}",
            "PODS_JSON": json.dumps({"apiVersion": "v1", "kind": "PodList", "items": pods}),
            "DEPLOYMENT_JSON": json.dumps(
                {
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
                                                "labelSelector": {"matchLabels": labels},
                                            }
                                        ]
                                    }
                                },
                                "containers": [
                                    {
                                        "image": EXPECTED_IMAGE,
                                        "readinessProbe": {
                                            "httpGet": {"path": "/ready", "port": 2000}
                                        },
                                        "env": [
                                            {
                                                "name": "TUNNEL_TOKEN",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": "tunnel-token",
                                                        "key": "token",
                                                    }
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
            ),
            "SERVICE_JSON": json.dumps(
                {
                    "spec": {
                        "type": "ClusterIP",
                        "selector": labels,
                        "ports": [
                            {"name": "metrics", "port": 2000, "protocol": "TCP", "targetPort": 2000}
                        ],
                    }
                }
            ),
            "MONITOR_JSON": json.dumps(
                {
                    "metadata": {"labels": {"release": "kube-prometheus-stack"}},
                    "spec": {
                        "selector": {"matchLabels": labels},
                        "endpoints": [{"path": "/metrics"}],
                    },
                }
            ),
            "RULES_JSON": json.dumps(
                {
                    "data": {
                        "groups": [
                            {
                                "rules": [
                                    {"name": name, "health": "ok"}
                                    for name in (
                                        "CloudflareTunnelNoHealthyConnections",
                                        "CloudflareTunnelConnectionsDegraded",
                                        "CloudflareTunnelMetricsTargetsDown",
                                    )
                                ]
                            }
                        ]
                    }
                }
            ),
        }
    )
    return subprocess.run(
        ["bash", str(VERIFIER), "env=staging"], env=env, text=True, capture_output=True
    )


def test_two_ready_pods_on_distinct_nodes_pass_without_jq_context_error(mock_commands: Path):
    result = _run_verifier(mock_commands, [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b")])
    assert result.returncode == 0, result.stderr
    assert 'Cannot index array with string "items"' not in result.stderr
    assert "Secret values were not read" in result.stdout


def test_non_ready_and_terminating_pods_are_ignored(mock_commands: Path):
    pods = [
        _pod("tunnel-a", "node-a"),
        _pod("tunnel-b", "node-b"),
        _pod("old-not-ready", "node-c", ready=False),
        _pod("old-terminating", "node-d", terminating=True),
    ]
    result = _run_verifier(mock_commands, pods)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "pods",
    [
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-a")],
        [_pod("tunnel-a", "node-a")],
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b", ready=False)],
        [_pod("tunnel-a", "node-a"), _pod("tunnel-b", "node-b", terminating=True)],
    ],
    ids=["duplicate-node", "incorrect-count", "not-ready", "terminating"],
)
def test_invalid_pod_sets_fail(mock_commands: Path, pods: list[dict]):
    result = _run_verifier(mock_commands, pods)
    assert result.returncode != 0
