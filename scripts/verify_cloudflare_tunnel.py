#!/usr/bin/env python3
"""Read-only verification for the manually managed staging tunnel release."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse

NAMESPACE = "cloudflare"
RELEASE = "cloudflare-tunnel"
IMAGE = (
    "cloudflare/cloudflared@sha256:e39ee8da81ad5e05d77f38d2f51c60ca51bf2a8450ac3abab50c17fdb91d91bf"
)
SELECTOR = {"app.kubernetes.io/name": RELEASE, "app.kubernetes.io/instance": RELEASE}
PROM_PROXY = (
    "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy"
)
ALERTS = {
    "CloudflareTunnelNoHealthyConnections",
    "CloudflareTunnelConnectionsDegraded",
    "CloudflareTunnelMetricsTargetsDown",
}


class VerificationError(RuntimeError):
    """A staging contract was not satisfied."""


def run(*args: str) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode:
        raise VerificationError(f"command failed ({' '.join(args)}): {result.stderr.strip()}")
    return result.stdout


def kubectl_json(*args: str) -> dict:
    return json.loads(run("kubectl", *args, "-o", "json"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)
    print(f"PASS: {message}")


def prometheus(path: str, params: dict[str, str] | None = None) -> dict:
    query = urllib.parse.urlencode(params or {})
    suffix = f"?{query}" if query else ""
    payload = json.loads(run("kubectl", "get", "--raw", f"{PROM_PROXY}{path}{suffix}"))
    require(payload.get("status") == "success", f"Prometheus request {path} succeeded")
    return payload["data"]


def query_scalar(expression: str) -> float:
    result = prometheus("/api/v1/query", {"query": expression})["result"]
    require(len(result) == 1, f"Prometheus returned one result for {expression}")
    return float(result[0]["value"][1])


def main() -> int:
    supplied = sys.argv[1] if len(sys.argv) > 1 else "staging"
    env = supplied.removeprefix("env=")
    require(env in {"staging", "int"}, "verification is restricted to staging")
    run(sys.executable, "scripts/cluster_identity.py", "assert", "--env", "staging")
    print("PASS: kube context identifies the staging cluster")

    releases = json.loads(run("helm", "list", "-A", "--output", "json"))
    owned = [r for r in releases if r.get("name") == RELEASE]
    require(len(owned) == 1, "exactly one cloudflare-tunnel Helm release exists")
    require(owned[0].get("namespace") == NAMESPACE, "the Helm release is in namespace cloudflare")
    require(
        owned[0].get("chart") == "cloudflare-tunnel-0.3.2",
        "the Helm chart is cloudflare-tunnel-0.3.2",
    )

    deployment = kubectl_json("-n", NAMESPACE, "get", "deployment", RELEASE)
    require(
        deployment["metadata"].get("annotations", {}).get("meta.helm.sh/release-name") == RELEASE,
        "the Deployment is owned by the unique Helm release",
    )
    spec = deployment["spec"]
    require(spec.get("replicas") == 2, "the Deployment requests two replicas")
    strategy = spec.get("strategy", {}).get("rollingUpdate", {})
    require(
        str(strategy.get("maxUnavailable")) == "0" and str(strategy.get("maxSurge")) == "1",
        "rolling updates use maxUnavailable 0 and maxSurge 1",
    )
    container = spec["template"]["spec"]["containers"][0]
    require(
        container.get("image") == IMAGE, "the connector uses the supported immutable 2026.7.3 image"
    )
    require("livenessProbe" not in container, "no WAN-sensitive liveness probe is configured")
    ready = container.get("readinessProbe", {})
    require(
        ready.get("httpGet") == {"path": "/ready", "port": 2000},
        "/ready on port 2000 is the readiness probe",
    )
    env_vars = {item["name"]: item for item in container.get("env", [])}
    ref = env_vars.get("TUNNEL_TOKEN", {}).get("valueFrom", {}).get("secretKeyRef", {})
    require(
        ref == {"name": "tunnel-token", "key": "token"},
        "TUNNEL_TOKEN references tunnel-token key token without reading it",
    )

    pods = kubectl_json(
        "-n", NAMESPACE, "get", "pods", "-l", "app.kubernetes.io/name=cloudflare-tunnel"
    )["items"]
    require(len(pods) == 2, "exactly two connector pods exist")
    require(
        len({pod["spec"].get("nodeName") for pod in pods}) == 2,
        "the connectors run on separate nodes",
    )

    pdb = kubectl_json("-n", NAMESPACE, "get", "poddisruptionbudget", RELEASE)
    require(pdb["spec"].get("minAvailable") == 1, "the disruption budget preserves one connector")
    service = kubectl_json("-n", NAMESPACE, "get", "service", RELEASE)
    require(
        service["spec"].get("type") == "ClusterIP" and service["spec"].get("selector") == SELECTOR,
        "the internal metrics Service selects only this release",
    )
    port = service["spec"]["ports"][0]
    require(
        port.get("name") == "metrics" and port.get("targetPort") == 2000,
        "the metrics Service exposes named port metrics to target port 2000",
    )
    monitor = kubectl_json("-n", NAMESPACE, "get", "servicemonitor", RELEASE)
    require(
        monitor["spec"].get("selector", {}).get("matchLabels") == SELECTOR,
        "the ServiceMonitor selects only this tunnel release",
    )

    target_filter = 'up{namespace="cloudflare",service="cloudflare-tunnel"}'
    require(query_scalar(f"count({target_filter})") == 2, "Prometheus sees two connector targets")
    require(
        query_scalar(f"sum({target_filter})") == 2, "both connector metrics targets are healthy"
    )
    ha = 'cloudflared_tunnel_ha_connections{namespace="cloudflare",service="cloudflare-tunnel"}'
    require(query_scalar(f"count({ha})") == 2, "Prometheus sees HA metrics from both connectors")
    require(query_scalar(f"min({ha})") >= 4, "each connector reports at least four HA connections")

    groups = prometheus("/api/v1/rules", {"type": "alert"})["groups"]
    rules = {rule["name"]: rule for group in groups for rule in group.get("rules", [])}
    require(ALERTS <= rules.keys(), "all Cloudflare Tunnel alerts are loaded")
    require(
        all(
            rules[name].get("health") == "ok" and not rules[name].get("lastError")
            for name in ALERTS
        ),
        "all Cloudflare Tunnel alerts evaluate successfully",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (VerificationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
