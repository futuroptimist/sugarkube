#!/usr/bin/env python3
"""Collect a sanitized, strictly read-only production resilience inventory."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NODES = {"sugarkube0", "sugarkube1", "sugarkube2"}
EXPECTED_IMAGE = (
    "cloudflare/cloudflared:2026.7.3@sha256:"
    "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)
TARGETS = ROOT / "config/prod-resilience-audit-targets.json"
MAX_PROBE_WORKERS = 8
PROMETHEUS_ALERT_RULES_PATH = (
    "/api/v1/namespaces/monitoring/services/"
    "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/rules?type=alert"
)
EXPECTED_CLOUDFLARE_ALERT_RULES = (
    "CloudflareTunnelConnectionsDegraded",
    "CloudflareTunnelMetricsTargetsDown",
    "CloudflareTunnelNoHealthyConnections",
)


class HardFailure(RuntimeError):
    pass


def object_shape(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HardFailure(message)
    return value


def list_shape(value: Any, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise HardFailure(message)
    return value


def operation(argv: list[str]) -> str:
    """Return a safe operation identifier or reject before process execution."""
    if not argv:
        raise HardFailure("internal safety policy rejected an empty command")
    args = argv[1:]
    if argv[0] == "kubectl":
        if args == ["config", "current-context"]:
            return "kubectl/config-current-context"
        namespace = None
        if len(args) >= 2 and args[0] in ("-n", "--namespace"):
            namespace, args = args[1], args[2:]
            if not re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", namespace):
                raise HardFailure("internal safety policy rejected a non-allowlisted operation")
        if namespace is None and args == ["get", "nodes", "-o", "json"]:
            return "kubectl/get"
        if namespace is None and args == [
            "get",
            "deployment",
            "-A",
            "-l",
            "app.kubernetes.io/name=cloudflare-tunnel",
            "-o",
            "json",
        ]:
            return "kubectl/get"
        if args[:2] == ["get", "--raw"] and len(args) == 3:
            path = args[2]
            if namespace is None and path == "/readyz?verbose":
                return "kubectl/get-raw-readyz"
            if namespace is None and path == PROMETHEUS_ALERT_RULES_PATH:
                return "kubectl/get-raw-prometheus-alert-rules"
            prom_prefix = (
                "/api/v1/namespaces/monitoring/services/"
                "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
            )
            if namespace is None and path.startswith(prom_prefix) and len(path) <= 1000:
                from urllib.parse import unquote

                query = unquote(path[len(prom_prefix) :])
                if re.fullmatch(
                    r'count\((?:up|cloudflared_tunnel_ha_connections)\{namespace="[-a-z0-9]+",service="[-a-z0-9]*"\} (?:== 1|>= 4)\)'
                    r'|count\(ALERTS\{alertname=~"CloudflareTunnel\(NoHealthyConnections\|ConnectionsDegraded\|MetricsTargetsDown\)",alertstate="firing"\}\)',
                    query,
                ):
                    return "kubectl/get-raw-prometheus-query"
        namespaced_gets = {
            ("deployment", "coredns"),
            ("deployment", "coredns-ha"),
            ("deployment", "traefik"),
            ("service", "traefik"),
            ("helmchartconfig", "traefik"),
        }
        if namespace == "kube-system" and len(args) == 5 and args[:1] == ["get"]:
            if tuple(args[1:3]) in namespaced_gets and args[3:] == ["-o", "json"]:
                return "kubectl/get"
        if namespace is not None and args[:2] == ["get", "pods"] and len(args) == 6:
            if (
                args[2] == "-l"
                and re.fullmatch(r"[-A-Za-z0-9_./=,]+", args[3])
                and args[4:] == ["-o", "json"]
            ):
                return "kubectl/get"
        if namespace is not None and args in (
            ["get", "pdb", "-o", "json"],
            ["get", "service", "-o", "json"],
            ["get", "servicemonitor", "-o", "json"],
        ):
            return "kubectl/get"
        if (
            namespace == "kube-system"
            and len(args) == 6
            and args[:2]
            == [
                "get",
                "endpointslices.discovery.k8s.io",
            ]
        ):
            if (
                args[2] == "-l"
                and re.fullmatch(r"kubernetes\.io/service-name=[-a-z0-9]+", args[3])
                and args[4:] == ["-o", "json"]
            ):
                return "kubectl/get"
    elif argv[0] == "helm":
        if args == ["list", "-A", "-o", "json"]:
            return "helm/list"
        if len(args) == 6 and args[0] in ("-n", "--namespace"):
            namespace, verb, release = args[1:4]
            if (
                verb in ("status", "history")
                and re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", namespace)
                and re.fullmatch(r"[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?", release)
                and args[4:] == ["-o", "json"]
            ):
                return f"helm/{verb}"
    elif argv[0] == "git" and args == ["rev-parse", "HEAD"]:
        return "git/rev-parse-head"
    elif argv[0] == sys.executable and args == [
        str(ROOT / "scripts/cluster_identity.py"),
        "assert",
        "--kubeconfig",
        os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config")),
        "--env",
        "prod",
    ]:
        return "python/cluster-identity-assert-prod"
    elif (
        argv[0] == "curl"
        and len(argv) == 15
        and args[:-1]
        == [
            "--silent",
            "--show-error",
            "--output",
            "/dev/null",
            "--max-time",
            "8",
            "--connect-timeout",
            "3",
            "--write-out",
            "%{http_code}\t%{time_connect}\t%{time_starttransfer}\t%{time_total}",
            "--proto",
            "=https",
            "--location",
        ]
        and args[-1] in probe_urls(json.loads(TARGETS.read_text()))
    ):
        return "curl/public-probe"
    raise HardFailure("internal safety policy rejected a non-allowlisted operation")


def run(argv: list[str], *, ok=(0,), timeout=30) -> subprocess.CompletedProcess[str]:
    op = operation(argv)
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    if proc.returncode not in ok:
        # Raw argv and stderr can expose credentials, connector IDs, labels, or bodies.
        raise HardFailure(f"read-only {op} failed (exit {proc.returncode}; external-error)")
    return proc


def kubectl(*args: str, allow_missing=False) -> dict[str, Any]:
    proc = run(["kubectl", *args], ok=(0, 1) if allow_missing else (0,))
    if proc.returncode:
        if allow_missing and ("NotFound" in proc.stderr or "not found" in proc.stderr.lower()):
            return {}
        raise HardFailure("unable to collect an expected Kubernetes resource")
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HardFailure("kubectl returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise HardFailure("kubectl JSON must be an object")
    return value


def add_gap(gaps: set[str], code: str, condition: bool) -> None:
    if condition:
        gaps.add(code)


def int_or_string_equals(value: Any, expected: int) -> bool:
    """Compare a Kubernetes IntOrString value with an expected integer."""
    return not isinstance(value, bool) and str(value) == str(expected)


def probe_urls(target_map: Any) -> list[str]:
    """Expand the public target manifest, failing closed when it has no URLs."""
    if not isinstance(target_map, dict):
        raise HardFailure("production probe target manifest must be an object")
    urls = []
    for host, paths in target_map.items():
        if not isinstance(host, str) or not host or not isinstance(paths, list) or not paths:
            raise HardFailure("production probe target manifest contains a malformed entry")
        if any(not isinstance(path, str) or not path.startswith("/") for path in paths):
            raise HardFailure("production probe target manifest contains a malformed path")
        urls.extend(f"https://{host}{path}" for path in paths)
    urls.sort()
    if not urls:
        raise HardFailure("production probe target manifest contains no URLs")
    return urls


def probes_unhealthy(rows: list[dict[str, Any]]) -> bool:
    return any(row.get("error") != "none" or not 200 <= row["status"] < 400 for row in rows)


def selector_matches(selector: Any, labels: dict[str, Any]) -> bool:
    match = selector.get("matchLabels", {}) if isinstance(selector, dict) else {}
    return bool(match) and all(labels.get(k) == v for k, v in match.items())


def required_hostname_anti_affinity(affinity: Any, labels: dict[str, Any]) -> bool:
    if not isinstance(affinity, dict):
        return False
    terms = affinity.get("podAntiAffinity", {}).get(
        "requiredDuringSchedulingIgnoredDuringExecution", []
    )
    return any(
        isinstance(term, dict)
        and term.get("topologyKey") == "kubernetes.io/hostname"
        and selector_matches(term.get("labelSelector"), labels)
        for term in terms
    )


def traefik_desired_snapshot(content: Any) -> dict[str, Any]:
    """Extract only the two approved fields from K3s Helm values (never raw values)."""
    text = content if isinstance(content, str) else ""
    replica = re.search(r"(?m)^\s{2}replicas:\s*([0-9]+)\s*$", text)
    return {
        "replicas": int(replica.group(1)) if replica else None,
        "requiredHostnameAntiAffinity": bool(
            re.search(r"(?m)^\s*requiredDuringSchedulingIgnoredDuringExecution:\s*$", text)
            and re.search(r"(?m)^\s*topologyKey:\s*kubernetes\.io/hostname\s*$", text)
            and re.search(r"(?m)^\s*app\.kubernetes\.io/name:\s*traefik\s*$", text)
        ),
    }


def ready(pod: dict[str, Any]) -> bool:
    return pod.get("metadata", {}).get("deletionTimestamp") is None and any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in pod.get("status", {}).get("conditions", [])
    )


def pods_snapshot(document: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for value in list_shape(document.get("items"), "malformed Kubernetes pod list"):
        pod = object_shape(value, "malformed Kubernetes pod record")
        metadata = object_shape(pod.get("metadata"), "malformed Kubernetes pod record")
        spec = object_shape(pod.get("spec"), "malformed Kubernetes pod record")
        status = object_shape(pod.get("status"), "malformed Kubernetes pod record")
        list_shape(status.get("conditions", []), "malformed Kubernetes pod record")
        statuses = list_shape(
            status.get("containerStatuses", []), "malformed Kubernetes pod record"
        )
        if not all(isinstance(item, dict) for item in statuses):
            raise HardFailure("malformed Kubernetes pod record")
        result.append(
            {
                "uid": metadata.get("uid"),
                "node": spec.get("nodeName"),
                "ready": ready(pod),
                "restarts": sum(int(c.get("restartCount", 0)) for c in statuses),
            }
        )
    return sorted(result, key=lambda p: (p["node"] or "", p["uid"] or ""))


def deployment_snapshot(dep: dict[str, Any]) -> dict[str, Any]:
    meta = object_shape(dep.get("metadata"), "malformed Kubernetes Deployment")
    spec = object_shape(dep.get("spec"), "malformed Kubernetes Deployment")
    status = object_shape(dep.get("status", {}), "malformed Kubernetes Deployment")
    template = object_shape(spec.get("template"), "malformed Kubernetes Deployment")
    pod_spec = object_shape(template.get("spec"), "malformed Kubernetes Deployment")
    containers = []

    def safe_probe(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        http = value.get("httpGet", {})
        return {
            "httpGet": {
                "path": http.get("path"),
                "port": http.get("port"),
                "scheme": http.get("scheme"),
            },
            "initialDelaySeconds": value.get("initialDelaySeconds"),
            "periodSeconds": value.get("periodSeconds"),
            "timeoutSeconds": value.get("timeoutSeconds"),
            "failureThreshold": value.get("failureThreshold"),
        }

    for value in list_shape(
        pod_spec.get("containers"), "malformed Kubernetes Deployment containers"
    ):
        c = object_shape(value, "malformed Kubernetes Deployment container")
        refs = []
        for env_value in list_shape(
            c.get("env", []), "malformed Kubernetes Deployment environment"
        ):
            env = object_shape(env_value, "malformed Kubernetes Deployment environment")
            ref = env.get("valueFrom", {}).get("secretKeyRef")
            if ref:
                refs.append(
                    {"env": env.get("name"), "secret": ref.get("name"), "key": ref.get("key")}
                )
        containers.append(
            {
                "name": c.get("name"),
                "image": c.get("image"),
                "readinessProbe": safe_probe(c.get("readinessProbe")),
                "livenessProbe": safe_probe(c.get("livenessProbe")),
                "secretReferences": refs,
            }
        )
    return {
        "namespace": meta.get("namespace"),
        "name": meta.get("name"),
        "uid": meta.get("uid"),
        "generation": meta.get("generation"),
        "ownerReferences": meta.get("ownerReferences", []),
        "replicas": spec.get("replicas", 1),
        "readyReplicas": status.get("readyReplicas", 0),
        "availableReplicas": status.get("availableReplicas", 0),
        "strategy": spec.get("strategy", {}),
        "affinity": pod_spec.get("affinity", {}),
        "topologySpreadConstraints": pod_spec.get("topologySpreadConstraints", []),
        "containers": containers,
    }


def endpoints(document: dict[str, Any], service: str) -> dict[str, Any]:
    grouped: dict[tuple[str, tuple[str, ...], tuple[str, ...]], list[tuple[bool, bool, bool]]] = {}
    items = document.get("items")
    if not isinstance(items, list):
        raise HardFailure("malformed EndpointSlice list")
    for item in items:
        item = object_shape(item, "malformed EndpointSlice entry")
        metadata = object_shape(item.get("metadata"), "malformed EndpointSlice entry")
        labels = object_shape(metadata.get("labels"), "malformed EndpointSlice entry")
        if labels.get("kubernetes.io/service-name") != service:
            raise HardFailure("EndpointSlice selector returned an unrelated Service")
        for value in list_shape(item.get("endpoints"), "malformed EndpointSlice entry"):
            endpoint = object_shape(value, "malformed EndpointSlice entry")
            cond = object_shape(endpoint.get("conditions", {}), "malformed EndpointSlice entry")
            effective_ready = cond.get("ready", True)
            serving = cond.get("serving", effective_ready)
            terminating = cond.get("terminating", False)
            addresses = list_shape(endpoint.get("addresses"), "malformed EndpointSlice entry")
            if not all(isinstance(address, str) for address in addresses):
                raise HardFailure("malformed EndpointSlice entry")
            target = object_shape(endpoint.get("targetRef", {}), "malformed EndpointSlice entry")
            key = (
                endpoint.get("nodeName") or "",
                tuple(sorted(set(addresses))),
                tuple(str(target.get(k, "")) for k in ("kind", "namespace", "name", "uid")),
            )
            grouped.setdefault(key, []).append((effective_ready, serving, terminating))
    healthy = [k for k, states in grouped.items() if all(r and s and not t for r, s, t in states)]
    return {
        "service": service,
        "slices": len(items),
        "uniqueEndpoints": len(grouped),
        "healthyEndpoints": len(healthy),
        "unhealthyEndpoints": len(grouped) - len(healthy),
        "healthyNodes": sorted({key[0] for key in healthy if key[0]}),
    }


def list_items(*args: str) -> list[dict[str, Any]]:
    value = kubectl(*args)
    items = value.get("items", [])
    if not isinstance(items, list):
        raise HardFailure("Kubernetes list response is malformed")
    if not all(isinstance(item, dict) for item in items):
        raise HardFailure("Kubernetes list contains a malformed record")
    return items


def prom_count(query: str) -> int:
    from urllib.parse import quote

    path = (
        "/api/v1/namespaces/monitoring/services/"
        "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
        + quote(query, safe="")
    )
    result = kubectl("get", "--raw", path).get("data", {}).get("result", [])
    try:
        return int(float(result[0]["value"][1])) if result else 0
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise HardFailure("Prometheus returned an invalid aggregate") from exc


def prometheus_alert_rules() -> dict[str, Any]:
    """Return only repository-owned aggregate alert-rule health state."""
    document = kubectl("get", "--raw", PROMETHEUS_ALERT_RULES_PATH)
    data = document.get("data")
    if document.get("status") != "success" or not isinstance(data, dict):
        raise HardFailure("Prometheus returned malformed alert rules")
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise HardFailure("Prometheus returned malformed alert rules")

    expected = set(EXPECTED_CLOUDFLARE_ALERT_RULES)
    matches: list[tuple[str, str]] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("rules"), list):
            raise HardFailure("Prometheus returned malformed alert rules")
        for rule in group["rules"]:
            if (
                not isinstance(rule, dict)
                or not isinstance(rule.get("name"), str)
                or not isinstance(rule.get("health"), str)
            ):
                raise HardFailure("Prometheus returned malformed alert rules")
            if rule["name"] in expected:
                matches.append((rule["name"], rule["health"]))

    return {
        "expectedNames": list(EXPECTED_CLOUDFLARE_ALERT_RULES),
        "expectedCount": len(EXPECTED_CLOUDFLARE_ALERT_RULES),
        "presentNames": sorted({name for name, _ in matches}),
        "presentCount": len(matches),
        "healthyCount": sum(health == "ok" for _, health in matches),
        "ruleSetMatches": sorted(name for name, _ in matches)
        == list(EXPECTED_CLOUDFLARE_ALERT_RULES),
        "allPresentRulesHealthy": all(health == "ok" for _, health in matches),
    }


def probe(url: str) -> dict[str, Any]:
    try:
        proc = run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--output",
                "/dev/null",
                "--max-time",
                "8",
                "--connect-timeout",
                "3",
                "--write-out",
                "%{http_code}\t%{time_connect}\t%{time_starttransfer}\t%{time_total}",
                "--proto",
                "=https",
                "--location",
                url,
            ],
            ok=tuple(range(0, 100)),
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"url": url, "status": 0, "error": "timeout"}
    fields = proc.stdout.strip().split("\t")
    status = int(fields[0]) if fields and fields[0].isdigit() else 0
    row: dict[str, Any] = {"url": url, "status": status, "error": "none"}
    if len(fields) == 4:
        row.update(zip(("connectSeconds", "startTransferSeconds", "totalSeconds"), fields[1:]))
    if proc.returncode:
        row["error"] = "timeout" if proc.returncode == 28 else "transport"
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--require-parity", action="store_true")
    args = parser.parse_args(argv)
    if args.env.removeprefix("env=") != "prod":
        raise HardFailure("env must normalize exactly to prod")
    for tool in ("kubectl", "helm", "curl", "git"):
        if not shutil.which(tool):
            raise HardFailure(f"required read-only tool not found: {tool}")
    context = run(["kubectl", "config", "current-context"]).stdout.strip()
    if context != "sugar-prod":
        raise HardFailure("current kubectl context must be exactly sugar-prod")
    kubeconfig = os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config"))
    identity = run(
        [
            sys.executable,
            str(ROOT / "scripts/cluster_identity.py"),
            "assert",
            "--kubeconfig",
            kubeconfig,
            "--env",
            "prod",
        ]
    )
    if identity.stdout.strip() != "prod":
        raise HardFailure("repository cluster identity did not report prod")

    gaps: set[str] = set()
    nodes_doc = kubectl("get", "nodes", "-o", "json")
    node_items = list_shape(nodes_doc.get("items"), "malformed Kubernetes node list")
    nodes_by_name = []
    for value in node_items:
        node = object_shape(value, "malformed Kubernetes node record")
        metadata = object_shape(node.get("metadata"), "malformed Kubernetes node record")
        status = object_shape(node.get("status"), "malformed Kubernetes node record")
        conditions = list_shape(status.get("conditions"), "malformed Kubernetes node conditions")
        if not isinstance(metadata.get("name"), str) or not all(
            isinstance(condition, dict) for condition in conditions
        ):
            raise HardFailure("malformed Kubernetes node record")
        nodes_by_name.append((node, metadata, conditions))
    names = {metadata["name"] for _, metadata, _ in nodes_by_name}
    if names != EXPECTED_NODES:
        raise HardFailure("observed node set is not exactly sugarkube0, sugarkube1, sugarkube2")
    nodes = []
    for node, metadata, node_conditions in nodes_by_name:
        conditions = {c.get("type"): c.get("status") for c in node_conditions}
        nodes.append({"name": metadata["name"], "ready": conditions.get("Ready") == "True"})
    add_gap(gaps, "NODE_NOT_READY", not all(n["ready"] for n in nodes))
    readyz = run(["kubectl", "get", "--raw", "/readyz?verbose"]).stdout
    readyz_summary = {
        "ready": "readyz check passed" in readyz,
        "etcdReady": any(
            line.startswith("[+]etcd ") or line == "[+]etcd ok" for line in readyz.splitlines()
        ),
    }
    add_gap(gaps, "API_OR_ETCD_NOT_READY", not all(readyz_summary.values()))

    components: dict[str, Any] = {}
    for name in ("coredns", "coredns-ha", "traefik"):
        dep = kubectl(
            "-n", "kube-system", "get", "deployment", name, "-o", "json", allow_missing=True
        )
        if not dep:
            if name != "coredns-ha":
                gaps.add(f"{name.upper()}_MISSING")
            continue
        snap = deployment_snapshot(dep)
        selector = ",".join(
            f"{k}={v}"
            for k, v in sorted(
                dep.get("spec", {}).get("selector", {}).get("matchLabels", {}).items()
            )
        )
        pod_doc = kubectl("-n", "kube-system", "get", "pods", "-l", selector, "-o", "json")
        snap["pods"] = pods_snapshot(pod_doc)
        components[name] = snap
    for name in ("coredns", "traefik"):
        relevant = [
            v
            for k, v in components.items()
            if k == name or (name == "coredns" and k == "coredns-ha")
        ]
        ready_pods = [p for d in relevant for p in d.get("pods", []) if p["ready"]]
        add_gap(gaps, f"{name.upper()}_SINGLETON", len(ready_pods) < 2)
        add_gap(gaps, f"{name.upper()}_UNSPREAD", len({p["node"] for p in ready_pods}) < 2)
    kube_system_pdbs = [
        {
            "name": item.get("metadata", {}).get("name"),
            "selector": item.get("spec", {}).get("selector", {}),
            "minAvailable": item.get("spec", {}).get("minAvailable"),
            "maxUnavailable": item.get("spec", {}).get("maxUnavailable"),
        }
        for item in list_items("-n", "kube-system", "get", "pdb", "-o", "json")
    ]
    endpoint_data = {}
    for service in ("kube-dns", "traefik"):
        doc = kubectl(
            "-n",
            "kube-system",
            "get",
            "endpointslices.discovery.k8s.io",
            "-l",
            f"kubernetes.io/service-name={service}",
            "-o",
            "json",
        )
        endpoint_data[service] = endpoints(doc, service)
        add_gap(
            gaps,
            f"{service.upper().replace('-', '_')}_ENDPOINTS_INSUFFICIENT",
            len(endpoint_data[service]["healthyNodes"]) < 2,
        )
    traefik_service = kubectl("-n", "kube-system", "get", "service", "traefik", "-o", "json")
    ingress_service = {
        "internalTrafficPolicy": traefik_service.get("spec", {}).get(
            "internalTrafficPolicy", "Cluster"
        )
    }
    add_gap(
        gaps, "TRAEFIK_TRAFFIC_POLICY_MISMATCH", ingress_service["internalTrafficPolicy"] != "Local"
    )
    traefik = components.get("traefik", {})
    add_gap(
        gaps,
        "TRAEFIK_SCHEDULING_CONTRACT_MISMATCH",
        not required_hostname_anti_affinity(
            traefik.get("affinity", {}), {"app.kubernetes.io/name": "traefik"}
        ),
    )
    lifecycle = {}
    for kind, name in (("helmchartconfig", "traefik"), ("deployment", "coredns-ha")):
        obj = kubectl("-n", "kube-system", "get", kind, name, "-o", "json", allow_missing=True)
        lifecycle[f"{kind}/{name}"] = {
            "present": bool(obj),
            "uid": obj.get("metadata", {}).get("uid"),
            "ownerReferences": obj.get("metadata", {}).get("ownerReferences", []),
            "managedBy": obj.get("metadata", {}).get("labels", {}).get("sugarkube.dev/managed-by"),
            "desired": (
                {
                    "replicas": obj.get("spec", {}).get("replicas"),
                    "affinity": obj.get("spec", {})
                    .get("template", {})
                    .get("spec", {})
                    .get("affinity", {}),
                }
                if kind == "deployment"
                else traefik_desired_snapshot(obj.get("spec", {}).get("valuesContent"))
            ),
        }
    desired_traefik = lifecycle["helmchartconfig/traefik"]["desired"]
    add_gap(
        gaps,
        "TRAEFIK_DESIRED_CONFIG_MISMATCH",
        desired_traefik.get("replicas") != 2
        or not desired_traefik.get("requiredHostnameAntiAffinity"),
    )
    add_gap(gaps, "COREDNS_HA_MISSING", not lifecycle["deployment/coredns-ha"]["present"])

    deployments = list_items(
        "get", "deployment", "-A", "-l", "app.kubernetes.io/name=cloudflare-tunnel", "-o", "json"
    )
    releases = list_shape(
        json.loads(run(["helm", "list", "-A", "-o", "json"]).stdout),
        "malformed Helm release list",
    )
    if not all(isinstance(item, dict) for item in releases):
        raise HardFailure("malformed Helm release record")
    candidates = []
    for dep in deployments:
        meta = object_shape(dep.get("metadata"), "malformed Kubernetes Deployment metadata")
        labels = object_shape(meta.get("labels", {}), "malformed Kubernetes Deployment metadata")
        annotations = object_shape(
            meta.get("annotations", {}), "malformed Kubernetes Deployment metadata"
        )
        release_name = labels.get("app.kubernetes.io/instance") or annotations.get(
            "meta.helm.sh/release-name"
        )
        match = [
            r
            for r in releases
            if r.get("name") == release_name and r.get("namespace") == meta.get("namespace")
        ]
        if len(match) == 1:
            candidates.append((dep, match[0]))
    if len(candidates) != 1:
        raise HardFailure(
            f"expected exactly one live Cloudflare release candidate; found {len(candidates)}"
        )
    tunnel_dep, release = candidates[0]
    tunnel_meta = object_shape(
        tunnel_dep.get("metadata"), "malformed Kubernetes Deployment metadata"
    )
    ns, release_name = tunnel_meta.get("namespace"), release.get("name")
    if not isinstance(ns, str) or not isinstance(release_name, str):
        raise HardFailure("malformed Cloudflare release identity")
    history_raw = list_shape(
        json.loads(run(["helm", "-n", ns, "history", release_name, "-o", "json"]).stdout),
        "malformed Helm release history",
    )
    if not all(isinstance(item, dict) for item in history_raw):
        raise HardFailure("malformed Helm history record")
    history = [
        {k: h.get(k) for k in ("revision", "updated", "status", "chart", "app_version")}
        for h in history_raw
    ]
    status_raw = object_shape(
        json.loads(run(["helm", "-n", ns, "status", release_name, "-o", "json"]).stdout),
        "malformed Helm release status",
    )
    tunnel = deployment_snapshot(tunnel_dep)
    tunnel.update(
        {
            "release": release_name,
            "chart": release.get("chart"),
            "appVersion": release.get("app_version"),
            "revision": release.get("revision"),
            "helmStatus": status_raw.get("info", {}).get("status"),
            "history": history,
        }
    )
    tunnel_spec = object_shape(tunnel_dep.get("spec"), "malformed Kubernetes Deployment selector")
    tunnel_selector = object_shape(
        tunnel_spec.get("selector"), "malformed Kubernetes Deployment selector"
    )
    match_labels = object_shape(
        tunnel_selector.get("matchLabels"), "malformed Kubernetes Deployment selector"
    )
    if not match_labels or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in match_labels.items()
    ):
        raise HardFailure("malformed Kubernetes Deployment selector")
    selector = ",".join(f"{k}={v}" for k, v in sorted(match_labels.items()))
    workload_labels = (
        tunnel_dep.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
    )
    tunnel["pods"] = pods_snapshot(kubectl("-n", ns, "get", "pods", "-l", selector, "-o", "json"))
    ready_tunnel = [p for p in tunnel["pods"] if p["ready"]]
    container = tunnel["containers"][0] if tunnel["containers"] else {}
    strategy = tunnel["strategy"].get("rollingUpdate", {})
    add_gap(gaps, "CF_IMAGE_NOT_IMMUTABLE_PIN", container.get("image") != EXPECTED_IMAGE)
    add_gap(gaps, "CF_CHART_VERSION_MISMATCH", release.get("chart") != "cloudflare-tunnel-0.3.2")
    tunnel["helmListStatus"] = release.get("status")
    add_gap(
        gaps,
        "CF_HELM_RELEASE_NOT_DEPLOYED",
        tunnel["helmStatus"] != "deployed" or tunnel["helmListStatus"] != "deployed",
    )
    add_gap(gaps, "CF_CONNECTORS_INSUFFICIENT", len(ready_tunnel) < 2)
    add_gap(gaps, "CF_CONNECTORS_UNSPREAD", len({p["node"] for p in ready_tunnel}) < 2)
    add_gap(
        gaps,
        "CF_ANTI_AFFINITY_MISSING",
        not required_hostname_anti_affinity(tunnel.get("affinity"), workload_labels),
    )
    add_gap(
        gaps,
        "CF_UNSAFE_ROLLOUT",
        not int_or_string_equals(strategy.get("maxUnavailable"), 0)
        or not int_or_string_equals(strategy.get("maxSurge"), 1),
    )
    probe_spec = (container.get("readinessProbe") or {}).get("httpGet", {})
    add_gap(
        gaps,
        "CF_PROBE_CONTRACT",
        probe_spec.get("path") != "/ready"
        or not int_or_string_equals(probe_spec.get("port"), 2000)
        or bool(container.get("livenessProbe")),
    )
    pdbs = list_items("-n", ns, "get", "pdb", "-o", "json")
    services = list_items("-n", ns, "get", "service", "-o", "json")
    monitors = list_items("-n", ns, "get", "servicemonitor", "-o", "json")
    tunnel["pdb"] = [
        {
            "name": x["metadata"]["name"],
            "minAvailable": x.get("spec", {}).get("minAvailable"),
            "maxUnavailable": x.get("spec", {}).get("maxUnavailable"),
        }
        for x in pdbs
        if selector_matches(x.get("spec", {}).get("selector"), workload_labels)
    ]
    matching_services = []
    for service in services:
        spec = service.get("spec", {})
        ports = spec.get("ports", [])
        if (
            spec.get("type", "ClusterIP") == "ClusterIP"
            and selector_matches({"matchLabels": spec.get("selector", {})}, workload_labels)
            and any(
                p.get("name") == "metrics"
                and int_or_string_equals(p.get("port"), 2000)
                and int_or_string_equals(p.get("targetPort"), 2000)
                for p in ports
            )
        ):
            matching_services.append(service)
    service_labels = (
        matching_services[0].get("metadata", {}).get("labels", {})
        if len(matching_services) == 1
        else {}
    )
    matching_monitors = [
        monitor
        for monitor in monitors
        if selector_matches(monitor.get("spec", {}).get("selector"), service_labels)
        and ns in monitor.get("spec", {}).get("namespaceSelector", {}).get("matchNames", [])
        and any(
            endpoint.get("port") == "metrics" and endpoint.get("path") == "/metrics"
            for endpoint in monitor.get("spec", {}).get("endpoints", [])
        )
    ]
    tunnel["metrics"] = {
        "services": [x["metadata"]["name"] for x in matching_services],
        "serviceMonitors": [x["metadata"]["name"] for x in matching_monitors],
    }
    add_gap(
        gaps,
        "CF_PDB_MISSING",
        not any(int_or_string_equals(p.get("minAvailable"), 1) for p in tunnel["pdb"]),
    )
    add_gap(
        gaps,
        "CF_METRICS_DISCOVERY_MISSING",
        len(matching_services) != 1 or len(matching_monitors) != 1,
    )
    metrics_service = tunnel["metrics"]["services"][0] if tunnel["metrics"]["services"] else ""
    metrics = {
        "healthyTargets": prom_count(
            f'count(up{{namespace="{ns}",service="{metrics_service}"}} == 1)'
        ),
        "connectorsWithFourHAConnections": prom_count(
            "count(cloudflared_tunnel_ha_connections"
            f'{{namespace="{ns}",service="{metrics_service}"}} >= 4)'
        ),
        "firingRelevantAlerts": prom_count(
            'count(ALERTS{alertname=~"CloudflareTunnel(NoHealthyConnections|'
            'ConnectionsDegraded|MetricsTargetsDown)",alertstate="firing"})'
        ),
    }
    metrics["alertRules"] = prometheus_alert_rules()
    add_gap(gaps, "CF_METRICS_TARGETS_UNHEALTHY", metrics["healthyTargets"] < len(ready_tunnel))
    add_gap(
        gaps,
        "CF_HA_CONNECTIONS_INSUFFICIENT",
        metrics["connectorsWithFourHAConnections"] < len(ready_tunnel),
    )
    add_gap(gaps, "CF_ALERTS_FIRING", metrics["firingRelevantAlerts"] != 0)
    add_gap(
        gaps,
        "CF_ALERT_RULE_SET_MISMATCH",
        not metrics["alertRules"]["ruleSetMatches"],
    )
    add_gap(
        gaps,
        "CF_ALERT_RULES_UNHEALTHY",
        not metrics["alertRules"]["allPresentRulesHealthy"],
    )

    target_map = json.loads(TARGETS.read_text())
    urls = probe_urls(target_map)
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(MAX_PROBE_WORKERS, len(urls))
    ) as pool:
        probe_rows = sorted(pool.map(probe, urls), key=lambda row: row["url"])
    add_gap(
        gaps,
        "PUBLIC_ENDPOINT_UNHEALTHY",
        probes_unhealthy(probe_rows),
    )
    revision = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    timestamp = os.environ.get("SUGARKUBE_AUDIT_TIMESTAMP") or dt.datetime.now(
        dt.timezone.utc
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    audit = {
        "schemaVersion": 1,
        "timestamp": timestamp,
        "gitRevision": revision,
        "environment": "prod",
        "context": context,
        "result": "PARITY_OK" if not gaps else "PARITY_GAPS",
        "gapCount": len(gaps),
        "gaps": sorted(gaps),
        "observed": {
            "nodes": sorted(nodes, key=lambda x: x["name"]),
            "apiReadyz": readyz_summary,
            "components": components,
            "kubeSystemPDBs": sorted(kube_system_pdbs, key=lambda item: item["name"] or ""),
            "endpointSlices": endpoint_data,
            "traefikService": ingress_service,
            "lifecycleResources": lifecycle,
            "cloudflareTunnel": tunnel,
            "prometheus": metrics,
        },
    }
    parent = args.evidence_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".prod-audit-", dir=parent))
    try:
        (tmp / "audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
        with (tmp / "endpoints.tsv").open("w") as stream:
            stream.write(
                "url\tstatus\tconnect_seconds\tstart_transfer_seconds\ttotal_seconds\terror\n"
            )
            for row in probe_rows:
                stream.write(
                    "\t".join(
                        str(row.get(k, ""))
                        for k in (
                            "url",
                            "status",
                            "connectSeconds",
                            "startTransferSeconds",
                            "totalSeconds",
                            "error",
                        )
                    )
                    + "\n"
                )
        lines = [
            "# Production resilience parity audit",
            "",
            f"**Result:** `{audit['result']}` ({len(gaps)} gaps)",
            "",
            "| Gap code |",
            "|---|",
        ] + [f"| `{gap}` |" for gap in sorted(gaps)]
        (tmp / "summary.md").write_text("\n".join(lines) + "\n")
        files = sorted(p for p in tmp.iterdir() if p.name != "SHA256SUMS")
        (tmp / "SHA256SUMS").write_text(
            "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files)
        )
        if args.evidence_dir.exists():
            raise HardFailure("evidence directory already exists")
        tmp.rename(args.evidence_dir)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(
        f"{audit['result']}: collection complete; {len(gaps)} parity gap(s); "
        f"evidence: {args.evidence_dir}"
    )
    return 1 if args.require_parity and gaps else 0


def cli(argv: list[str] | None = None) -> int:
    """Run the CLI with a sanitized hard-failure boundary."""
    try:
        return main(argv)
    except HardFailure as error:
        print(f"HARD_FAILURE: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("HARD_FAILURE: unexpected collection failure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
