#!/usr/bin/env python3
"""Read-only verification for the staging Cloudflare Tunnel release."""

from __future__ import annotations

import json
import subprocess
import sys

NAMESPACE = "cloudflare"
RELEASE = "cloudflare-tunnel"
IMAGE = (
    "cloudflare/cloudflared:2026.7.3@sha256:"
    "e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)
PROM_API = "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy"


def run(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(
            f"ERROR: read-only command failed: {' '.join(args)}\n{result.stderr.strip()}"
        )
    return result.stdout


def kube_json(*args: str) -> dict:
    return json.loads(run("kubectl", *args, "-o", "json"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"ERROR: {message}")


def prometheus(path: str) -> dict:
    return json.loads(run("kubectl", "get", "--raw", PROM_API + path))


def main() -> int:
    run("python3", "scripts/cluster_identity.py", "assert", "--env", "staging")
    releases = json.loads(run("helm", "-n", NAMESPACE, "list", "--all", "--output", "json"))
    owned = [item for item in releases if item.get("name") == RELEASE]
    require(len(owned) == 1, "expected one uniquely owned cloudflare-tunnel Helm release")
    require(owned[0].get("chart") == "cloudflare-tunnel-0.3.2", "unexpected Helm chart/version")

    deployment = kube_json("-n", NAMESPACE, "get", "deployment", RELEASE)
    spec = deployment["spec"]
    require(spec.get("replicas") == 2, "deployment must have exactly two replicas")
    rolling = spec.get("strategy", {}).get("rollingUpdate", {})
    require(rolling == {"maxSurge": 1, "maxUnavailable": 0}, "rollout strategy is not HA-safe")
    container = spec["template"]["spec"]["containers"][0]
    require(container.get("image") == IMAGE, "connector image is not the supported immutable image")
    require("livenessProbe" not in container, "WAN-sensitive liveness probe is present")
    readiness = container.get("readinessProbe", {})
    require(
        readiness.get("httpGet") == {"path": "/ready", "port": 2000}, "/ready is not readiness-only"
    )
    refs = [e.get("valueFrom", {}).get("secretKeyRef") for e in container.get("env", [])]
    require(
        {"name": "tunnel-token", "key": "token"} in refs,
        "expected token Secret reference is absent",
    )

    pods = kube_json(
        "-n", NAMESPACE, "get", "pods", "-l", "app.kubernetes.io/name=cloudflare-tunnel"
    )["items"]
    require(len(pods) == 2, "expected exactly two connector pods")
    require(
        len({pod["spec"].get("nodeName") for pod in pods}) == 2,
        "connectors are not on separate nodes",
    )

    pdb = kube_json("-n", NAMESPACE, "get", "pdb", RELEASE)
    require(pdb["spec"].get("minAvailable") == 1, "PDB must retain one available connector")
    service = kube_json("-n", NAMESPACE, "get", "service", "cloudflare-tunnel-metrics")
    monitor = kube_json("-n", NAMESPACE, "get", "servicemonitor", RELEASE)
    selector = {"app.kubernetes.io/name": RELEASE, "app.kubernetes.io/instance": RELEASE}
    require(service["spec"].get("selector") == selector, "metrics Service selector drifted")
    require(
        monitor["spec"]["selector"].get("matchLabels") == selector,
        "ServiceMonitor selector drifted",
    )

    targets = prometheus("/api/v1/targets")["data"]["activeTargets"]
    targets = [
        t
        for t in targets
        if t.get("labels", {}).get("namespace") == NAMESPACE
        and t.get("labels", {}).get("service") == "cloudflare-tunnel-metrics"
    ]
    require(
        len(targets) == 2 and all(t.get("health") == "up" for t in targets),
        "Prometheus does not see two healthy connector targets",
    )
    query = prometheus(
        "/api/v1/query?query=cloudflared_tunnel_ha_connections%7Bnamespace%3D%22cloudflare%22%7D"
    )
    series = query["data"]["result"]
    require(
        len(series) == 2 and all(float(item["value"][1]) >= 4 for item in series),
        "each connector must report at least four HA connections",
    )
    rules = prometheus("/api/v1/rules")["data"]["groups"]
    wanted = {
        "CloudflareTunnelNoConnections",
        "CloudflareTunnelDegraded",
        "CloudflareTunnelMetricsDown",
    }
    loaded = {
        rule.get("name")
        for group in rules
        for rule in group.get("rules", [])
        if rule.get("health") == "ok"
    }
    require(wanted <= loaded, "Cloudflare Tunnel alert rules are not loaded and healthy")
    print(
        "Cloudflare Tunnel staging release, HA lifecycle, metrics, "
        "connections, and alerts verified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
