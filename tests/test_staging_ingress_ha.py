import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/staging_ingress_ha.sh"
VERIFY = ROOT / "scripts/staging_ingress_ha_verify.py"
CONFIG = ROOT / "clusters/staging/ingress-ha"


def pod(node, ready=True):
    return {
        "spec": {"nodeName": node},
        "status": {"phase": "Running", "containerStatuses": [{"ready": ready}]},
    }


def inventory(nodes=("sugarkube4", "sugarkube5")):
    pods = {"items": [pod(node) for node in nodes]}
    endpoints = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]}
    return {
        "coredns": pods,
        "traefik": pods,
        "cloudflare": pods,
        "dns_endpoints": endpoints,
        "traefik_endpoints": endpoints,
    }


def run_verifier(value):
    return subprocess.run([str(VERIFY)], input=json.dumps(value), text=True, capture_output=True)


def test_canonical_configs_have_two_replicas_and_required_hostname_spread():
    traefik = (CONFIG / "traefik-helmchartconfig.yaml").read_text()
    renderer = (ROOT / "scripts/render_coredns_ha.py").read_text()
    assert "replicas: 2" in traefik
    assert "requiredDuringSchedulingIgnoredDuringExecution:" in traefik
    assert "topologyKey: kubernetes.io/hostname" in traefik
    assert 'spec["replicas"] = 2' in renderer
    assert '"topologyKey": "kubernetes.io/hostname"' in renderer
    assert "/var/lib/rancher/k3s/server/manifests" not in traefik + renderer


def test_coredns_renderer_preserves_packaged_contract_and_is_idempotent():
    source = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "coredns",
            "namespace": "kube-system",
            "resourceVersion": "9",
            "labels": {"k8s-app": "kube-dns"},
        },
        "spec": {
            "selector": {"matchLabels": {"k8s-app": "kube-dns"}},
            "template": {
                "metadata": {"labels": {"k8s-app": "kube-dns"}},
                "spec": {
                    "serviceAccountName": "coredns",
                    "containers": [
                        {
                            "name": "coredns",
                            "image": "example/coredns:pinned",
                            "readinessProbe": {"httpGet": {"path": "/ready"}},
                        }
                    ],
                },
            },
        },
    }
    command = [str(ROOT / "scripts/render_coredns_ha.py")]
    first = subprocess.run(
        command, input=json.dumps(source), text=True, capture_output=True, check=True
    ).stdout
    rendered = json.loads(first)
    assert rendered["metadata"]["name"] == "coredns-ha"
    assert "resourceVersion" not in rendered["metadata"]
    assert rendered["spec"]["replicas"] == 2
    assert rendered["spec"]["template"]["spec"]["serviceAccountName"] == "coredns"
    assert (
        rendered["spec"]["template"]["spec"]["containers"][0]["image"] == "example/coredns:pinned"
    )
    second = subprocess.run(
        command, input=json.dumps(source), text=True, capture_output=True, check=True
    ).stdout
    assert first == second


def test_verifier_accepts_healthy_node_spread_inventory():
    result = run_verifier(inventory())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("component", ["coredns", "traefik", "cloudflare"])
def test_verifier_rejects_single_replica(component):
    value = inventory()
    value[component] = {"items": [pod("sugarkube4")]}
    result = run_verifier(value)
    assert result.returncode != 0
    assert "at least 2" in result.stderr


@pytest.mark.parametrize("component", ["coredns", "traefik", "cloudflare"])
def test_verifier_rejects_same_node_replicas(component):
    value = inventory()
    value[component] = {"items": [pod("sugarkube4"), pod("sugarkube4")]}
    result = run_verifier(value)
    assert result.returncode != 0
    assert "not spread" in result.stderr


def test_environment_guard_runs_before_tools_or_cluster_access():
    result = subprocess.run([str(SCRIPT), "apply", "env=prod"], text=True, capture_output=True)
    assert result.returncode == 2
    assert "only supports explicit env=staging" in result.stderr


def test_context_guard_fails_closed_without_mutation(tmp_path):
    kubectl = tmp_path / "kubectl"
    kubectl.write_text("#!/bin/sh\n[ \"$1 $2\" = 'config current-context' ] && echo production\n")
    kubectl.chmod(0o755)
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(SCRIPT), "apply", "env=staging"], env=env, text=True, capture_output=True
    )
    assert result.returncode == 3
    assert "refusing cluster access" in result.stderr


def test_script_has_bounded_cleanup_discovery_rollback_and_redaction():
    text = SCRIPT.read_text()
    assert '--timeout="${TIMEOUT}"' in text
    assert "trap 'kubectl -n default delete pod" in text
    assert "app.kubernetes.io/name=cloudflare-tunnel" in text
    assert "--all-namespaces" in text
    assert "delete helmchartconfig" in text
    assert "delete deployment coredns-ha" in text
    assert "URL redacted" in text
    assert "get secret" not in text
    assert "kubectl patch" not in text
