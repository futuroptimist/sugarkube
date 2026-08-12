#!/usr/bin/env python3
"""Collect a sanitized, strictly read-only production resilience inventory."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import shlex
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
FORBIDDEN = {"apply", "create", "patch", "replace", "delete", "edit", "run", "exec", "port-forward"}


class HardFailure(RuntimeError):
    pass


def run(argv: list[str], *, ok=(0,), timeout=30) -> subprocess.CompletedProcess[str]:
    if argv[0] == "kubectl":
        words = set(argv[1:])
        if words & FORBIDDEN or ("rollout" in words and "restart" in words):
            raise HardFailure("internal safety policy rejected a mutating kubectl command")
    if argv[0] == "helm" and set(argv[1:]) & {
        "install",
        "upgrade",
        "rollback",
        "uninstall",
        "repo",
        "push",
    }:
        raise HardFailure("internal safety policy rejected a mutating helm command")
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    if proc.returncode not in ok:
        stderr = " ".join(proc.stderr.split())[:500] or "<empty>"
        raise HardFailure(
            f"read-only command failed (exit {proc.returncode}): {shlex.join(argv)}; "
            f"stderr: {stderr}"
        )
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
    urls = sorted(
        f"https://{host}{path}"
        for host, paths in target_map.items()
        if isinstance(paths, list)
        for path in paths
    )
    if not urls:
        raise HardFailure("production probe target manifest contains no URLs")
    return urls


def probes_unhealthy(rows: list[dict[str, Any]]) -> bool:
    return any(row.get("error") or not 200 <= row["status"] < 400 for row in rows)


def ready(pod: dict[str, Any]) -> bool:
    return pod.get("metadata", {}).get("deletionTimestamp") is None and any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in pod.get("status", {}).get("conditions", [])
    )


def pods_snapshot(document: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for pod in document.get("items", []):
        result.append(
            {
                "uid": pod.get("metadata", {}).get("uid"),
                "node": pod.get("spec", {}).get("nodeName"),
                "ready": ready(pod),
                "restarts": sum(
                    int(c.get("restartCount", 0))
                    for c in pod.get("status", {}).get("containerStatuses", [])
                ),
            }
        )
    return sorted(result, key=lambda p: (p["node"] or "", p["uid"] or ""))


def deployment_snapshot(dep: dict[str, Any]) -> dict[str, Any]:
    meta, spec, status = dep.get("metadata", {}), dep.get("spec", {}), dep.get("status", {})
    pod_spec = spec.get("template", {}).get("spec", {})
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

    for c in pod_spec.get("containers", []):
        refs = []
        for env in c.get("env", []):
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
        if item.get("metadata", {}).get("labels", {}).get("kubernetes.io/service-name") != service:
            raise HardFailure("EndpointSlice selector returned an unrelated Service")
        for endpoint in item.get("endpoints", []):
            cond = endpoint.get("conditions", {})
            effective_ready = cond.get("ready", True)
            serving = cond.get("serving", effective_ready)
            terminating = cond.get("terminating", False)
            target = endpoint.get("targetRef", {})
            key = (
                endpoint.get("nodeName") or "",
                tuple(sorted(set(endpoint.get("addresses", [])))),
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
                url,
            ],
            ok=tuple(range(0, 100)),
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"url": url, "status": 0, "error": "timeout"}
    fields = proc.stdout.strip().split("\t")
    status = int(fields[0]) if fields and fields[0].isdigit() else 0
    row: dict[str, Any] = {"url": url, "status": status}
    if len(fields) == 4:
        row.update(zip(("connectSeconds", "startTransferSeconds", "totalSeconds"), fields[1:]))
    if proc.returncode:
        row["error"] = "timeout" if proc.returncode == 28 else "transport"
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--require-parity", action="store_true")
    args = parser.parse_args()
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
    names = {n.get("metadata", {}).get("name") for n in nodes_doc.get("items", [])}
    if names != EXPECTED_NODES:
        raise HardFailure("observed node set is not exactly sugarkube0, sugarkube1, sugarkube2")
    nodes = []
    for node in nodes_doc["items"]:
        conditions = {
            c.get("type"): c.get("status") for c in node.get("status", {}).get("conditions", [])
        }
        nodes.append({"name": node["metadata"]["name"], "ready": conditions.get("Ready") == "True"})
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
                else {
                    "valuesContentSha256": hashlib.sha256(
                        str(obj.get("spec", {}).get("valuesContent", "")).encode()
                    ).hexdigest()
                }
            ),
        }

    deployments = list_items(
        "get", "deployment", "-A", "-l", "app.kubernetes.io/name=cloudflare-tunnel", "-o", "json"
    )
    releases = json.loads(run(["helm", "list", "-A", "-o", "json"]).stdout)
    candidates = []
    for dep in deployments:
        meta = dep.get("metadata", {})
        labels = meta.get("labels", {})
        release_name = labels.get("app.kubernetes.io/instance") or meta.get("annotations", {}).get(
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
    ns, release_name = tunnel_dep["metadata"]["namespace"], release["name"]
    history_raw = json.loads(run(["helm", "-n", ns, "history", release_name, "-o", "json"]).stdout)
    history = [
        {k: h.get(k) for k in ("revision", "updated", "status", "chart", "app_version")}
        for h in history_raw
    ]
    status_raw = json.loads(run(["helm", "-n", ns, "status", release_name, "-o", "json"]).stdout)
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
    selector = ",".join(
        f"{k}={v}" for k, v in sorted(tunnel_dep["spec"]["selector"]["matchLabels"].items())
    )
    tunnel["pods"] = pods_snapshot(kubectl("-n", ns, "get", "pods", "-l", selector, "-o", "json"))
    ready_tunnel = [p for p in tunnel["pods"] if p["ready"]]
    container = tunnel["containers"][0] if tunnel["containers"] else {}
    strategy = tunnel["strategy"].get("rollingUpdate", {})
    add_gap(gaps, "CF_IMAGE_NOT_IMMUTABLE_PIN", container.get("image") != EXPECTED_IMAGE)
    add_gap(gaps, "CF_CHART_VERSION_MISMATCH", release.get("chart") != "cloudflare-tunnel-0.3.2")
    add_gap(gaps, "CF_HELM_RELEASE_NOT_DEPLOYED", tunnel["helmStatus"] != "deployed")
    add_gap(gaps, "CF_CONNECTORS_INSUFFICIENT", len(ready_tunnel) < 2)
    add_gap(gaps, "CF_CONNECTORS_UNSPREAD", len({p["node"] for p in ready_tunnel}) < 2)
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
    pdbs = list_items(
        "-n", ns, "get", "pdb", "-l", f"app.kubernetes.io/instance={release_name}", "-o", "json"
    )
    services = list_items(
        "-n", ns, "get", "service", "-l", f"app.kubernetes.io/instance={release_name}", "-o", "json"
    )
    monitors = list_items(
        "-n",
        ns,
        "get",
        "servicemonitor",
        "-l",
        f"app.kubernetes.io/instance={release_name}",
        "-o",
        "json",
    )
    tunnel["pdb"] = [
        {
            "name": x["metadata"]["name"],
            "minAvailable": x.get("spec", {}).get("minAvailable"),
            "maxUnavailable": x.get("spec", {}).get("maxUnavailable"),
        }
        for x in pdbs
    ]
    tunnel["metrics"] = {
        "services": [
            x["metadata"]["name"]
            for x in services
            if x.get("spec", {}).get("type", "ClusterIP") == "ClusterIP"
        ],
        "serviceMonitors": [x["metadata"]["name"] for x in monitors],
    }
    add_gap(
        gaps,
        "CF_PDB_MISSING",
        not any(
            p.get("spec", {}).get("minAvailable") == 1
            or p.get("spec", {}).get("maxUnavailable") == 1
            for p in pdbs
        ),
    )
    add_gap(gaps, "CF_METRICS_DISCOVERY_MISSING", not tunnel["metrics"]["services"] or not monitors)
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
    add_gap(gaps, "CF_METRICS_TARGETS_UNHEALTHY", metrics["healthyTargets"] < len(ready_tunnel))
    add_gap(
        gaps,
        "CF_HA_CONNECTIONS_INSUFFICIENT",
        metrics["connectorsWithFourHAConnections"] < len(ready_tunnel),
    )
    add_gap(gaps, "CF_ALERTS_FIRING", metrics["firingRelevantAlerts"] != 0)

    target_map = json.loads(TARGETS.read_text())
    urls = probe_urls(target_map)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as pool:
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HardFailure, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"HARD_FAILURE: {error}", file=sys.stderr)
        raise SystemExit(2)
