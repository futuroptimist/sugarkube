"""Focused offline contracts for the production resilience collector."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prod_audit", ROOT / "scripts/prod_resilience_audit.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def slices(endpoints_by_slice):
    return {
        "items": [
            {
                "metadata": {"labels": {"kubernetes.io/service-name": "traefik"}},
                "endpoints": endpoints,
            }
            for endpoints in endpoints_by_slice
        ]
    }


def test_endpoint_slices_aggregate_all_slices_and_effective_conditions() -> None:
    document = slices(
        [
            [{"addresses": ["10.0.0.1"], "nodeName": "a", "conditions": {}}],
            [
                {
                    "addresses": ["10.0.0.2"],
                    "nodeName": "b",
                    "conditions": {"ready": True, "serving": True, "terminating": False},
                },
                {
                    "addresses": ["10.0.0.3"],
                    "nodeName": "c",
                    "conditions": {"ready": True, "terminating": True},
                },
            ],
        ]
    )
    result = audit.endpoints(document, "traefik")
    assert result == {
        "service": "traefik",
        "slices": 2,
        "uniqueEndpoints": 3,
        "healthyEndpoints": 2,
        "unhealthyEndpoints": 1,
        "healthyNodes": ["a", "b"],
    }
    assert "10.0.0.1" not in json.dumps(result)


def test_conflicting_duplicate_endpoint_fails_closed() -> None:
    endpoint = {"addresses": ["10.0.0.1"], "nodeName": "a", "conditions": {"ready": True}}
    other = json.loads(json.dumps(endpoint))
    other["conditions"]["ready"] = False
    result = audit.endpoints(slices([[endpoint], [other]]), "traefik")
    assert result["healthyEndpoints"] == 0
    assert result["unhealthyEndpoints"] == 1


def test_deployment_snapshot_keeps_secret_reference_but_not_value() -> None:
    dep = {
        "metadata": {"name": "tunnel", "namespace": "cf", "uid": "pod-uid"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "cloudflared",
                            "image": "image@sha256:digest",
                            "env": [
                                {
                                    "name": "TUNNEL_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {"name": "tunnel-token", "key": "token"}
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }
    result = audit.deployment_snapshot(dep)
    encoded = json.dumps(result)
    assert "tunnel-token" in encoded
    assert '"value"' not in encoded
    assert "connector" not in encoded.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["kubectl", "apply", "-f", "x"],
        ["kubectl", "rollout", "restart", "deployment/x"],
        ["kubectl", "exec", "pod/x"],
        ["helm", "upgrade", "x", "chart"],
        ["helm", "repo", "add", "x", "url"],
        ["kubectl", "scale", "deployment/x"],
        ["kubectl", "cp", "pod/x:/x", "."],
        ["helm", "test", "x"],
        ["flux", "reconcile", "kustomization", "x"],
        ["sudo", "true"],
        ["ssh", "host"],
    ],
)
def test_internal_runner_rejects_mutation_before_execution(monkeypatch, argv) -> None:
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(audit.subprocess, "run", forbidden)
    with pytest.raises(audit.HardFailure, match="safety policy"):
        audit.run(argv)
    assert called is False


def test_source_has_no_cluster_mutation_or_dormant_flux_discovery() -> None:
    source = (ROOT / "scripts/prod_resilience_audit.py").read_text()
    for forbidden in ("flux reconcile", "systemctl", "nftables", "poweroff"):
        assert forbidden not in source
    assert '["kubectl", "port-forward"' not in source
    assert "platform/cloudflared" not in source
    assert "cloudflared-values.yaml" not in source


def test_target_manifest_is_canonical_and_narrow() -> None:
    targets = json.loads((ROOT / "config/prod-resilience-audit-targets.json").read_text())
    assert sorted(targets) == ["danielsmith.io", "democratized.space", "token.place"]
    assert all(path.startswith("/") for paths in targets.values() for path in paths)


@pytest.mark.parametrize("value", [0, "0"])
def test_int_or_string_comparison_accepts_kubernetes_encodings(value) -> None:
    assert audit.int_or_string_equals(value, 0)


@pytest.mark.parametrize("value", [None, 1, "1", False])
def test_int_or_string_comparison_rejects_other_values(value) -> None:
    assert not audit.int_or_string_equals(value, 0)


def test_runner_failure_is_bounded_and_redacted(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        ["kubectl", "get", "nodes"], 7, stderr="permission denied " + "x" * 600
    )
    monkeypatch.setattr(audit.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(audit.HardFailure) as caught:
        audit.run(["kubectl", "get", "nodes"])

    message = str(caught.value)
    assert "exit 7" in message
    assert "kubectl/get" in message
    assert "permission denied" not in message
    assert "x" * 20 not in message
    assert len(message) < 100


def test_successful_status_with_transport_error_is_unhealthy() -> None:
    assert audit.probes_unhealthy([{"status": 200, "error": "transport"}])
    assert not audit.probes_unhealthy([{"status": 204, "error": "none"}])


@pytest.mark.parametrize(
    "targets",
    [{}, {"example.com": []}, [], {"example.com": "path"}, {1: ["/"]}, {"x": [1]}],
)
def test_empty_probe_targets_fail_closed(targets) -> None:
    with pytest.raises(audit.HardFailure, match="target manifest"):
        audit.probe_urls(targets)


def test_required_hostname_anti_affinity_matches_workload() -> None:
    affinity = {
        "podAntiAffinity": {
            "requiredDuringSchedulingIgnoredDuringExecution": [
                {
                    "topologyKey": "kubernetes.io/hostname",
                    "labelSelector": {"matchLabels": {"app": "tunnel"}},
                }
            ]
        }
    }
    assert audit.required_hostname_anti_affinity(affinity, {"app": "tunnel"})
    assert not audit.required_hostname_anti_affinity(affinity, {"app": "unrelated"})


def test_traefik_desired_snapshot_never_retains_raw_values() -> None:
    result = audit.traefik_desired_snapshot(
        "deployment:\n  replicas: 2\naffinity:\n  "
        "requiredDuringSchedulingIgnoredDuringExecution:\n"
        "    app.kubernetes.io/name: traefik\n"
        "    topologyKey: kubernetes.io/hostname\nsecret: do-not-retain\n"
    )
    assert result == {"replicas": 2, "requiredHostnameAntiAffinity": True}
    assert "do-not-retain" not in json.dumps(result)


FAKE_TOOL = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

state = json.loads(Path(os.environ["AUDIT_FAKE_STATE"]).read_text())
with Path(os.environ["AUDIT_COMMAND_LOG"]).open("a") as stream:
    stream.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + "\n")
tool, args = Path(sys.argv[0]).name, sys.argv[1:]

def emit(value):
    print(json.dumps(value) if not isinstance(value, str) else value)

labels = {"sugarkube.env": "prod", "sugarkube.cluster": "sugar-prod"}
node_names = state.get("nodes", ["sugarkube0", "sugarkube1", "sugarkube2"])
nodes = {"items": [{"metadata": {"name": n, "labels": labels},
                    "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
                   for n in node_names]}
if tool == "git":
    emit("0123456789abcdef0123456789abcdef01234567"); raise SystemExit()
if tool == "curl":
    print("credential=SECRET-CANARY connector=CONNECTOR-CANARY", file=sys.stderr)
    if state.get("failed_probe") and args[-1].endswith("/healthz"):
        emit("000\t0.01\t0.00\t0.02"); raise SystemExit(28)
    emit("204\t0.01\t0.02\t0.03"); raise SystemExit()
if tool == "helm":
    clean = args[2:] if args[:1] in (["-n"], ["--namespace"]) else args
    if clean[0] == "list":
        emit([{ "name": "cloudflare", "namespace": "cloudflare", "status": "deployed",
                "chart": "cloudflare-tunnel-0.3.2", "app_version": "2026.7.3", "revision": "1"}])
    elif clean[0] == "history":
        emit([{"revision": 1, "updated": "fixed", "status": "deployed",
               "chart": "cloudflare-tunnel-0.3.2", "app_version": "2026.7.3"}])
    else:
        emit({"info": {"status": "deployed"}})
    raise SystemExit()

identity = args[:1] == ["--kubeconfig"]
if identity:
    args = args[2:]
if args == ["config", "current-context"]:
    emit(state.get("context", "sugar-prod")); raise SystemExit()
if identity and args[:2] == ["get", "nodes"] and state.get("identity_fail"):
    print("credential=SECRET-CANARY connector=CONNECTOR-CANARY", file=sys.stderr)
    raise SystemExit(1)
if args[:2] == ["get", "nodes"]:
    emit(nodes); raise SystemExit()
if args[:3] == ["config", "view", "--minify"]:
    emit("https://sanitized.invalid"); raise SystemExit()
if args[:3] == ["get", "--raw", "/readyz?verbose"]:
    emit("readyz check passed\n[+]etcd ok"); raise SystemExit()
if args[:2] == ["get", "--raw"]:
    count = 0 if "ALERTS" in args[2] else 2
    emit({"data": {"result": [{"value": [0, str(count)]}]}}); raise SystemExit()

ns = None
if args[:1] in (["-n"], ["--namespace"]):
    ns, args = args[1], args[2:]
kind = args[1] if args[:1] == ["get"] and len(args) > 1 else ""
name = args[2] if len(args) > 2 and not args[2].startswith("-") else ""
pod_labels = {"app": "cloudflare"}
anti = {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
    {"topologyKey": "kubernetes.io/hostname", "labelSelector": {"matchLabels": pod_labels}}
]}}
traefik_anti = {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
    {"topologyKey": "kubernetes.io/hostname",
     "labelSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}}}
]}}
def pod(uid, node):
    return {"metadata": {"uid": uid}, "spec": {"nodeName": node},
            "status": {"conditions": [{"type": "Ready", "status": "True"}],
                       "containerStatuses": [{"restartCount": 0}]}}
def deployment(dep_name, labels_, affinity):
    container = {"name": dep_name, "image": "unused"}
    if dep_name == "cloudflare":
        container = {"name": "cloudflared", "image": os.environ["AUDIT_EXPECTED_IMAGE"],
                     "readinessProbe": {"httpGet": {"path": "/ready", "port": 2000}}}
    return {"metadata": {"name": dep_name, "namespace": ns or "cloudflare", "uid": dep_name,
                         "generation": 1, "labels": labels_},
            "spec": {"replicas": 2, "selector": {"matchLabels": labels_},
                     "strategy": {"rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
                     "template": {"metadata": {"labels": labels_},
                                  "spec": {"affinity": affinity, "containers": [container]}}},
            "status": {"readyReplicas": 2, "availableReplicas": 2}}
if kind == "deployment" and args[2:3] == ["-A"]:
    dep = deployment("cloudflare", pod_labels, anti)
    dep["metadata"]["labels"]["app.kubernetes.io/name"] = "cloudflare-tunnel"
    dep["metadata"]["labels"]["app.kubernetes.io/instance"] = "cloudflare"
    emit({"items": [dep]}); raise SystemExit()
if kind == "deployment" and name in ("coredns", "coredns-ha", "traefik"):
    lab = {"app.kubernetes.io/name": name}
    emit(deployment(name, lab, traefik_anti if name == "traefik" else anti)); raise SystemExit()
if kind == "pods":
    one = state.get("gap") and ns == "kube-system"
    emit({"items": [pod("a", "sugarkube0")] + ([] if one else [pod("b", "sugarkube1")])})
elif kind == "pdb":
    emit({"items": [] if ns == "kube-system" else
          [{"metadata": {"name": "cloudflare-pdb"},
            "spec": {"selector": {"matchLabels": pod_labels}, "minAvailable": 1}}]})
elif kind == "endpointslices.discovery.k8s.io":
    service = next(x.split("=", 1)[1] for x in args if x.startswith("kubernetes.io/service-name="))
    emit({"items": [{"metadata": {"labels": {"kubernetes.io/service-name": service}},
                     "endpoints": [{"addresses": ["10.0.0.1"], "nodeName": "sugarkube0", "conditions": {}},
                                   {"addresses": ["10.0.0.2"], "nodeName": "sugarkube1", "conditions": {}}]}]})
elif kind == "service" and name == "traefik":
    emit({"spec": {"internalTrafficPolicy": "Local"}})
elif kind == "helmchartconfig":
    emit({"metadata": {"uid": "hcc"}, "spec": {"valuesContent":
          "deployment:\n  replicas: 2\naffinity:\n  requiredDuringSchedulingIgnoredDuringExecution:\n"
          "    app.kubernetes.io/name: traefik\n    topologyKey: kubernetes.io/hostname\n"}})
elif kind == "service":
    emit({"items": [{"metadata": {"name": "cloudflare-metrics", "labels": {"monitor": "cloudflare"}},
                     "spec": {"selector": pod_labels, "ports": [{"name": "metrics", "port": 2000,
                                                                   "targetPort": 2000}]}}]})
elif kind == "servicemonitor":
    emit({"items": [{"metadata": {"name": "cloudflare"},
                     "spec": {"selector": {"matchLabels": {"monitor": "cloudflare"}},
                              "namespaceSelector": {"matchNames": ["cloudflare"]},
                              "endpoints": [{"port": "metrics", "path": "/metrics"}]}}]})
else:
    print("unexpected fake kubectl invocation", args, file=sys.stderr); raise SystemExit(9)
"""


@pytest.fixture
def audit_harness(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("kubectl", "helm", "curl", "git"):
        path = bin_dir / name
        path.write_text(FAKE_TOOL)
        path.chmod(0o755)
    state = tmp_path / "state.json"
    log = tmp_path / "commands.jsonl"

    def execute(label, *, cli_env="prod", require_parity=False, **scenario):
        state.write_text(json.dumps(scenario))
        evidence = tmp_path / label
        env = os.environ.copy()
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
            KUBECONFIG=str(tmp_path / "kubeconfig"),
            AUDIT_FAKE_STATE=str(state),
            AUDIT_COMMAND_LOG=str(log),
            AUDIT_EXPECTED_IMAGE=audit.EXPECTED_IMAGE,
            SUGARKUBE_AUDIT_TIMESTAMP="2026-08-12T00:00:00Z",
        )
        command = [
            sys.executable,
            str(ROOT / "scripts/prod_resilience_audit.py"),
            cli_env,
            "--evidence-dir",
            str(evidence),
        ]
        if require_parity:
            command.append("--require-parity")
        result = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
        return result, evidence

    return execute, log


@pytest.mark.parametrize(
    ("label", "scenario"),
    [
        ("invalid-env", {"cli_env": "staging"}),
        ("wrong-context", {"context": "sugar-dev"}),
        ("identity", {"identity_fail": True}),
        ("nodes", {"nodes": ["sugarkube0"]}),
    ],
)
def test_cli_identity_guards_fail_without_evidence(audit_harness, label, scenario) -> None:
    execute, _ = audit_harness
    result, evidence = execute(label, **scenario)
    assert result.returncode == 2
    assert not evidence.exists()
    assert "HARD_FAILURE:" in result.stderr


def test_cli_compliant_gap_determinism_sanitization_and_read_only_log(audit_harness) -> None:
    execute, log = audit_harness
    first, first_dir = execute("compliant-one")
    second, second_dir = execute("compliant-two")
    failed, failed_dir = execute("endpoint-error", failed_probe=True)
    assert first.returncode == second.returncode == failed.returncode == 0
    assert json.loads((first_dir / "audit.json").read_text())["result"] == "PARITY_OK"
    assert json.loads((failed_dir / "audit.json").read_text())["result"] == "PARITY_GAPS"
    assert {p.name for p in first_dir.iterdir()} == {
        "audit.json",
        "summary.md",
        "endpoints.tsv",
        "SHA256SUMS",
    }
    for name in ("audit.json", "summary.md", "endpoints.tsv", "SHA256SUMS"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()
    for line in (first_dir / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert digest == hashlib.sha256((first_dir / name).read_bytes()).hexdigest()
    combined = (
        first.stdout
        + first.stderr
        + failed.stdout
        + failed.stderr
        + "".join(
            path.read_text()
            for directory in (first_dir, failed_dir)
            for path in directory.iterdir()
        )
    )
    assert "SECRET-CANARY" not in combined
    assert "CONNECTOR-CANARY" not in combined
    endpoint_text = (failed_dir / "endpoints.tsv").read_text()
    assert "\tnone\n" in endpoint_text
    assert "\ttimeout\n" in endpoint_text

    commands = [json.loads(line) for line in log.read_text().splitlines()]
    forbidden = {
        "secret",
        "logs",
        "values",
        "apply",
        "delete",
        "patch",
        "exec",
        "port-forward",
        "rollout",
        "flux",
        "ssh",
        "sudo",
        "systemctl",
    }
    assert not any(forbidden.intersection(command) for command in commands)
    assert all(command[0] in {"kubectl", "helm", "curl", "git"} for command in commands)
    assert all(
        command[1] in {"config", "get", "--kubeconfig", "-n"}
        for command in commands
        if command[0] == "kubectl"
    )
    assert all((command[1] in {"list", "-n"}) for command in commands if command[0] == "helm")


def test_cli_completed_gap_exit_contract(audit_harness) -> None:
    execute, _ = audit_harness
    default, evidence = execute("gap-default", gap=True)
    required, required_evidence = execute("gap-required", gap=True, require_parity=True)
    assert default.returncode == 0
    assert required.returncode == 1
    assert json.loads((evidence / "audit.json").read_text())["result"] == "PARITY_GAPS"
    assert required_evidence.exists()
