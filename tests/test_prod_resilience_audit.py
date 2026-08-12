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


@pytest.mark.parametrize(
    "endpoint",
    [
        {"addresses": ["10.0.0.1"], "conditions": {"ready": "false"}},
        {"addresses": ["10.0.0.1"], "conditions": {"serving": 1}},
        {"addresses": ["10.0.0.1"], "conditions": {"terminating": None}},
        {"addresses": []},
        {"addresses": [""]},
        {"addresses": [1]},
        {"addresses": ["10.0.0.1"], "nodeName": ""},
        {"addresses": ["10.0.0.1"], "nodeName": 1},
        {"addresses": ["10.0.0.1"], "targetRef": []},
        {"addresses": ["10.0.0.1"], "targetRef": {"uid": 1}},
    ],
)
def test_endpoint_slices_reject_malformed_endpoint_fields(endpoint) -> None:
    with pytest.raises(audit.HardFailure, match="^malformed EndpointSlice entry$"):
        audit.endpoints(slices([[endpoint]]), "traefik")


def test_endpoint_target_api_version_is_part_of_duplicate_identity() -> None:
    common = {
        "addresses": ["10.0.0.1"],
        "nodeName": "a",
        "targetRef": {"kind": "Pod", "name": "pod", "uid": "uid"},
    }
    first = {**common, "targetRef": {**common["targetRef"], "apiVersion": "v1"}}
    second = {**common, "targetRef": {**common["targetRef"], "apiVersion": "v2"}}
    result = audit.endpoints(slices([[first, second]]), "traefik")
    assert result["uniqueEndpoints"] == result["healthyEndpoints"] == 2
    assert "apiVersion" not in json.dumps(result)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "error", "data": {"result": []}},
        {"status": "success", "data": []},
        {"status": "success", "data": {"result": {}}},
        {"status": "success", "data": {"result": [{"value": [0, "1"]}, {"value": [0, "2"]}]}},
        {"status": "success", "data": {"result": [{}]}},
        {"status": "success", "data": {"result": [{"value": [0]}]}},
        {"status": "success", "data": {"result": [{"value": ["bad", "1"]}]}},
        {"status": "success", "data": {"result": [{"value": [0, "1.5"]}]}},
        {"status": "success", "data": {"result": [{"value": [0, "-1"]}]}},
        {"status": "success", "data": {"result": [{"value": [0, "NaN"]}]}},
    ],
)
def test_prom_count_rejects_invalid_aggregates(monkeypatch, response) -> None:
    monkeypatch.setattr(audit, "kubectl", lambda *args: response)
    with pytest.raises(audit.HardFailure, match="^Prometheus returned an invalid aggregate$"):
        audit.prom_count("sum(up)")


@pytest.mark.parametrize(
    ("result", "expected"),
    [([], 0), ([{"metric": {"raw": "SECRET-CANARY"}, "value": [0, "2"]}], 2)],
)
def test_prom_count_accepts_valid_sanitized_aggregates(monkeypatch, result, expected) -> None:
    monkeypatch.setattr(
        audit, "kubectl", lambda *args: {"status": "success", "data": {"result": result}}
    )
    assert audit.prom_count("sum(up)") == expected


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


@pytest.mark.parametrize(
    "argv",
    [
        ["kubectl", "get", "secrets", "-A", "-o", "json"],
        ["kubectl", "-n", "default", "get", "secret", "token", "-o", "json"],
        ["kubectl", "get", "--raw", "/api/v1/namespaces/default/secrets"],
        ["kubectl", "get", "--raw", audit.PROMETHEUS_ALERT_RULES_PATH + "&x=1"],
        [
            "kubectl",
            "get",
            "--raw",
            audit.PROMETHEUS_ALERT_RULES_PATH.replace("monitoring", "default"),
        ],
        [
            "kubectl",
            "get",
            "--raw",
            audit.PROMETHEUS_ALERT_RULES_PATH.replace("type=alert", "type=record"),
        ],
        ["kubectl", "get", "nodes", "-o", "yaml"],
        ["kubectl", "get", "nodes", "-o", "json", "--show-labels"],
        ["kubectl", "get", "nodes", "--unknown"],
        ["helm", "list", "-A", "-o", "json", "--pending"],
        ["helm", "status", "release"],
        ["helm", "-n", "default", "status", "release", "-o", "json"],
        ["helm", "--namespace", "default", "status", "release", "-o", "json"],
        ["helm", "-n", "default", "status", "release", "-o", "json", "--show-resources"],
        ["helm", "-n", "default", "history", "release", "-o", "json", "--max", "1"],
    ],
)
def test_operation_rejects_non_allowlisted_read_shapes_before_execution(monkeypatch, argv) -> None:
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
        audit.run(["kubectl", "get", "nodes", "-o", "json"])

    message = str(caught.value)
    assert "exit 7" in message
    assert "kubectl/get" in message
    assert "permission denied" not in message
    assert "x" * 20 not in message
    assert len(message) < 100


def test_kubectl_rejects_malformed_json_shapes(monkeypatch) -> None:
    monkeypatch.setattr(
        audit,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="not-json"),
    )
    with pytest.raises(audit.HardFailure, match="malformed JSON"):
        audit.kubectl("get", "nodes")

    monkeypatch.setattr(
        audit,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="[]"),
    )
    with pytest.raises(audit.HardFailure, match="must be an object"):
        audit.kubectl("get", "nodes")


def test_empty_command_is_rejected() -> None:
    with pytest.raises(audit.HardFailure, match="empty command"):
        audit.operation([])


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


APPROVED_TRAEFIK_VALUES = """deployment:
  replicas: 2
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app.kubernetes.io/name: traefik
        topologyKey: kubernetes.io/hostname
secret: do-not-retain
"""


def test_traefik_desired_snapshot_never_retains_raw_values() -> None:
    result = audit.traefik_desired_snapshot(APPROVED_TRAEFIK_VALUES)
    assert result == {"replicas": 2, "requiredHostnameAntiAffinity": True}
    assert "do-not-retain" not in json.dumps(result)


@pytest.mark.parametrize(
    "content",
    [
        "unrelated:\n  replicas: 2\n",
        "deployment:\n  replicas: 2\naffinity:\n  requiredDuringSchedulingIgnoredDuringExecution:\n    app.kubernetes.io/name: traefik\n    topologyKey: kubernetes.io/hostname\n",
        APPROVED_TRAEFIK_VALUES.replace(
            "        topologyKey: kubernetes.io/hostname",
            "      - topologyKey: kubernetes.io/hostname",
        ),
        APPROVED_TRAEFIK_VALUES.replace("traefik", "not-traefik"),
        APPROVED_TRAEFIK_VALUES.replace("kubernetes.io/hostname", "topology.kubernetes.io/zone"),
        APPROVED_TRAEFIK_VALUES + "deployment:\n  replicas: 2\n",
        APPROVED_TRAEFIK_VALUES.replace(
            "    requiredDuringSchedulingIgnoredDuringExecution:",
            "    requiredDuringSchedulingIgnoredDuringExecution:\n"
            "      - labelSelector:\n"
            "          matchLabels:\n"
            "            app.kubernetes.io/name: traefik\n"
            "        topologyKey: kubernetes.io/hostname\n"
            "    requiredDuringSchedulingIgnoredDuringExecution:",
        ),
    ],
)
def test_traefik_desired_snapshot_rejects_decoys_and_ambiguity(content) -> None:
    assert audit.traefik_desired_snapshot(content) != {
        "replicas": 2,
        "requiredHostnameAntiAffinity": True,
    }


@pytest.mark.parametrize(
    "term, unrelated",
    [
        (
            "      - labelSelector: {}\n",
            "  labelSelector:\n"
            "    matchLabels:\n"
            "      app.kubernetes.io/name: traefik\n"
            "  topologyKey: kubernetes.io/hostname\n",
        ),
        (
            "      - labelSelector:\n"
            "          matchLabels:\n"
            "            app.kubernetes.io/name: traefik\n",
            "  topologyKey: kubernetes.io/hostname\n",
        ),
        (
            "      - topologyKey: kubernetes.io/hostname\n",
            "  labelSelector:\n" "    matchLabels:\n" "      app.kubernetes.io/name: traefik\n",
        ),
    ],
)
def test_traefik_desired_snapshot_does_not_complete_term_after_dedent(term, unrelated) -> None:
    content = (
        "deployment:\n"
        "  replicas: 2\n"
        "affinity:\n"
        "  podAntiAffinity:\n"
        "    requiredDuringSchedulingIgnoredDuringExecution:\n"
        f"{term}"
        "unrelated:\n"
        f"{unrelated}"
    )

    assert audit.traefik_desired_snapshot(content) == {
        "replicas": 2,
        "requiredHostnameAntiAffinity": False,
    }


FAKE_TOOL = r"""#!/usr/bin/python3 -S
import json, os, sys, time
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
                    "status": {"conditions": [{"type": "Ready", "status":
                               "False" if state.get("nodes_unready") and n == "sugarkube0"
                               else "True"}]}}
                   for n in node_names]}
if tool == "git":
    emit("0123456789abcdef0123456789abcdef01234567"); raise SystemExit()
if tool == "curl":
    print("credential=SECRET-CANARY connector=CONNECTOR-CANARY", file=sys.stderr)
    if state.get("timeout_isolation"):
        marker = Path(os.environ["AUDIT_TIMEOUT_MARKER"])
        if args[-1] == "https://danielsmith.io/":
            for _ in range(100):
                if marker.exists():
                    Path(os.environ["AUDIT_TIMEOUT_OBSERVED"]).write_text("observed")
                    emit("000\t0.01\t0.00\t0.02"); raise SystemExit(28)
                time.sleep(0.01)
            emit("000\t0.01\t0.00\t0.02"); raise SystemExit(9)
        marker.write_text("FAST-BODY-CANARY SECRET-CANARY CONNECTOR-CANARY")
    if state.get("failed_probe") and args[-1].endswith("/healthz"):
        emit("000\t0.01\t0.00\t0.02"); raise SystemExit(28)
    emit("204\t0.01\t0.02\t0.03"); raise SystemExit()
if tool == "helm":
    clean = args[2:] if args[:1] in (["-n"], ["--namespace"]) else args
    if clean[0] == "list":
        if state.get("malformed_helm"):
            emit(["credential=SECRET-CANARY connector=CONNECTOR-CANARY"]); raise SystemExit()
        releases = [{ "name": "cloudflare", "namespace": "cloudflare",
                "status": state.get("helm_list_status", "deployed"),
                "chart": "cloudflare-tunnel-0.3.2", "app_version": "2026.7.3",
                "revision": state.get("helm_revision", 2 if state.get("reverse_order") else "2"),
                "config": "credential=SECRET-CANARY", "manifest": "CONNECTOR-CANARY"}]
        if state.get("multiple_candidates"):
            releases.append({**releases[0], "name": "cloudflare-second"})
        emit(releases)
    elif clean[0] == "history":
        revision = (lambda value: str(value)) if state.get("reverse_order") else (lambda value: value)
        entries = [
            {"revision": revision(1), "updated": "older", "status": "superseded",
             "chart": "cloudflare-tunnel-0.3.1", "app_version": "2026.7.2"},
            {"revision": revision(2), "updated": "fixed",
             "status": state.get("helm_history_status", "deployed"),
             "chart": "cloudflare-tunnel-0.3.2", "app_version": "2026.7.3",
             "config": "credential=SECRET-CANARY", "manifest": "CONNECTOR-CANARY"},
        ]
        if state.get("helm_history_missing"):
            entries[1]["revision"] = revision(3)
        if state.get("helm_history_duplicate"):
            entries.append(dict(entries[1]))
        if state.get("reverse_order"):
            entries.reverse()
        emit(entries)
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
    if state.get("malformed_nodes"):
        emit({"items": [{"metadata": "credential=SECRET-CANARY connector=CONNECTOR-CANARY"}]})
        raise SystemExit()
    emit(nodes); raise SystemExit()
if args[:3] == ["config", "view", "--minify"]:
    emit("https://sanitized.invalid"); raise SystemExit()
if args[:3] == ["get", "--raw", "/readyz?verbose"]:
    emit("readyz check failed\n[-]etcd failed" if state.get("readyz_failed") else
         "readyz check passed\n[+]etcd ok"); raise SystemExit()
if args[:2] == ["get", "--raw"]:
    if args[2].endswith("/api/v1/rules?type=alert"):
        if state.get("alert_malformed"):
            emit({"status": "success", "data": {"groups": "credential=SECRET-CANARY"}})
            raise SystemExit()
        rules = [
            {"name": "CloudflareTunnelNoHealthyConnections", "health": "ok"},
            {"name": "CloudflareTunnelConnectionsDegraded", "health": "ok"},
            {"name": "CloudflareTunnelMetricsTargetsDown", "health": "ok"},
        ]
        if state.get("alert_missing"):
            rules.pop()
        if state.get("alert_unhealthy"):
            rules[0]["health"] = "err"
        if state.get("alert_duplicate"):
            rules.append(dict(rules[0]))
        for rule in rules:
            rule.update({"query": "credential=SECRET-CANARY", "labels": {"connector": "CONNECTOR-CANARY"},
                         "annotations": {"description": "SECRET-CANARY"}})
        emit({"status": "success", "data": {"groups": [{"rules": rules}]}})
        raise SystemExit()
    if state.get("prom_invalid"):
        response = {"data": {"result": [
            {"metric": {"connector": "CONNECTOR-CANARY"},
             "value": [0, "credential=SECRET-CANARY"]}]}}
        if not state.get("prom_missing_status"):
            response["status"] = "error"
        emit(response)
        raise SystemExit()
    if "ALERTS" in args[2]:
        count = 0
    elif "cloudflared_tunnel_ha_connections" in args[2]:
        count = state.get("ha_connections", 2)
    else:
        count = state.get("healthy_targets", 2)
    emit({"status": "success", "data": {"result": [
        {"metric": {"connector": "CONNECTOR-CANARY", "credential": "SECRET-CANARY"},
         "value": [0, str(count)]}]}}); raise SystemExit()

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
def pod(uid, node, ready=True):
    return {"metadata": {"uid": uid}, "spec": {"nodeName": node},
            "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                       "containerStatuses": [{"restartCount": 0}]}}
def deployment(dep_name, labels_, affinity):
    container = {"name": dep_name, "image": "unused"}
    if dep_name == "cloudflare":
        container = {"name": "cloudflared", "image": os.environ["AUDIT_EXPECTED_IMAGE"],
                     "readinessProbe": {"httpGet": {"path": "/ready", "port": 2000}}}
        if state.get("image_unpinned"):
            container["image"] = "cloudflare/cloudflared:latest"
        if state.get("probe_path_wrong"):
            container["readinessProbe"]["httpGet"]["path"] = "/wrong"
        if state.get("probe_port_wrong"):
            container["readinessProbe"]["httpGet"]["port"] = 2001
        if state.get("liveness_probe"):
            container["livenessProbe"] = {"httpGet": {"path": "/ready", "port": 2000}}
    return {"metadata": {"name": dep_name, "namespace": ns or "cloudflare", "uid": dep_name,
                         "generation": 1, "labels": dict(labels_)},
            "spec": {"replicas": 2, "selector": {"matchLabels": dict(labels_)},
                     "strategy": {"rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
                     "template": {"metadata": {"labels": dict(labels_)},
                                  "spec": {"affinity": affinity, "containers": [container]}}},
            "status": {"readyReplicas": 2, "availableReplicas": 2}}
if kind == "deployment" and args[2:3] == ["-A"]:
    dep = deployment("cloudflare", pod_labels, anti)
    dep["metadata"]["labels"]["app.kubernetes.io/name"] = "cloudflare-tunnel"
    dep["metadata"]["labels"]["app.kubernetes.io/instance"] = "cloudflare"
    dep["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "Helm"
    dep["metadata"]["labels"]["canary-label"] = "CONNECTOR-CANARY"
    dep["metadata"]["annotations"] = {
        "meta.helm.sh/release-name": "cloudflare",
        "meta.helm.sh/release-namespace": "cloudflare",
        "canary-annotation": "SECRET-CANARY",
    }
    ownership = state.get("ownership")
    if ownership == "missing-managed-by":
        dep["metadata"]["labels"].pop("app.kubernetes.io/managed-by")
    elif ownership == "flux-managed":
        dep["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "Flux"
    elif ownership == "missing-release-name":
        dep["metadata"]["annotations"].pop("meta.helm.sh/release-name")
    elif ownership == "wrong-release-namespace":
        dep["metadata"]["annotations"]["meta.helm.sh/release-namespace"] = "other"
    elif ownership == "conflicting-instance":
        dep["metadata"]["labels"]["app.kubernetes.io/instance"] = "other"
    items = [dep]
    if state.get("dormant_flux"):
        flux = deployment("dormant-flux", pod_labels, anti)
        flux["metadata"]["labels"].update({"app.kubernetes.io/name": "cloudflare-tunnel",
                                             "app.kubernetes.io/instance": "cloudflare",
                                             "app.kubernetes.io/managed-by": "Flux",
                                             "flux-canary": "CONNECTOR-CANARY"})
        items.append(flux)
    if state.get("multiple_candidates"):
        second = deployment("cloudflare-second", pod_labels, anti)
        second["metadata"]["labels"].update({"app.kubernetes.io/name": "cloudflare-tunnel",
                                               "app.kubernetes.io/instance": "cloudflare-second",
                                               "app.kubernetes.io/managed-by": "Helm"})
        second["metadata"]["annotations"] = {
            "meta.helm.sh/release-name": "cloudflare-second",
            "meta.helm.sh/release-namespace": "cloudflare",
        }
        items.append(second)
    emit({"items": [] if state.get("zero_candidates") else items}); raise SystemExit()
if kind == "deployment" and name in ("coredns", "coredns-ha", "traefik"):
    if state.get("missing_component") == name:
        emit({}); raise SystemExit()
    lab = {"app.kubernetes.io/name": name}
    emit(deployment(name, lab, traefik_anti if name == "traefik" else anti)); raise SystemExit()
if kind == "pods":
    selector = next((value for value in args if "=" in value), "")
    component = "cloudflare" if ns == "cloudflare" else selector.rsplit("=", 1)[-1]
    selected = state.get("pod_component")
    applies = selected == component or (selected == "coredns" and component.startswith("coredns"))
    mode = state.get("pod_mode") if applies else None
    if state.get("gap") and ns == "kube-system":
        mode = "singleton"
    items = [pod("a", "sugarkube0")]
    if mode != "singleton":
        items.append(pod("b", "sugarkube0" if mode == "unspread" else "sugarkube1",
                         ready=mode != "unhealthy"))
    emit({"items": items})
elif kind == "pdb":
    pdb_selector = {"other": "workload"} if state.get("pdb_selector_mismatch") else pod_labels
    pdb_items = [
        {"metadata": {"name": "cloudflare-pdb"},
         "spec": {"selector": {"matchLabels": pdb_selector}, "minAvailable": 1}},
        {"metadata": {"name": "cloudflare-pdb-secondary"},
         "spec": {"selector": {"matchLabels": pdb_selector}, "minAvailable": 1}},
    ]
    if state.get("reverse_order"):
        pdb_items.reverse()
    emit({"items": [] if ns == "kube-system" else pdb_items})
elif kind == "endpointslices.discovery.k8s.io":
    service = next(x.split("=", 1)[1] for x in args if x.startswith("kubernetes.io/service-name="))
    insufficient = state.get("endpoint_insufficient") == service
    emit({"items": [{"metadata": {"labels": {"kubernetes.io/service-name": service}},
                     "endpoints": [{"addresses": ["10.0.0.1"], "nodeName": "sugarkube0", "conditions": {}},
                                   {"addresses": ["10.0.0.2"], "nodeName":
                                    "sugarkube0" if insufficient else "sugarkube1",
                                    "conditions": {}}]}]})
elif kind == "service" and name == "traefik":
    emit({"spec": {} if state.get("traffic_policy_absent") else
          {"internalTrafficPolicy": state.get("traffic_policy", "Cluster")}})
elif kind == "helmchartconfig":
    emit({"metadata": {"uid": "hcc"}, "spec": {"valuesContent":
          "deployment:\n  replicas: 2\naffinity:\n  podAntiAffinity:\n"
          "    requiredDuringSchedulingIgnoredDuringExecution:\n      - labelSelector:\n"
          "          matchLabels:\n            app.kubernetes.io/name: traefik\n"
          "        topologyKey: kubernetes.io/hostname\n"}})
elif kind == "service":
    service_items = [
        {"metadata": {"name": "cloudflare-metrics", "labels": {"monitor": "cloudflare"}},
         "spec": {"selector": ({"other": "workload"}
                                 if state.get("service_selector_mismatch") else pod_labels),
                  "ports": [{"name": "metrics", "port": (9090 if state.get("port_mismatch") else 2000),
                             "targetPort": 2000}]}},
        {"metadata": {"name": "unrelated-metrics", "labels": {"monitor": "unrelated"}},
         "spec": {"selector": {"other": "workload"},
                  "ports": [{"name": "metrics", "port": 9090, "targetPort": 9090}]}},
    ]
    if state.get("reverse_order"):
        service_items.reverse()
    emit({"items": service_items})
elif kind == "servicemonitor":
    monitor_items = [
        {"metadata": {"name": "cloudflare"},
         "spec": {"selector": {"matchLabels": ({"other": "service"}
                          if state.get("monitor_selector_mismatch") else {"monitor": "cloudflare"})},
                  "namespaceSelector": {"matchNames": ["other" if state.get("namespace_mismatch") else "cloudflare"]},
                  "endpoints": [{"port": "metrics", "path": ("/wrong" if state.get("path_mismatch") else "/metrics")}]}},
        {"metadata": {"name": "unrelated"},
         "spec": {"selector": {"matchLabels": {"monitor": "unrelated"}},
                  "namespaceSelector": {"matchNames": ["other"]},
                  "endpoints": [{"port": "other", "path": "/other"}]}},
    ]
    if state.get("reverse_order"):
        monitor_items.reverse()
    emit({"items": monitor_items})
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

    def configure(label, *, cli_env="prod", require_parity=False, **scenario):
        state.write_text(json.dumps(scenario))
        evidence = tmp_path / label
        env = os.environ.copy()
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
            KUBECONFIG=str(tmp_path / "kubeconfig"),
            AUDIT_FAKE_STATE=str(state),
            AUDIT_COMMAND_LOG=str(log),
            AUDIT_EXPECTED_IMAGE=audit.EXPECTED_IMAGE,
            AUDIT_TIMEOUT_MARKER=str(tmp_path / "timeout-marker-SECRET-CANARY"),
            AUDIT_TIMEOUT_OBSERVED=str(tmp_path / "timeout-observed-CONNECTOR-CANARY"),
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
        return command, env, evidence

    def execute(label, *, cli_env="prod", require_parity=False, **scenario):
        command, env, evidence = configure(
            label, cli_env=cli_env, require_parity=require_parity, **scenario
        )
        result = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
        return result, evidence

    execute.configure = configure
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
    second, second_dir = execute("compliant-two", reverse_order=True)
    failed, failed_dir = execute("endpoint-error", failed_probe=True)
    assert first.returncode == second.returncode == failed.returncode == 0
    first_audit = json.loads((first_dir / "audit.json").read_text())
    assert first_audit["result"] == "PARITY_OK"
    tunnel = first_audit["observed"]["cloudflareTunnel"]
    assert tunnel["revision"] == 2
    assert [record["revision"] for record in tunnel["history"]] == [1, 2]
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
    assert not any(command[0] == "helm" and "status" in command for command in commands)


def test_cli_completed_gap_exit_contract(audit_harness) -> None:
    execute, _ = audit_harness
    default, evidence = execute("gap-default", gap=True)
    required, required_evidence = execute("gap-required", gap=True, require_parity=True)
    assert default.returncode == 0
    assert required.returncode == 1
    assert json.loads((evidence / "audit.json").read_text())["result"] == "PARITY_GAPS"
    assert required_evidence.exists()


@pytest.mark.parametrize(
    ("scenario", "added_gaps"),
    [
        ({"missing_component": "coredns"}, {"COREDNS_MISSING"}),
        ({"missing_component": "coredns-ha"}, {"COREDNS_HA_MISSING"}),
        (
            {"missing_component": "traefik"},
            {
                "TRAEFIK_MISSING",
                "TRAEFIK_SINGLETON",
                "TRAEFIK_UNSPREAD",
                "TRAEFIK_SCHEDULING_CONTRACT_MISMATCH",
            },
        ),
        (
            {
                "missing_component": "coredns-ha",
                "pod_component": "coredns",
                "pod_mode": "singleton",
            },
            {"COREDNS_HA_MISSING", "COREDNS_SINGLETON", "COREDNS_UNSPREAD"},
        ),
        (
            {"pod_component": "traefik", "pod_mode": "singleton"},
            {"TRAEFIK_SINGLETON", "TRAEFIK_UNSPREAD"},
        ),
        (
            {"pod_component": "cloudflare", "pod_mode": "singleton"},
            {"CF_CONNECTORS_INSUFFICIENT", "CF_CONNECTORS_UNSPREAD"},
        ),
        ({"pod_component": "coredns", "pod_mode": "unspread"}, {"COREDNS_UNSPREAD"}),
        ({"pod_component": "traefik", "pod_mode": "unspread"}, {"TRAEFIK_UNSPREAD"}),
        (
            {"pod_component": "cloudflare", "pod_mode": "unspread"},
            {"CF_CONNECTORS_UNSPREAD"},
        ),
        ({"nodes_unready": True}, {"NODE_NOT_READY"}),
        ({"readyz_failed": True}, {"API_OR_ETCD_NOT_READY"}),
        (
            {
                "missing_component": "coredns-ha",
                "pod_component": "coredns",
                "pod_mode": "unhealthy",
            },
            {"COREDNS_HA_MISSING", "COREDNS_SINGLETON", "COREDNS_UNSPREAD"},
        ),
        (
            {"pod_component": "traefik", "pod_mode": "unhealthy"},
            {"TRAEFIK_SINGLETON", "TRAEFIK_UNSPREAD"},
        ),
        (
            {"pod_component": "cloudflare", "pod_mode": "unhealthy"},
            {"CF_CONNECTORS_INSUFFICIENT", "CF_CONNECTORS_UNSPREAD"},
        ),
        ({"endpoint_insufficient": "kube-dns"}, {"KUBE_DNS_ENDPOINTS_INSUFFICIENT"}),
        ({"endpoint_insufficient": "traefik"}, {"TRAEFIK_ENDPOINTS_INSUFFICIENT"}),
        ({"image_unpinned": True}, {"CF_IMAGE_NOT_IMMUTABLE_PIN"}),
        ({"probe_path_wrong": True}, {"CF_PROBE_CONTRACT"}),
        ({"probe_port_wrong": True}, {"CF_PROBE_CONTRACT"}),
        ({"liveness_probe": True}, {"CF_PROBE_CONTRACT"}),
        ({"healthy_targets": 1}, {"CF_METRICS_TARGETS_UNHEALTHY"}),
        ({"ha_connections": 1}, {"CF_HA_CONNECTIONS_INSUFFICIENT"}),
    ],
    ids=[
        "missing-coredns",
        "missing-coredns-ha",
        "missing-traefik",
        "singleton-coredns",
        "singleton-traefik",
        "singleton-cloudflare",
        "unspread-coredns",
        "unspread-traefik",
        "unspread-cloudflare",
        "unready-node",
        "api-etcd-unready",
        "unready-coredns-pod",
        "unready-traefik-pod",
        "unready-cloudflare-pod",
        "kube-dns-endpoints",
        "traefik-endpoints",
        "cloudflare-image",
        "probe-path",
        "probe-port",
        "liveness-probe",
        "prometheus-targets",
        "prometheus-ha",
    ],
)
def test_cli_prompt_gap_matrix(audit_harness, scenario, added_gaps) -> None:
    execute, _ = audit_harness
    baseline_result, baseline_dir = execute("matrix-compliant")
    baseline = json.loads((baseline_dir / "audit.json").read_text())
    assert baseline_result.returncode == 0
    assert baseline["result"] == "PARITY_OK"
    assert baseline["gaps"] == []
    assert baseline["gapCount"] == 0

    result, evidence = execute("matrix-" + next(iter(scenario)), **scenario)
    document = json.loads((evidence / "audit.json").read_text())
    assert result.returncode == 0
    assert set(document["gaps"]) - set(baseline["gaps"]) == added_gaps
    assert document["gapCount"] == len(added_gaps)


def test_cli_endpoint_timeout_isolation_is_concurrent_and_sanitized(audit_harness) -> None:
    execute, _ = audit_harness
    command, env, evidence = execute.configure("timeout-isolation", timeout_isolation=True)
    result = subprocess.run(
        command, text=True, capture_output=True, env=env, check=False, timeout=15
    )

    assert result.returncode == 0
    rows = (evidence / "endpoints.tsv").read_text().splitlines()
    assert any(
        row.startswith("https://danielsmith.io/\t0\t") and row.endswith("\ttimeout") for row in rows
    )
    assert any(row.endswith("\tnone") for row in rows)
    assert Path(env["AUDIT_TIMEOUT_OBSERVED"]).read_text() == "observed"
    combined = (
        result.stdout + result.stderr + "".join(path.read_text() for path in evidence.iterdir())
    )
    for canary in (
        "SECRET-CANARY",
        "CONNECTOR-CANARY",
        "FAST-BODY-CANARY",
        env["AUDIT_TIMEOUT_MARKER"],
        env["AUDIT_TIMEOUT_OBSERVED"],
    ):
        assert canary not in combined


@pytest.mark.parametrize(
    "scenario", [{"prom_invalid": True}, {"prom_invalid": True, "prom_missing_status": True}]
)
def test_cli_invalid_prometheus_aggregate_is_sanitized_hard_failure(
    audit_harness, scenario
) -> None:
    execute, _ = audit_harness
    result, evidence = execute("prometheus-invalid-" + str(scenario), **scenario)
    combined = result.stdout + result.stderr
    assert result.returncode == 2
    assert result.stderr == "HARD_FAILURE: Prometheus returned an invalid aggregate\n"
    assert "SECRET-CANARY" not in combined
    assert "CONNECTOR-CANARY" not in combined
    assert not evidence.exists()


def test_cli_cloudflare_evidence_proves_sanitized_helm_ownership_and_bindings(
    audit_harness,
) -> None:
    execute, _ = audit_harness
    result, evidence = execute("ownership-evidence")
    assert result.returncode == 0
    tunnel = json.loads((evidence / "audit.json").read_text())["observed"]["cloudflareTunnel"]
    assert tunnel["helmOwnership"] == {
        "managedBy": "Helm",
        "releaseName": "cloudflare",
        "releaseNamespace": "cloudflare",
        "managedByHelm": True,
        "instanceMatchesRelease": True,
        "namespaceMatchesDeployment": True,
        "matchesUniqueHelmRelease": True,
    }
    assert tunnel["pdb"] == [
        {
            "name": "cloudflare-pdb",
            "minAvailable": 1,
            "maxUnavailable": None,
            "selectorTargetsWorkload": True,
        },
        {
            "name": "cloudflare-pdb-secondary",
            "minAvailable": 1,
            "maxUnavailable": None,
            "selectorTargetsWorkload": True,
        },
    ]
    assert tunnel["metrics"] == {
        "services": [
            {
                "name": "cloudflare-metrics",
                "type": "ClusterIP",
                "selectorTargetsWorkload": True,
                "metricsPortName": "metrics",
                "port": 2000,
                "targetPort": 2000,
            },
            {
                "name": "unrelated-metrics",
                "type": "ClusterIP",
                "selectorTargetsWorkload": False,
                "metricsPortName": "metrics",
                "port": 9090,
                "targetPort": 9090,
            },
        ],
        "serviceMonitors": [
            {
                "name": "cloudflare",
                "selectorTargetsService": True,
                "namespaceTargetsRelease": True,
                "endpointPort": "metrics",
                "endpointPath": "/metrics",
            },
            {
                "name": "unrelated",
                "selectorTargetsService": False,
                "namespaceTargetsRelease": False,
                "endpointPort": "other",
                "endpointPath": "/other",
            },
        ],
    }
    encoded = "".join(path.read_text() for path in evidence.iterdir())
    assert "canary-label" not in encoded
    assert "canary-annotation" not in encoded
    assert "SECRET-CANARY" not in encoded
    assert "CONNECTOR-CANARY" not in encoded


@pytest.mark.parametrize(
    "ownership",
    [
        "missing-managed-by",
        "flux-managed",
        "missing-release-name",
        "wrong-release-namespace",
        "conflicting-instance",
    ],
)
def test_cli_invalid_ownership_cannot_become_release_candidate(audit_harness, ownership) -> None:
    execute, _ = audit_harness
    result, evidence = execute("invalid-ownership-" + ownership, ownership=ownership)
    assert result.returncode == 2
    assert (
        result.stderr
        == "HARD_FAILURE: expected exactly one live Cloudflare release candidate; found 0\n"
    )
    assert not evidence.exists()


def test_cli_dormant_flux_deployment_is_ignored(audit_harness) -> None:
    execute, _ = audit_harness
    result, evidence = execute("dormant-flux", dormant_flux=True)
    assert result.returncode == 0
    encoded = "".join(path.read_text() for path in evidence.iterdir())
    assert '"managedBy": "Helm"' in encoded
    assert "Flux" not in encoded
    assert "CONNECTOR-CANARY" not in encoded


@pytest.mark.parametrize(
    ("scenario", "count"), [({"zero_candidates": True}, 0), ({"multiple_candidates": True}, 2)]
)
def test_cli_candidate_cardinality_is_a_sanitized_hard_failure(
    audit_harness, scenario, count
) -> None:
    execute, _ = audit_harness
    result, evidence = execute("candidate-cardinality-" + str(count), **scenario)
    assert result.returncode == 2
    assert result.stderr == (
        f"HARD_FAILURE: expected exactly one live Cloudflare release candidate; found {count}\n"
    )
    assert not evidence.exists()


@pytest.mark.parametrize(
    ("scenario", "gap"),
    [
        ({"pdb_selector_mismatch": True}, "CF_PDB_MISSING"),
        ({"service_selector_mismatch": True}, "CF_METRICS_DISCOVERY_MISSING"),
        ({"monitor_selector_mismatch": True}, "CF_METRICS_DISCOVERY_MISSING"),
        ({"port_mismatch": True}, "CF_METRICS_DISCOVERY_MISSING"),
        ({"namespace_mismatch": True}, "CF_METRICS_DISCOVERY_MISSING"),
        ({"path_mismatch": True}, "CF_METRICS_DISCOVERY_MISSING"),
    ],
)
def test_cli_resource_binding_mismatches_retain_stable_gaps(audit_harness, scenario, gap) -> None:
    execute, _ = audit_harness
    result, evidence = execute("binding-mismatch-" + next(iter(scenario)), **scenario)
    assert result.returncode == 0
    assert gap in json.loads((evidence / "audit.json").read_text())["gaps"]


@pytest.mark.parametrize(
    "scenario",
    [{"traffic_policy_absent": True}, {"traffic_policy": "Cluster"}, {"traffic_policy": "Local"}],
)
def test_cli_traffic_policy_is_observed_without_an_unsupported_gap(audit_harness, scenario) -> None:
    execute, _ = audit_harness
    result, evidence = execute("traffic-policy-" + str(scenario), **scenario)
    assert result.returncode == 0
    document = json.loads((evidence / "audit.json").read_text())
    assert "TRAEFIK_TRAFFIC_POLICY_MISMATCH" not in document["gaps"]
    assert document["observed"]["traefikService"]["internalTrafficPolicy"] == scenario.get(
        "traffic_policy", "Cluster"
    )


@pytest.mark.parametrize("scenario", [{}, {"helm_revision": 2}])
def test_cli_helm_list_and_current_history_deployed_pass(audit_harness, scenario) -> None:
    execute, _ = audit_harness
    result, evidence = execute("helm-deployed-" + str(scenario), **scenario)
    assert result.returncode == 0
    document = json.loads((evidence / "audit.json").read_text())
    assert "CF_HELM_RELEASE_NOT_DEPLOYED" not in document["gaps"]
    tunnel = document["observed"]["cloudflareTunnel"]
    assert tunnel["helmListStatus"] == "deployed"
    assert tunnel["helmCurrentHistoryStatus"] == "deployed"
    assert "helmStatus" not in tunnel


@pytest.mark.parametrize(
    "scenario",
    [
        {"helm_list_status": "failed"},
        {"helm_list_status": "pending-upgrade"},
        {"helm_history_status": "failed"},
        {"helm_history_status": "pending-upgrade"},
    ],
)
def test_cli_helm_non_deployed_status_is_a_gap(audit_harness, scenario) -> None:
    execute, _ = audit_harness
    result, evidence = execute("helm-status-gap-" + str(scenario), **scenario)
    assert result.returncode == 0
    assert (
        "CF_HELM_RELEASE_NOT_DEPLOYED" in json.loads((evidence / "audit.json").read_text())["gaps"]
    )


@pytest.mark.parametrize(
    "scenario", [{"helm_history_missing": True}, {"helm_history_duplicate": True}]
)
def test_cli_current_helm_history_revision_must_be_unique_and_sanitized(
    audit_harness, scenario
) -> None:
    execute, _ = audit_harness
    result, evidence = execute("helm-history-" + str(scenario), **scenario)
    assert result.returncode == 2
    assert (
        result.stderr.strip()
        == "HARD_FAILURE: unable to identify unique current Helm history revision"
    )
    assert not evidence.exists()
    combined = result.stdout + result.stderr
    for canary in ("SECRET-CANARY", "CONNECTOR-CANARY", "credential", "manifest"):
        assert canary not in combined


@pytest.mark.parametrize("scenario", [{"malformed_nodes": True}, {"malformed_helm": True}])
def test_cli_malformed_external_shapes_are_sanitized(audit_harness, scenario) -> None:
    execute, _ = audit_harness
    result, evidence = execute("malformed-" + next(iter(scenario)), **scenario)
    assert result.returncode == 2
    assert not evidence.exists()
    combined = result.stdout + result.stderr
    assert "HARD_FAILURE:" in result.stderr
    assert "Traceback" not in combined
    assert "SECRET-CANARY" not in combined
    assert "CONNECTOR-CANARY" not in combined


def test_cli_filesystem_failure_is_generic_and_leaves_no_partial_evidence(
    audit_harness, monkeypatch, capsys
) -> None:
    execute, _ = audit_harness
    command, env, evidence = execute.configure("filesystem-failure")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    original_write_text = Path.write_text

    def fail_audit_write(path, *args, **kwargs):
        if path.name == "audit.json":
            raise OSError("FILESYSTEM-CANARY /private/path")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_audit_write)
    assert audit.cli(command[2:]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "HARD_FAILURE: unexpected collection failure"
    assert "FILESYSTEM-CANARY" not in captured.out + captured.err
    assert not evidence.exists()
    assert not list(evidence.parent.glob(".prod-audit-*"))


def test_cli_boundary_does_not_catch_keyboard_interrupt(monkeypatch) -> None:
    def interrupted(argv=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(audit, "main", interrupted)
    with pytest.raises(KeyboardInterrupt):
        audit.cli([])


@pytest.mark.parametrize(
    ("scenario", "gap"),
    [
        ({}, None),
        ({"alert_missing": True}, "CF_ALERT_RULE_SET_MISMATCH"),
        ({"alert_duplicate": True}, "CF_ALERT_RULE_SET_MISMATCH"),
        ({"alert_unhealthy": True}, "CF_ALERT_RULES_UNHEALTHY"),
    ],
)
def test_cli_alert_rule_parity_is_sanitized(audit_harness, scenario, gap) -> None:
    execute, _ = audit_harness
    result, evidence = execute("alerts-" + (gap or "healthy") + str(scenario), **scenario)
    assert result.returncode == 0
    document = json.loads((evidence / "audit.json").read_text())
    assert (
        (gap in document["gaps"])
        if gap
        else not any(code.startswith("CF_ALERT_RULE") for code in document["gaps"])
    )
    combined = (
        result.stdout + result.stderr + "".join(path.read_text() for path in evidence.iterdir())
    )
    for canary in ("SECRET-CANARY", "CONNECTOR-CANARY", "credential", "annotations", "query"):
        assert canary not in combined


def test_cli_malformed_alert_rules_are_a_sanitized_hard_failure(audit_harness) -> None:
    execute, _ = audit_harness
    result, evidence = execute("alerts-malformed", alert_malformed=True)
    assert result.returncode == 2
    assert not evidence.exists()
    assert result.stderr.strip() == "HARD_FAILURE: Prometheus returned malformed alert rules"
    assert "SECRET-CANARY" not in result.stdout + result.stderr


def test_cli_compliant_fixture_covers_in_process_collection(audit_harness, monkeypatch) -> None:
    """Exercise collector branches in-process so patch coverage observes the CLI work."""
    execute, _ = audit_harness
    command, env, evidence = execute.configure("covered-compliant")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", command[1:])

    assert audit.main() == 0
    assert json.loads((evidence / "audit.json").read_text())["result"] == "PARITY_OK"
