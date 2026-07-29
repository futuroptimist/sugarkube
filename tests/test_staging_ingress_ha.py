import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/staging_ingress_ha.sh"
ACTIVE = ROOT / "clusters/staging/ingress-ha"
JUSTFILE = ROOT / "justfile"


def load_yaml(path):
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.safe_load_file(ARGV[0]))",
            path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("component", ["coredns", "traefik"])
def test_active_config_has_two_replicas_and_required_hostname_anti_affinity(component):
    document = load_yaml(ACTIVE / f"{component}-helmchartconfig.yaml")
    values = document["spec"]["valuesContent"]
    parsed = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load(STDIN.read))"],
        input=values,
        check=True,
        capture_output=True,
        text=True,
    )
    values = json.loads(parsed.stdout)
    replicas = (
        values["replicaCount"] if component == "coredns" else values["deployment"]["replicas"]
    )
    assert replicas == 2
    terms = values["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    assert terms and all(term["topologyKey"] == "kubernetes.io/hostname" for term in terms)
    assert document["kind"] == "HelmChartConfig"
    assert document["metadata"] == {"name": component, "namespace": "kube-system"}


@pytest.mark.parametrize("component", ["coredns", "traefik"])
def test_rollback_explicitly_restores_singleton_without_anti_affinity(component):
    document = load_yaml(ACTIVE / "rollback" / f"{component}-helmchartconfig.yaml")
    values = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.safe_load(STDIN.read))"],
        input=document["spec"]["valuesContent"],
        check=True,
        capture_output=True,
        text=True,
    )
    values = json.loads(values.stdout)
    replicas = (
        values["replicaCount"] if component == "coredns" else values["deployment"]["replicas"]
    )
    assert replicas == 1
    assert values["affinity"] == {}


def run(action, env="env=staging", *, path=None):
    environment = os.environ.copy()
    if path:
        environment["PATH"] = f"{path}:{environment['PATH']}"
    return subprocess.run(
        [SCRIPT, action, env], capture_output=True, text=True, check=False, env=environment
    )


def fake_kubectl(tmp_path, context="wrong-context"):
    executable = tmp_path / "kubectl"
    executable.write_text(
        f'#!/bin/sh\nif [ "$1 $2" = "config current-context" ]; then echo {context}; exit 0; fi\nexit 0\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return tmp_path


@pytest.mark.parametrize("action", ["apply", "verify", "rollback"])
def test_mutations_fail_closed_on_wrong_context(tmp_path, action):
    result = run(action, path=fake_kubectl(tmp_path))
    assert result.returncode == 3
    assert "expected context 'sugar-staging'" in result.stderr


@pytest.mark.parametrize("action", ["render", "plan", "status", "apply", "verify", "rollback"])
def test_all_actions_reject_non_staging_environment(action):
    result = run(action, "env=prod")
    assert result.returncode == 2
    assert "staging-only" in result.stderr


def test_render_is_idempotent_and_contains_only_two_configs():
    first = run("render")
    second = run("render")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert first.stdout.count("kind: HelmChartConfig") == 2
    assert "Secret" not in first.stdout


def test_verify_logic_rejects_singleton_and_same_node_and_redacts_targets():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "len(ready) < 2 or len(nodes) < 2" in text
    assert "app.kubernetes.io/name in (cloudflare-tunnel,cloudflared)" in text
    assert "target redacted" in text
    assert "credentials" not in text.lower()
    assert '--timeout="${TIMEOUT}"' in text
    assert "trap 'kubectl delete pod" in text


def test_justfile_exposes_complete_small_lifecycle():
    text = JUSTFILE.read_text(encoding="utf-8")
    for action in ("render", "plan", "status", "apply", "verify", "rollback"):
        assert f"staging-ingress-ha-{action}" in text


def test_flux_staging_path_does_not_own_active_ha_configs():
    flux = (ROOT / "clusters/staging/kustomization.yaml").read_text(encoding="utf-8")
    assert "ingress-ha" not in flux
