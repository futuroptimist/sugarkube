#!/usr/bin/env python3
"""Strictly read-only, sanitized production resilience parity audit."""

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
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
NODES = {"sugarkube0", "sugarkube1", "sugarkube2"}
IMAGE = (
    "cloudflare/cloudflared:2026.7.3@sha256:"
    "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)
KUBECTL_FORBIDDEN = {
    "apply",
    "create",
    "patch",
    "replace",
    "delete",
    "edit",
    "run",
    "exec",
    "port-forward",
}
HELM_FORBIDDEN = {"install", "upgrade", "rollback", "uninstall", "repo"}


class AuditError(RuntimeError):
    pass


def run(cmd, optional=False):
    """Execute only an explicitly read-only command."""
    if cmd[0] not in {"kubectl", "helm", "curl", "git"}:
        raise AuditError(f"unsafe executable: {cmd[0]}")
    if cmd[0] == "kubectl" and KUBECTL_FORBIDDEN.intersection(cmd[1:]):
        raise AuditError("mutating kubectl command rejected")
    if cmd[0] == "helm" and HELM_FORBIDDEN.intersection(cmd[1:]):
        raise AuditError("mutating helm command rejected")
    p = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if p.returncode and not optional:
        raise AuditError(f"read-only command failed: {cmd[0]} {cmd[1]} ({p.returncode})")
    return p.stdout


def jrun(cmd, optional=False):
    raw = run(cmd, optional)
    if optional and not raw.strip():
        return {"items": []}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise AuditError(f"invalid JSON from {cmd[0]} {cmd[1]}") from e


def kube(*args, optional=False):
    return jrun(["kubectl", *args], optional=optional)


def items(kind, optional=False):
    data = kube("get", kind, "-A", "-o", "json", optional=optional)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise AuditError(f"malformed {kind} list")
    return data["items"]


def meta(x):
    m = x.get("metadata", {})
    return {k: m[k] for k in ("name", "namespace", "uid", "generation") if k in m}


def ownership_labels(obj):
    labels = obj.get("metadata", {}).get("labels", {})
    allowed = {
        "app.kubernetes.io/managed-by",
        "app.kubernetes.io/name",
        "app.kubernetes.io/instance",
        "sugarkube.dev/managed-by",
    }
    return {key: labels[key] for key in sorted(allowed & labels.keys())}


def owned_config(x):
    """Describe ownership and presence without retaining arbitrary valuesContent."""
    m = x.get("metadata", {})
    s = x.get("spec", {})
    return {
        "metadata": meta(x),
        "labels": ownership_labels(x),
        "ownerKinds": sorted(o.get("kind", "") for o in m.get("ownerReferences", [])),
        "targetChart": s.get("targetNamespace"),
        "desiredConfigurationPresent": bool(s),
    }


def ready(p):
    return p.get("metadata", {}).get("deletionTimestamp") is None and any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in p.get("status", {}).get("conditions", [])
    )


def psum(p):
    return {
        "name": p.get("metadata", {}).get("name"),
        "uid": p.get("metadata", {}).get("uid"),
        "node": p.get("spec", {}).get("nodeName"),
        "ready": ready(p),
        "restarts": sum(
            int(c.get("restartCount", 0)) for c in p.get("status", {}).get("containerStatuses", [])
        ),
    }


def dsum(d):
    s = d.get("spec", {})
    t = s.get("template", {}).get("spec", {})
    st = d.get("status", {})
    return {
        **meta(d),
        "labels": ownership_labels(d),
        "ownerKinds": sorted(
            o.get("kind", "") for o in d.get("metadata", {}).get("ownerReferences", [])
        ),
        "desired": s.get("replicas", 1),
        "ready": st.get("readyReplicas", 0),
        "available": st.get("availableReplicas", 0),
        "strategy": s.get("strategy", {}),
        "affinity": t.get("affinity", {}),
        "topologySpreadConstraints": t.get("topologySpreadConstraints", []),
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
            for c in t.get("containers", [])
        ],
    }


def epsummary(all_slices, service):
    groups = {}
    selected = [
        x
        for x in all_slices
        if x.get("metadata", {}).get("labels", {}).get("kubernetes.io/service-name") == service
    ]
    for sl in selected:
        for ep in sl.get("endpoints", []):
            c = ep.get("conditions", {})
            r = c.get("ready", True)
            s = c.get("serving", r)
            t = c.get("terminating", False)
            ref = ep.get("targetRef", {})
            key = (
                ep.get("nodeName") or "",
                tuple(sorted(ep.get("addresses", []))),
                ref.get("uid") or ref.get("name") or "",
            )
            groups.setdefault(key, []).append((r is True, s is True, t is True))
    good = [k for k, v in groups.items() if all(r and s and not t for r, s, t in v)]
    return {
        "service": service,
        "slices": len(selected),
        "uniqueEndpoints": len(groups),
        "healthyEndpoints": len(good),
        "healthyNodes": sorted({k[0] for k in good if k[0]}),
        "unhealthyEndpoints": len(groups) - len(good),
    }


def scalar(x):
    try:
        return float(x["data"]["result"][0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def prom(q):
    proxy = "/api/v1/namespaces/monitoring/services/"
    proxy += "http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query="
    return scalar(
        kube(
            "get",
            "--raw",
            proxy + quote(q, safe=""),
        )
    )


def probe(url):
    mark = "__AUDIT__"
    p = subprocess.run(
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
            mark + "%{http_code}\\t%{time_connect}\\t%{time_starttransfer}\\t%{time_total}",
            url,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    m = re.search(re.escape(mark) + r"(\d{3})\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)", p.stdout)
    err = (
        "none"
        if p.returncode == 0
        else {28: "timeout", 6: "dns", 7: "connect", 35: "tls"}.get(p.returncode, "request")
    )
    return {
        "url": url,
        "status": int(m.group(1)) if m else 0,
        "connectSeconds": float(m.group(2)) if m else None,
        "startTransferSeconds": float(m.group(3)) if m else None,
        "totalSeconds": float(m.group(4)) if m else None,
        "error": err,
    }


def add(gaps, code, detail):
    gaps.append({"code": code, "detail": detail})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--require-parity", action="store_true")
    a = ap.parse_args(argv)
    if a.env.removeprefix("env=").strip() != "prod":
        raise AuditError("env must normalize exactly to prod")
    for tool in ("kubectl", "helm", "curl", "git"):
        if not shutil.which(tool):
            raise AuditError(f"required read-only tool '{tool}' was not found")
    context = run(["kubectl", "config", "current-context"]).strip()
    if context != "sugar-prod":
        raise AuditError("current kubectl context must be exactly sugar-prod")
    nd = kube("get", "nodes", "-o", "json")
    nodes = nd.get("items", [])
    names = {n.get("metadata", {}).get("name") for n in nodes}
    if names != NODES:
        raise AuditError(f"observed node set is not exact: {sorted(names)}")
    if {n.get("metadata", {}).get("labels", {}).get("sugarkube.env") for n in nodes} != {
        "prod"
    } or len(
        {n.get("metadata", {}).get("labels", {}).get("sugarkube.cluster") for n in nodes}
        - {None, ""}
    ) != 1:
        raise AuditError(
            "repository cluster-identity detection does not report an unambiguous prod cluster"
        )
    gaps = []
    node_state = []
    for n in sorted(nodes, key=lambda x: x["metadata"]["name"]):
        cs = [
            {"type": c.get("type"), "status": c.get("status"), "reason": c.get("reason")}
            for c in n.get("status", {}).get("conditions", [])
            if c.get("type") == "Ready"
        ]
        node_state.append({"name": n["metadata"]["name"], "readyConditions": cs})
        if not any(c["status"] == "True" for c in cs):
            add(gaps, "NODE_NOT_READY", n["metadata"]["name"])
    readyz = sorted(
        x.strip()
        for x in run(["kubectl", "get", "--raw", "/readyz?verbose"]).splitlines()
        if x.strip()
    )
    if not any("etcd" in x and "ok" in x.lower() for x in readyz):
        add(gaps, "APISERVER_ETCD_NOT_READY", "etcd not reported ready")
    deps = items("deployments.apps")
    pods = items("pods")
    pdbs = items("poddisruptionbudgets.policy", True)
    svcs = items("services")
    slices = items("endpointslices.discovery.k8s.io")
    configs = items("helmchartconfigs.helm.cattle.io", True)
    monitors = items("servicemonitors.monitoring.coreos.com", True)
    components = {}
    for name in ("coredns", "traefik"):
        wanted = {name, "coredns-ha"} if name == "coredns" else {name}
        ds = [
            d
            for d in deps
            if d.get("metadata", {}).get("namespace") == "kube-system"
            and d.get("metadata", {}).get("name") in wanted
        ]
        pp = [
            psum(p)
            for p in pods
            if p.get("metadata", {}).get("namespace") == "kube-system"
            and name
            in (
                p.get("metadata", {}).get("labels", {}).get("k8s-app", "")
                + p.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name", "")
            )
        ]
        component_pdbs = [
            {"metadata": meta(x), "spec": x.get("spec", {})}
            for x in pdbs
            if x.get("metadata", {}).get("namespace") == "kube-system"
            and name in x.get("metadata", {}).get("name", "")
        ]
        components[name] = {
            "deployments": [dsum(d) for d in ds],
            "pods": sorted(pp, key=lambda x: x["name"]),
            "pdbs": component_pdbs,
            "endpoints": epsummary(slices, "kube-dns" if name == "coredns" else "traefik"),
        }
        desired = sum(d["desired"] for d in components[name]["deployments"])
        rn = {p["node"] for p in pp if p["ready"]}
        if desired < 2:
            add(gaps, name.upper() + "_SINGLETON", f"desired replicas={desired}")
        if len(rn) < 2:
            add(gaps, name.upper() + "_INSUFFICIENT_SPREAD", f"ready nodes={sorted(rn)}")
    ts = [
        s
        for s in svcs
        if s.get("metadata", {}).get("namespace") == "kube-system"
        and s.get("metadata", {}).get("name") == "traefik"
    ]
    policy = ts[0].get("spec", {}).get("internalTrafficPolicy") if ts else None
    if policy != "Local":
        add(gaps, "TRAEFIK_INTERNAL_TRAFFIC_POLICY", f"observed={policy or 'unset'}")
    releases = jrun(["helm", "list", "-A", "-o", "json"])
    candidates = [
        d
        for d in deps
        if d.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name")
        in {"cloudflare-tunnel", "cloudflared"}
        or any(
            str(c.get("image", "")).split("@")[0].split(":")[0].endswith("/cloudflared")
            for c in d.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        )
    ]
    if len(candidates) != 1:
        raise AuditError(
            f"expected exactly one live Cloudflare Deployment candidate; found {len(candidates)}"
        )
    dep = candidates[0]
    m = dep.get("metadata", {})
    labels = m.get("labels", {})
    rel = labels.get("app.kubernetes.io/instance") or labels.get("meta.helm.sh/release-name")
    ns = m.get("namespace")
    matches = [r for r in releases if r.get("name") == rel and r.get("namespace") == ns]
    if len(matches) != 1:
        raise AuditError(
            "expected exactly one Helm release for live Cloudflare Deployment; "
            f"found {len(matches)}"
        )
    release = matches[0]
    hist = jrun(["helm", "history", rel, "-n", ns, "-o", "json"])
    cp = [
        psum(p)
        for p in pods
        if p.get("metadata", {}).get("namespace") == ns
        and p.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/instance") == rel
    ]
    cf = {
        "namespace": ns,
        "release": rel,
        "chart": release.get("chart"),
        "appVersion": release.get("app_version"),
        "status": release.get("status"),
        "revision": release.get("revision"),
        "history": [
            {k: h.get(k) for k in ("revision", "status", "chart", "app_version")} for h in hist
        ],
        "deployment": dsum(dep),
        "pods": sorted(cp, key=lambda x: x["name"]),
        "pdbs": [
            {"metadata": meta(x), "spec": x.get("spec", {})}
            for x in pdbs
            if x.get("metadata", {}).get("namespace") == ns
        ],
        "metricsServices": [
            {
                "metadata": meta(x),
                "type": x.get("spec", {}).get("type"),
                "ports": x.get("spec", {}).get("ports", []),
            }
            for x in svcs
            if x.get("metadata", {}).get("namespace") == ns
            and "metrics" in x.get("metadata", {}).get("name", "")
        ],
        "serviceMonitors": [
            meta(x) for x in monitors if x.get("metadata", {}).get("namespace") == ns
        ],
    }
    c = cf["deployment"]["containers"][0] if cf["deployment"]["containers"] else {}
    rp = [p for p in cp if p["ready"]]
    strategy = cf["deployment"]["strategy"].get("rollingUpdate", {})
    checks = [
        (c.get("image") == IMAGE, "CF_IMAGE_IMMUTABLE"),
        (len(rp) >= 2, "CF_READY_CONNECTORS"),
        (len({p["node"] for p in rp}) >= 2, "CF_CONNECTOR_SPREAD"),
        (
            strategy.get("maxUnavailable") == 0 and strategy.get("maxSurge") == 1,
            "CF_UNSAFE_ROLLOUT",
        ),
        (
            c.get("readinessProbe", {}).get("httpGet", {}).get("path") == "/ready"
            and not c.get("livenessProbe"),
            "CF_PROBE_CONTRACT",
        ),
        (any(x.get("spec", {}).get("minAvailable") == 1 for x in cf["pdbs"]), "CF_PDB_MISSING"),
        (
            bool(cf["metricsServices"]) and bool(cf["serviceMonitors"]),
            "CF_PRIVATE_METRICS_DISCOVERY",
        ),
    ]
    for ok, code in checks:
        if not ok:
            add(gaps, code, "live release differs from staging-proven contract")
    metrics = {
        "healthyTargets": int(prom(f'count(up{{namespace="{ns}",service=~".*metrics"}} == 1)')),
        "connectorsWithFourHAConnections": int(
            prom(f'count(cloudflared_tunnel_ha_connections{{namespace="{ns}"}} >= 4)')
        ),
        "firingRelevantAlerts": int(
            prom(
                'count(ALERTS{alertname=~"CloudflareTunnel(NoHealthyConnections|'
                'ConnectionsDegraded|MetricsTargetsDown)",alertstate="firing"})'
            )
        ),
    }
    if metrics["healthyTargets"] < len(rp):
        add(gaps, "CF_METRICS_TARGETS_UNHEALTHY", "healthy targets below Ready connectors")
    if metrics["connectorsWithFourHAConnections"] < len(rp):
        add(gaps, "CF_HA_CONNECTIONS_LOW", "fewer than four HA connections per Ready connector")
    if metrics["firingRelevantAlerts"]:
        add(gaps, "CF_ALERT_FIRING", "relevant alert firing")
    targets = json.loads((ROOT / "config/prod-resilience-audit-targets.json").read_text())
    urls = sorted(f"https://{h}{p}" for h, paths in targets.items() for p in paths)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(urls)) as pool:
        endpoints = sorted(pool.map(probe, urls), key=lambda x: x["url"])
    for x in endpoints:
        if not 200 <= x["status"] < 400:
            add(gaps, "PUBLIC_ENDPOINT_UNHEALTHY", x["url"])
    gaps.sort(key=lambda x: (x["code"], x["detail"]))
    stamp = os.environ.get("SUGARKUBE_AUDIT_TIMESTAMP") or dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    audit = {
        "schemaVersion": 1,
        "timestamp": stamp,
        "gitRevision": run(["git", "rev-parse", "HEAD"]).strip(),
        "environment": "prod",
        "context": context,
        "result": "PARITY_OK" if not gaps else "PARITY_GAPS",
        "gapCount": len(gaps),
        "gaps": gaps,
        "nodes": node_state,
        "apiReadyz": readyz,
        "dnsIngress": {
            "components": components,
            "traefikInternalTrafficPolicy": policy,
            "helmChartConfigs": [owned_config(x) for x in configs],
        },
        "cloudflareTunnel": cf,
        "prometheus": metrics,
        "endpoints": endpoints,
    }
    out = Path(a.evidence_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n")
    (out / "endpoints.tsv").write_text(
        "url\tstatus\tconnect_seconds\tstart_transfer_seconds\ttotal_seconds\terror\n"
        + "".join(
            "\t".join(
                str(x[key])
                for key in (
                    "url",
                    "status",
                    "connectSeconds",
                    "startTransferSeconds",
                    "totalSeconds",
                    "error",
                )
            )
            + "\n"
            for x in endpoints
        )
    )
    rows = (
        "\n".join(f'| `{x["code"]}` | {x["detail"]} |' for x in gaps)
        or "| — | No parity gaps observed. |"
    )
    (out / "summary.md").write_text(
        "# Production resilience parity audit\n\n"
        f"**Result:** `{audit['result']}`  \n**Gaps:** {len(gaps)}\n\n"
        f"| Gap code | Detail |\n|---|---|\n{rows}\n"
    )
    fs = sorted(p for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text(
        "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in fs)
    )
    print(f"{audit['result']}: collection complete; {len(gaps)} parity gap(s); evidence: {out}")
    return 1 if a.require_parity and gaps else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as e:
        print(f"AUDIT_COLLECTION_FAILED: {e}", file=sys.stderr)
        raise SystemExit(2)
