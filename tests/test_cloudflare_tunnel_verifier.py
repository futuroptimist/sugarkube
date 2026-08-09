import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_cloudflare_tunnel.sh"


def pod(name, node, *, ready=True, running=True, terminating=False):
    metadata = {"name": name}
    if terminating:
        metadata["deletionTimestamp"] = "2026-08-09T00:00:00Z"
    return {
        "metadata": metadata,
        "spec": {"nodeName": node},
        "status": {
            "phase": "Running" if running else "Pending",
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


@pytest.fixture
def verifier_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "helm").write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
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
                "affinity": {"podAntiAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": [{
                    "topologyKey": "kubernetes.io/hostname",
                    "labelSelector": {"matchLabels": {
                        "app.kubernetes.io/name": "cloudflare-tunnel",
                        "app.kubernetes.io/instance": "cloudflare-tunnel"
                    }}
                }]}},
                "containers": [{
                    "image": "cloudflare/cloudflared:2026.7.3@sha256:"
                             "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf",
                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 2000}},
                    "env": [{"name": "TUNNEL_TOKEN", "valueFrom": {
                        "secretKeyRef": {"name": "tunnel-token", "key": "token"}
                    }}]
                }],
                "volumes": []
            }}
        }
    }))
elif "get pods -l" in args:
    print(os.environ["PODS_JSON"])
elif "get pdb cloudflare-tunnel" in args:
    print('{"spec":{"minAvailable":1}}')
elif "get service cloudflare-tunnel-metrics" in args:
    print('{"spec":{"type":"ClusterIP","selector":{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"},"ports":[{"name":"metrics","port":2000,"protocol":"TCP","targetPort":2000}]}}')
elif "get servicemonitor cloudflare-tunnel" in args:
    print('{"metadata":{"labels":{"release":"kube-prometheus-stack"}},"spec":{"selector":{"matchLabels":{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"}},"endpoints":[{"path":"/metrics"}]}}')
elif "rules?type=alert" in args:
    print('{"data":{"groups":[{"rules":[{"name":"CloudflareTunnelNoHealthyConnections","health":"ok"},{"name":"CloudflareTunnelConnectionsDegraded","health":"ok"},{"name":"CloudflareTunnelMetricsTargetsDown","health":"ok"}]}]}}')
elif "api/v1/query?query=" in args:
    value = "0" if "ALERTS" in args else "2"
    print(json.dumps({"data": {"result": [{"value": [0, value]}]}}))
else:
    print("unexpected kubectl invocation: " + args, file=sys.stderr)
    sys.exit(99)
""")
    for executable in (bin_dir / "helm", bin_dir / "kubectl"):
        executable.chmod(0o755)
    return bin_dir


def run_verifier(verifier_bin, pods):
    env = os.environ.copy()
    env["PATH"] = f"{verifier_bin}:{env['PATH']}"
    env["PODS_JSON"] = json.dumps({"apiVersion": "v1", "kind": "PodList", "items": pods})
    return subprocess.run(
        ["bash", str(VERIFIER), "staging"], env=env, text=True, capture_output=True
    )


def test_two_ready_pods_on_distinct_nodes_pass_without_jq_context_error(verifier_bin):
    result = run_verifier(verifier_bin, [pod("tunnel-a", "node-a"), pod("tunnel-b", "node-b")])

    assert result.returncode == 0, result.stderr
    assert "verification passed" in result.stdout
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
def test_invalid_pod_placement_or_state_fails(verifier_bin, pods):
    result = run_verifier(verifier_bin, pods)

    assert result.returncode != 0
