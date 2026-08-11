#!/usr/bin/env python3
"""Collect a sanitized, strictly read-only production resilience audit."""

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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NODES = {"sugarkube0", "sugarkube1", "sugarkube2"}
EXPECTED_IMAGE = (
    "cloudflare/cloudflared:2026.7.3@sha256:"
    "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)
FORBIDDEN = {
    "apply",
    "create",
    "patch",
    "replace",
    "delete",
    "edit",
    "run",
    "exec",
    "port-forward",
    "install",
    "upgrade",
    "rollback",
    "uninstall",
    "reconcile",
    "repo",
}


class CollectionError(RuntimeError):
    pass


def run(command: list[str], *, required: bool = True) -> str:
    """Run only commands admitted by the audit's read-only allow-list."""
    if command[0] not in {"kubectl", "helm", "curl", "git", sys.executable}:
        raise CollectionError(f"command is not allow-listed: {command[0]}")
    if command[0] in {"kubectl", "helm"} and FORBIDDEN.intersection(command[1:]):
        raise CollectionError("mutation command rejected by audit allow-list")
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode and required:
        raise CollectionError(f"read-only command failed: {command[0]} {' '.join(command[1:3])}")
    return proc.stdout


def load_json(command: list[str], *, optional: bool = False) -> dict[str, Any]:
    text = run(command, required=not optional)
    if optional and not text.strip():
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        if optional:
            return {}
        raise CollectionError(f"invalid JSON from {command[0]}") from exc
    if not isinstance(value, dict) and command[0] == "kubectl":
        raise CollectionError(f"unexpected JSON from {command[0]}")
    return value


def metadata(obj: dict[str, Any]) -> dict[str, Any]:
    m = obj.get("metadata", {})
    result = {
        key: m.get(key)
        for key in ("name", "namespace", "uid", "generation")
        if m.get(key) is not None
    }
    for field in ("labels", "annotations"):
        values = m.get(field, {})
        if isinstance(values, dict):
            result[field] = {
                key: value
                for key, value in sorted(values.items())
                if not re.search(
                    r"connector|tunnel.?id|token|secret|credential", f"{key} {value}", re.I
                )
            }
    return result


def lifecycle_spec(resource: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    """Retain structural desired state without arbitrary embedded configuration text."""
    if not obj:
        return None
    if resource.startswith("deployment/"):
        return deployment_snapshot(obj)
    spec = obj.get("spec", {})
    if not isinstance(spec, dict):
        return {}
    result = {key: value for key, value in spec.items() if key != "valuesContent"}
    if isinstance(spec.get("valuesContent"), str):
        result["valuesContentSha256"] = hashlib.sha256(spec["valuesContent"].encode()).hexdigest()
    return result


def pod_snapshot(pod: dict[str, Any]) -> dict[str, Any]:
    status = pod.get("status", {})
    containers = status.get("containerStatuses", []) or []
    return {
        "name": pod.get("metadata", {}).get("name"),
        "uid": pod.get("metadata", {}).get("uid"),
        "node": pod.get("spec", {}).get("nodeName"),
        "ready": any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
        ),
        "restarts": sum(int(c.get("restartCount", 0)) for c in containers),
        "terminating": bool(pod.get("metadata", {}).get("deletionTimestamp")),
    }


def deployment_snapshot(dep: dict[str, Any]) -> dict[str, Any]:
    spec, status = dep.get("spec", {}), dep.get("status", {})
    template = spec.get("template", {}).get("spec", {})
    containers = template.get("containers", [])
    return {
        "metadata": metadata(dep),
        "replicas": {
            "desired": spec.get("replicas", 1),
            "ready": status.get("readyReplicas", 0),
            "available": status.get("availableReplicas", 0),
        },
        "strategy": spec.get("strategy", {}),
        "affinity": template.get("affinity"),
        "topologySpreadConstraints": template.get("topologySpreadConstraints"),
        "containers": [
            {
                "name": c.get("name"),
                "image": c.get("image"),
                "readinessProbe": c.get("readinessProbe"),
                "livenessProbe": c.get("livenessProbe"),
                "secretReferences": sorted(
                    {
                        e.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
                        for e in c.get("env", [])
                        if e.get("valueFrom", {}).get("secretKeyRef", {}).get("name")
                    }
                ),
            }
            for c in containers
        ],
    }


def endpoint_snapshot(doc: dict[str, Any], service: str) -> dict[str, Any]:
    grouped: dict[tuple[str, tuple[str, ...], str], list[tuple[bool, bool, bool]]] = {}
    for item in doc.get("items", []):
        if item.get("metadata", {}).get("labels", {}).get("kubernetes.io/service-name") != service:
            raise CollectionError(f"unexpected EndpointSlice ownership for {service}")
        for endpoint in item.get("endpoints", []):
            conditions = endpoint.get("conditions", {})
            ready = conditions.get("ready", True)
            serving = conditions.get("serving", ready)
            terminating = conditions.get("terminating", False)
            target = endpoint.get("targetRef", {})
            key = (
                endpoint.get("nodeName") or "",
                tuple(sorted(endpoint.get("addresses", []))),
                "/".join(str(target.get(k, "")) for k in ("kind", "namespace", "name", "uid")),
            )
            grouped.setdefault(key, []).append(
                (ready is True, serving is True, terminating is True)
            )
    healthy = [
        key for key, states in grouped.items() if all(r and s and not t for r, s, t in states)
    ]
    unhealthy = [key for key in grouped if key not in healthy]
    return {
        "service": service,
        "sliceCount": len(doc.get("items", [])),
        "uniqueEndpoints": len(grouped),
        "healthyEndpoints": len(healthy),
        "unhealthyEndpoints": len(unhealthy),
        "healthyNodes": sorted({key[0] for key in healthy if key[0]}),
    }


def gap(gaps: list[dict[str, str]], code: str, detail: str) -> None:
    gaps.append({"code": code, "detail": detail})


def prom_value(path: str) -> int:
    doc = load_json(["kubectl", "get", "--raw", path])
    try:
        return int(float(doc["data"]["result"][0]["value"][1]))
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def probe(url: str) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--output",
            "/dev/null",
            "--max-time",
            "10",
            "--connect-timeout",
            "4",
            "--write-out",
            "%{http_code}\t%{time_connect}\t%{time_starttransfer}\t%{time_total}",
            url,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    fields = proc.stdout.strip().split("\t")
    error = (
        "none" if proc.returncode == 0 else ("timeout" if proc.returncode == 28 else "transport")
    )
    return {
        "url": url,
        "status": int(fields[0]) if len(fields) == 4 and fields[0].isdigit() else 0,
        "connectSeconds": fields[1] if len(fields) == 4 else None,
        "startTransferSeconds": fields[2] if len(fields) == 4 else None,
        "totalSeconds": fields[3] if len(fields) == 4 else None,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env", help="must be env=prod or prod")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--require-parity", action="store_true")
    args = parser.parse_args()
    env_name = args.env
    while env_name.startswith("env="):
        env_name = env_name[4:]
    if env_name != "prod":
        raise CollectionError("env must normalize exactly to prod")
    for tool in ("kubectl", "helm", "curl", "git"):
        if shutil.which(tool) is None:
            raise CollectionError(f"required read-only tool not found: {tool}")
    context = run(["kubectl", "config", "current-context"]).strip()
    if context != "sugar-prod":
        raise CollectionError("current kubectl context must be exactly sugar-prod")
    kubeconfig = os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config"))
    detected = run(
        [
            sys.executable,
            str(ROOT / "scripts/cluster_identity.py"),
            "assert",
            "--kubeconfig",
            kubeconfig,
            "--env",
            "prod",
        ]
    ).strip()
    if detected != "prod":
        raise CollectionError("repository cluster-identity detection did not report prod")
    nodes_doc = load_json(["kubectl", "get", "nodes", "-o", "json"])
    node_names = {x.get("metadata", {}).get("name") for x in nodes_doc.get("items", [])}
    if node_names != EXPECTED_NODES:
        raise CollectionError(
            "observed node set must be exactly sugarkube0, sugarkube1, and sugarkube2"
        )

    gaps: list[dict[str, str]] = []
    node_state = [
        {
            "name": n.get("metadata", {}).get("name"),
            "ready": next(
                (
                    c.get("status") == "True"
                    for c in n.get("status", {}).get("conditions", [])
                    if c.get("type") == "Ready"
                ),
                False,
            ),
        }
        for n in nodes_doc.get("items", [])
    ]
    if not all(n["ready"] for n in node_state):
        gap(gaps, "NODE_NOT_READY", "not every production node is Ready")
    readyz = run(["kubectl", "get", "--raw", "/readyz?verbose"])
    readyz_lines = sorted(line.strip() for line in readyz.splitlines() if line.strip())
    if "etcd" not in readyz.lower() or "failed" in readyz.lower():
        gap(gaps, "API_READINESS_GAP", "API verbose readiness or etcd readiness is unhealthy")

    components: dict[str, Any] = {}
    for name in ("coredns", "traefik"):
        dep = load_json(["kubectl", "-n", "kube-system", "get", "deployment", name, "-o", "json"])
        pods = load_json(
            [
                "kubectl",
                "-n",
                "kube-system",
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/name={name}" if name == "traefik" else "k8s-app=kube-dns",
                "-o",
                "json",
            ]
        )
        snap = deployment_snapshot(dep)
        snap["pods"] = sorted(
            (pod_snapshot(p) for p in pods.get("items", [])), key=lambda p: p["name"] or ""
        )
        components[name] = snap
        ready_nodes = {p["node"] for p in snap["pods"] if p["ready"] and not p["terminating"]}
        if snap["replicas"]["ready"] < 2:
            gap(gaps, f"{name.upper()}_SINGLETON", f"{name} has fewer than two Ready replicas")
        if len(ready_nodes) < 2:
            gap(
                gaps,
                f"{name.upper()}_UNSPREAD",
                f"{name} Ready pods are not spread across two nodes",
            )
    endpoints = []
    for service in ("kube-dns", "traefik"):
        doc = load_json(
            [
                "kubectl",
                "-n",
                "kube-system",
                "get",
                "endpointslices.discovery.k8s.io",
                "-l",
                f"kubernetes.io/service-name={service}",
                "-o",
                "json",
            ]
        )
        snap = endpoint_snapshot(doc, service)
        endpoints.append(snap)
        if snap["healthyEndpoints"] < 2:
            gap(
                gaps,
                f"{service.upper().replace('-', '_')}_ENDPOINTS_INSUFFICIENT",
                f"{service} has fewer than two effective healthy endpoints",
            )
        if len(snap["healthyNodes"]) < 2:
            gap(
                gaps,
                f"{service.upper().replace('-', '_')}_ENDPOINTS_UNSPREAD",
                f"{service} endpoints are insufficiently spread",
            )
    traefik_service = load_json(
        ["kubectl", "-n", "kube-system", "get", "service", "traefik", "-o", "json"]
    )
    components["traefik"]["internalTrafficPolicy"] = traefik_service.get("spec", {}).get(
        "internalTrafficPolicy", "Cluster"
    )
    components["pdbs"] = load_json(
        ["kubectl", "-n", "kube-system", "get", "pdb", "-o", "json"], optional=True
    ).get("items", [])
    lifecycle = {}
    for resource in ("helmchartconfig/traefik", "deployment/coredns-ha"):
        obj = load_json(
            ["kubectl", "-n", "kube-system", "get", resource, "-o", "json"], optional=True
        )
        lifecycle[resource] = (
            {
                "present": bool(obj),
                "metadata": metadata(obj),
                "desiredSpec": lifecycle_spec(resource, obj),
            }
            if obj
            else {"present": False}
        )

    deployments = load_json(
        [
            "kubectl",
            "get",
            "deployments",
            "-A",
            "-l",
            "app.kubernetes.io/name=cloudflare-tunnel",
            "-o",
            "json",
        ]
    )
    candidates = sorted(
        deployments.get("items", []),
        key=lambda d: (
            d.get("metadata", {}).get("namespace", ""),
            d.get("metadata", {}).get("name", ""),
        ),
    )
    if len(candidates) != 1:
        raise CollectionError(
            f"expected exactly one live Cloudflare Tunnel Deployment; found {len(candidates)}"
        )
    tunnel_dep = candidates[0]
    tm = tunnel_dep.get("metadata", {})
    annotations = tm.get("annotations", {})
    namespace = tm.get("namespace")
    release = annotations.get("meta.helm.sh/release-name") or tm.get("labels", {}).get(
        "app.kubernetes.io/instance"
    )
    release_ns = annotations.get("meta.helm.sh/release-namespace") or namespace
    if (
        not release
        or release_ns != namespace
        or tm.get("labels", {}).get("app.kubernetes.io/managed-by") != "Helm"
    ):
        raise CollectionError("live Cloudflare Deployment does not have unambiguous Helm ownership")
    releases = json.loads(run(["helm", "list", "-A", "-o", "json"]) or "[]")
    matches = [r for r in releases if r.get("name") == release and r.get("namespace") == namespace]
    if len(matches) != 1:
        raise CollectionError("live Deployment did not resolve to exactly one Helm release")
    helm_status = json.loads(
        run(["helm", "-n", namespace, "status", release, "-o", "json"]) or "{}"
    )
    helm_history = json.loads(
        run(["helm", "-n", namespace, "history", release, "-o", "json"]) or "[]"
    )
    tunnel = deployment_snapshot(tunnel_dep)
    tunnel["release"] = {
        "namespace": namespace,
        "name": release,
        "chart": matches[0].get("chart"),
        "appVersion": matches[0].get("app_version"),
        "status": matches[0].get("status"),
        "revision": matches[0].get("revision"),
        "history": [
            {k: h.get(k) for k in ("revision", "status", "chart", "app_version")}
            for h in helm_history
        ],
        "helmStatus": helm_status.get("info", {}).get("status"),
    }
    selector = f"app.kubernetes.io/name=cloudflare-tunnel,app.kubernetes.io/instance={release}"
    tunnel_pods = load_json(
        ["kubectl", "-n", namespace, "get", "pods", "-l", selector, "-o", "json"]
    )
    tunnel["pods"] = sorted(
        (pod_snapshot(p) for p in tunnel_pods.get("items", [])), key=lambda p: p["name"] or ""
    )
    pdb = load_json(
        ["kubectl", "-n", namespace, "get", "pdb", "-l", selector, "-o", "json"], optional=True
    )
    metrics_service = load_json(
        ["kubectl", "-n", namespace, "get", "service", "-l", selector, "-o", "json"], optional=True
    )
    monitor = load_json(
        ["kubectl", "-n", namespace, "get", "servicemonitor", "-l", selector, "-o", "json"],
        optional=True,
    )
    tunnel["pdbCount"] = len(pdb.get("items", []))
    tunnel["metricsServiceCount"] = len(metrics_service.get("items", []))
    tunnel["serviceMonitorCount"] = len(monitor.get("items", []))
    container = (tunnel.get("containers") or [{}])[0]
    ready_pods = [p for p in tunnel["pods"] if p["ready"] and not p["terminating"]]
    strategy = tunnel.get("strategy") or {}
    rolling = strategy.get("rollingUpdate", {})
    anti_affinity = (tunnel.get("affinity") or {}).get("podAntiAffinity", {})
    required_spread = anti_affinity.get("requiredDuringSchedulingIgnoredDuringExecution", [])
    pdb_items = pdb.get("items", [])
    service_items = metrics_service.get("items", [])
    checks = {
        "TUNNEL_CHART_VERSION_MISMATCH": matches[0].get("chart") != "cloudflare-tunnel-0.3.2",
        "IMAGE_NOT_IMMUTABLE": container.get("image") != EXPECTED_IMAGE,
        "TUNNEL_READY_REPLICAS_INSUFFICIENT": len(ready_pods) < 2,
        "TUNNEL_UNSPREAD": len({p["node"] for p in ready_pods}) < 2,
        "TUNNEL_ANTI_AFFINITY_MISSING": not any(
            term.get("topologyKey") == "kubernetes.io/hostname" for term in required_spread
        ),
        "TUNNEL_UNSAFE_ROLLOUT": strategy.get("type", "RollingUpdate") != "RollingUpdate"
        or str(rolling.get("maxUnavailable")) != "0"
        or str(rolling.get("maxSurge")) != "1",
        "TUNNEL_PROBE_CONTRACT": container.get("readinessProbe", {}).get("httpGet", {}).get("path")
        != "/ready"
        or container.get("livenessProbe") is not None,
        "TUNNEL_PDB_MISSING": len(pdb_items) != 1
        or pdb_items[0].get("spec", {}).get("minAvailable") != 1,
        "TUNNEL_METRICS_DISCOVERY_MISSING": len(service_items) != 1
        or service_items[0].get("spec", {}).get("type", "ClusterIP") != "ClusterIP"
        or service_items[0].get("spec", {}).get("clusterIP") == "None"
        or tunnel["serviceMonitorCount"] != 1,
    }
    for code, failed in checks.items():
        if failed:
            gap(gaps, code, code.lower().replace("_", " "))
    metrics = {
        "healthyTargetCount": prom_value(
            "/api/v1/namespaces/monitoring/services/"
            "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
            "count(up%7Bservice%3D%22cloudflare-tunnel-metrics%22%7D%20%3D%3D%201)"
        ),
        "connectorsWithFourHAConnections": prom_value(
            "/api/v1/namespaces/monitoring/services/"
            "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
            "count(cloudflared_tunnel_ha_connections%7Bservice%3D%22"
            "cloudflare-tunnel-metrics%22%7D%20%3E%3D%204)"
        ),
        "firingRelevantAlerts": prom_value(
            "/api/v1/namespaces/monitoring/services/"
            "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
            "count(ALERTS%7Balertname%3D~%22CloudflareTunnel.%2A%22%2C"
            "alertstate%3D%22firing%22%7D)"
        ),
    }
    if metrics["healthyTargetCount"] < len(ready_pods):
        gap(
            gaps,
            "TUNNEL_METRICS_TARGETS_UNHEALTHY",
            "fewer healthy metrics targets than Ready connectors",
        )
    if metrics["connectorsWithFourHAConnections"] < len(ready_pods):
        gap(
            gaps,
            "TUNNEL_HA_CONNECTIONS_INSUFFICIENT",
            "fewer than four HA connections per Ready connector",
        )
    if metrics["firingRelevantAlerts"]:
        gap(gaps, "TUNNEL_ALERT_FIRING", "a relevant Cloudflare Tunnel alert is firing")

    targets = json.loads((ROOT / "config/production-resilience-audit-targets.json").read_text())[
        "targets"
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
        probes = sorted(pool.map(probe, targets), key=lambda p: p["url"])
    for p in probes:
        if p["error"] != "none" or not 200 <= p["status"] < 400:
            gap(gaps, "ENDPOINT_PROBE_FAILED", f"approved endpoint failed: {p['url']}")
    gaps.sort(key=lambda x: (x["code"], x["detail"]))
    timestamp = os.environ.get("SUGARKUBE_AUDIT_TIMESTAMP") or dt.datetime.now(
        dt.timezone.utc
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    audit = {
        "schemaVersion": 1,
        "timestamp": timestamp,
        "gitRevision": run(["git", "rev-parse", "HEAD"]).strip(),
        "environment": "prod",
        "context": context,
        "result": "PARITY_OK" if not gaps else "PARITY_GAPS",
        "gapCount": len(gaps),
        "gaps": gaps,
        "observed": {
            "nodes": sorted(node_state, key=lambda n: n["name"]),
            "apiReadyz": readyz_lines,
            "components": components,
            "endpointSlices": endpoints,
            "lifecycle": lifecycle,
            "cloudflareTunnel": tunnel,
            "prometheus": metrics,
            "probes": probes,
        },
    }
    out = args.evidence_dir
    out.mkdir(parents=True, exist_ok=False)
    (out / "audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    (out / "endpoints.tsv").write_text(
        "url\tstatus\tconnect_seconds\tstart_transfer_seconds\ttotal_seconds\terror\n"
        + "".join(
            "\t".join(
                str(value or "")
                for value in (
                    p["url"],
                    p["status"],
                    p["connectSeconds"],
                    p["startTransferSeconds"],
                    p["totalSeconds"],
                    p["error"],
                )
            )
            + "\n"
            for p in probes
        )
    )
    rows = (
        "\n".join(f"| `{g['code']}` | {g['detail']} |" for g in gaps)
        or "| — | No parity gaps observed. |"
    )
    (out / "summary.md").write_text(
        "# Production resilience parity audit\n\n"
        f"**Result:** `{audit['result']}` — {len(gaps)} gap(s).\n\n"
        f"| Gap code | Detail |\n|---|---|\n{rows}\n"
    )
    files = sorted(p for p in out.iterdir() if p.name != "sha256sums.txt")
    (out / "sha256sums.txt").write_text(
        "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files)
    )
    print(
        f"{audit['result']}: collection completed with {len(gaps)} parity gap(s); evidence: {out}"
    )
    return 1 if args.require_parity and gaps else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectionError as exc:
        print(f"COLLECTION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(2)
