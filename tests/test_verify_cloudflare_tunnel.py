# flake8: noqa: E501
"""Execution-level regression tests for the Cloudflare Tunnel verifier."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_cloudflare_tunnel.sh"
IMAGE = "cloudflare/cloudflared:2026.7.3@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"


def pod(name: str, node: str, *, ready: bool = True, terminating: bool = False) -> dict:
    metadata = {"name": name}
    if terminating:
        metadata["deletionTimestamp"] = "2026-08-09T12:00:00Z"
    return {
        "metadata": metadata,
        "spec": {"nodeName": node},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


@pytest.fixture
def fake_commands(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "helm").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' \'[{"name":"cloudflare-tunnel","chart":"cloudflare-tunnel-0.3.2"}]\'\n'
    )
    (bindir / "helm").chmod(0o755)
    (bindir / "kubectl").write_text(f"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args == ["config", "current-context"]:
    print("sugar-staging")
elif "deployment" in args:
    print(json.dumps({{
        "metadata": {{"labels": {{"app.kubernetes.io/managed-by": "Helm"}}}},
        "spec": {{"replicas": 2, "strategy": {{"rollingUpdate": {{"maxUnavailable": 0, "maxSurge": 1}}}},
          "template": {{"spec": {{"affinity": {{"podAntiAffinity": {{"requiredDuringSchedulingIgnoredDuringExecution": [{{
            "topologyKey": "kubernetes.io/hostname", "labelSelector": {{"matchLabels": {{
              "app.kubernetes.io/name": "cloudflare-tunnel", "app.kubernetes.io/instance": "cloudflare-tunnel"}}}}}}]}}}},
            "containers": [{{"image": "{IMAGE}", "readinessProbe": {{"httpGet": {{"path": "/ready", "port": 2000}}}},
              "env": [{{"name": "TUNNEL_TOKEN", "valueFrom": {{"secretKeyRef": {{"name": "tunnel-token", "key": "token"}}}}}}]}}],
            "volumes": []}}}}}}}}))
elif "pods" in args:
    print(os.environ["POD_LIST"])
elif "pdb" in args:
    print('{{"spec":{{"minAvailable":1}}}}')
elif "service" in args and "servicemonitor" not in args:
    print('{{"spec":{{"type":"ClusterIP","selector":{{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"}},"ports":[{{"name":"metrics","port":2000,"protocol":"TCP","targetPort":2000}}]}}}}')
elif "servicemonitor" in args:
    print('{{"metadata":{{"labels":{{"release":"kube-prometheus-stack"}}}},"spec":{{"selector":{{"matchLabels":{{"app.kubernetes.io/instance":"cloudflare-tunnel","app.kubernetes.io/name":"cloudflare-tunnel"}}}},"endpoints":[{{"path":"/metrics"}}]}}}}')
elif any("rules?type=alert" in arg for arg in args):
    names = ["CloudflareTunnelNoHealthyConnections", "CloudflareTunnelConnectionsDegraded", "CloudflareTunnelMetricsTargetsDown"]
    print(json.dumps({{"data": {{"groups": [{{"rules": [{{"name": name, "health": "ok"}} for name in names]}}]}}}}))
elif "--raw" in args:
    value = "0" if "ALERTS" in "".join(args) else "2"
    print(json.dumps({{"data": {{"result": [{{"value": [0, value]}}]}}}}))
else:
    raise SystemExit(f"unexpected kubectl invocation: {{args}}")
""")
    (bindir / "kubectl").chmod(0o755)
    return bindir


def run_verifier(fake_commands: Path, pods: list[dict]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_commands}:{env['PATH']}"
    env["POD_LIST"] = json.dumps({"apiVersion": "v1", "kind": "PodList", "items": pods})
    return subprocess.run(
        ["bash", str(VERIFIER), "staging"], env=env, text=True, capture_output=True, check=False
    )


def test_two_ready_current_pods_on_distinct_nodes_pass(fake_commands: Path) -> None:
    result = run_verifier(
        fake_commands, [pod("connector-1", "node-a"), pod("connector-2", "node-b")]
    )

    assert result.returncode == 0, result.stderr
    assert 'Cannot index array with string "items"' not in result.stderr


@pytest.mark.parametrize(
    "pods",
    [
        [pod("connector-1", "node-a"), pod("connector-2", "node-a")],
        [pod("connector-1", "node-a")],
        [pod("connector-1", "node-a"), pod("connector-2", "node-b", ready=False)],
        [pod("connector-1", "node-a"), pod("connector-2", "node-b", terminating=True)],
    ],
    ids=["duplicate-node", "incorrect-count", "non-ready", "terminating"],
)
def test_invalid_pod_sets_fail(fake_commands: Path, pods: list[dict]) -> None:
    result = run_verifier(fake_commands, pods)

    assert result.returncode != 0
