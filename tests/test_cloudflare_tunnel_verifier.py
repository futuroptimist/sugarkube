# flake8: noqa: E501
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_cloudflare_tunnel.sh"


def pod(name: str, node: str, *, ready: bool = True, terminating: bool = False) -> dict:
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


def run_verifier(tmp_path: Path, pods: list[dict]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pods_file = tmp_path / "pods.json"
    pods_file.write_text(json.dumps({"apiVersion": "v1", "kind": "PodList", "items": pods}))

    (bin_dir / "helm").write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' \'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
    )
    (bin_dir / "kubectl").write_text("""#!/usr/bin/env python3
import json
import os
import sys

args = " ".join(sys.argv[1:])
if args == "config current-context":
    print("sugar-staging")
elif "get deployment cloudflare-tunnel" in args:
    print(json.dumps({
        "metadata": {"labels": {"app.kubernetes.io/managed-by": "Helm"}},
        "spec": {
            "replicas": 2,
            "strategy": {"rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
            "template": {"spec": {
                "affinity": {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [{
                    "topologyKey": "kubernetes.io/hostname",
                    "labelSelector": {"matchLabels": {
                        "app.kubernetes.io/name": "cloudflare-tunnel",
                        "app.kubernetes.io/instance": "cloudflare-tunnel",
                    }},
                }]}},
                "containers": [{
                    "image": "cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf",
                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 2000}},
                    "env": [{"name": "TUNNEL_TOKEN", "valueFrom": {"secretKeyRef": {"name": "tunnel-token", "key": "token"}}}],
                }],
                "volumes": [],
            }},
        },
    }))
elif "get pods " in args:
    print(open(os.environ["PODS_FILE"], encoding="utf-8").read())
elif "get pdb cloudflare-tunnel" in args:
    print('{"spec":{"minAvailable":1}}')
elif "get service cloudflare-tunnel-metrics" in args:
    print('{"spec":{"type":"ClusterIP","selector":{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"},"ports":[{"name":"metrics","port":2000,"protocol":"TCP","targetPort":2000}]}}')
elif "get servicemonitor cloudflare-tunnel" in args:
    print('{"metadata":{"labels":{"release":"kube-prometheus-stack"}},"spec":{"selector":{"matchLabels":{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"}},"endpoints":[{"path":"/metrics"}]}}')
elif "rules?type=alert" in args:
    rules = ["CloudflareTunnelNoHealthyConnections", "CloudflareTunnelConnectionsDegraded", "CloudflareTunnelMetricsTargetsDown"]
    print(json.dumps({"data": {"groups": [{"rules": [{"name": name, "health": "ok"} for name in rules]}]}}))
elif "ALERTS" in args:
    print('{"data":{"result":[{"value":[0,"0"]}]}}')
elif "get --raw" in args:
    print('{"data":{"result":[{"value":[0,"2"]}]}}')
else:
    raise SystemExit(f"unexpected kubectl invocation: {args}")
""")
    for command in (bin_dir / "helm", bin_dir / "kubectl"):
        command.chmod(0o755)

    env = os.environ.copy()
    env.update(PATH=f"{bin_dir}:{env['PATH']}", PODS_FILE=str(pods_file))
    return subprocess.run(
        ["bash", str(VERIFIER), "env=staging"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_two_ready_pods_on_distinct_nodes_pass(tmp_path: Path) -> None:
    result = run_verifier(tmp_path, [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-b")])

    assert result.returncode == 0, result.stderr
    assert 'Cannot index array with string "items"' not in result.stderr
    assert "staging verification passed" in result.stdout


@pytest.mark.parametrize(
    "pods",
    [
        [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-a")],
        [pod("tunnel-a", "node-a")],
        [
            pod("tunnel-a", "node-a"),
            pod("tunnel-b", "node-b", ready=False),
            pod("tunnel-old", "node-c", terminating=True),
        ],
    ],
    ids=["duplicate-node", "incorrect-count", "non-ready-and-terminating"],
)
def test_invalid_pod_contract_fails(tmp_path: Path, pods: list[dict]) -> None:
    result = run_verifier(tmp_path, pods)

    assert result.returncode != 0
