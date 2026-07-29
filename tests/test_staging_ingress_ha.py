"""Offline regression tests for the staging DNS/ingress HA lifecycle."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/staging_ingress_ha.py"


def load_module():
    spec = importlib.util.spec_from_file_location("staging_ingress_ha", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_desired_state_has_two_replicas_and_required_hostname_spread() -> None:
    core = (ROOT / "clusters/staging/platform-ha/coredns-patch.yaml").read_text()
    traefik = (ROOT / "clusters/staging/platform-ha/traefik-helmchartconfig.yaml").read_text()
    for manifest in (core, traefik):
        assert "replicas: 2" in manifest
        assert "requiredDuringSchedulingIgnoredDuringExecution:" in manifest
        assert "topologyKey: kubernetes.io/hostname" in manifest


def test_render_is_offline_and_idempotent() -> None:
    first = subprocess.run(
        [sys.executable, str(SCRIPT), "render"], text=True, capture_output=True, check=True
    )
    second = subprocess.run(
        [sys.executable, str(SCRIPT), "render"], text=True, capture_output=True, check=True
    )
    assert first.stdout == second.stdout
    assert "replicas: 2" in first.stdout


@pytest.mark.parametrize("component", ["CoreDNS", "Traefik", "Cloudflare tunnel"])
def test_verifier_rejects_single_or_same_node_ready_pods(component: str) -> None:
    module = load_module()
    pod = {
        "spec": {"nodeName": "sugarkube4"},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    with pytest.raises(SystemExit):
        module.require_spread(component, {"items": [pod, pod]})


def test_verifier_accepts_two_distinct_ready_nodes() -> None:
    module = load_module()
    pods = {
        "items": [
            {
                "spec": {"nodeName": node},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            }
            for node in ("sugarkube4", "sugarkube5")
        ]
    }
    module.require_spread("CoreDNS", pods)


def test_mutation_guards_environment_before_kubectl() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "apply", "prod"], text=True, capture_output=True
    )
    assert result.returncode != 0
    assert "staging-only" in result.stderr


def test_rollback_removes_affinity_and_restores_one_replica() -> None:
    rollback = (ROOT / "clusters/staging/platform-ha/coredns-rollback-patch.yaml").read_text()
    assert "replicas: 1" in rollback
    assert "podAntiAffinity: null" in rollback


def test_cloudflare_discovery_uses_all_namespaces_and_stable_label(monkeypatch) -> None:
    module = load_module()
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"items": [{"metadata": {"namespace": "cloudflare"}}]}), ""
        )

    monkeypatch.setattr(module, "run", fake_run)
    module.cloudflare_pods()
    assert seen[0][:4] == ("kubectl", "get", "pods", "-A")
    assert "app.kubernetes.io/name=cloudflare-tunnel" in seen[0]


def test_script_never_requests_tunnel_secrets_or_logs() -> None:
    text = SCRIPT.read_text()
    assert "secret" not in text.lower()
    assert 'kubectl", "logs' not in text
