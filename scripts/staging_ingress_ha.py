#!/usr/bin/env python3
"""Guarded lifecycle for the active staging DNS/ingress HA baseline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("SUGARKUBE_HA_CONFIG", ROOT / "clusters/staging/platform-ha"))
TRAEFIK = CONFIG / "traefik-helmchartconfig.yaml"
COREDNS = CONFIG / "coredns-patch.yaml"
COREDNS_ROLLBACK = CONFIG / "coredns-rollback-patch.yaml"
TIMEOUT = os.environ.get("SUGARKUBE_HA_TIMEOUT", "180s")


def run(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=capture)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def guard(env: str) -> None:
    if env != "staging":
        fail("this mutation is staging-only; pass env=staging")
    context = run("kubectl", "config", "current-context", capture=True).stdout.strip()
    if context != "sugar-staging":
        fail(f"expected Kubernetes context sugar-staging, got {context or '<none>'}")


def objects(namespace: str, resource: str, selector: str = "") -> dict:
    command = ["kubectl", "-n", namespace, "get", resource]
    if selector:
        command += ["-l", selector]
    command += ["-o", "json"]
    return json.loads(run(*command, capture=True).stdout)


def ready_nodes(data: dict) -> set[str]:
    nodes: set[str] = set()
    for pod in data.get("items", []):
        conditions = pod.get("status", {}).get("conditions", [])
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
        node = pod.get("spec", {}).get("nodeName")
        if ready and node:
            nodes.add(node)
    return nodes


def require_spread(name: str, data: dict) -> None:
    nodes = ready_nodes(data)
    if len(nodes) < 2:
        fail(
            f"{name} needs at least two ready pods on distinct nodes; ready nodes: {sorted(nodes)}"
        )
    print(f"OK: {name} has ready pods on distinct nodes: {', '.join(sorted(nodes))}")


def require_endpoints(namespace: str, service: str) -> None:
    data = objects(namespace, "endpointslice", f"kubernetes.io/service-name={service}")
    ready = sum(
        endpoint.get("conditions", {}).get("ready") is not False
        for item in data.get("items", [])
        for endpoint in item.get("endpoints", [])
    )
    if ready < 1:
        fail(f"Service {namespace}/{service} has no ready EndpointSlice backends")
    print(f"OK: Service {namespace}/{service} has {ready} ready backend(s)")


def cloudflare_pods() -> dict:
    # Helm's standard app label is stable; discover the live namespace rather than guessing it.
    data = json.loads(
        run(
            "kubectl",
            "get",
            "pods",
            "-A",
            "-l",
            "app.kubernetes.io/name=cloudflare-tunnel",
            "-o",
            "json",
            capture=True,
        ).stdout
    )
    if not data.get("items"):
        fail(
            "no live Cloudflare tunnel pods found by label app.kubernetes.io/name=cloudflare-tunnel"
        )
    return data


def verify(env: str = "") -> None:
    guard(env)
    require_spread("CoreDNS", objects("kube-system", "pods", "k8s-app=kube-dns"))
    require_spread("Traefik", objects("kube-system", "pods", "app.kubernetes.io/name=traefik"))
    require_spread("Cloudflare tunnel", cloudflare_pods())
    require_endpoints("kube-system", "kube-dns")
    require_endpoints("kube-system", "traefik")
    name = f"sugarkube-dns-check-{os.getpid()}"
    try:
        run(
            "kubectl",
            "run",
            name,
            "-n",
            "default",
            "--restart=Never",
            "--image=busybox:1.36.1",
            "--command",
            "--",
            "nslookup",
            "kubernetes.default.svc.cluster.local",
        )
        run(
            "kubectl",
            "wait",
            "-n",
            "default",
            f"pod/{name}",
            "--for=jsonpath={.status.phase}=Succeeded",
            f"--timeout={TIMEOUT}",
        )
    finally:
        run(
            "kubectl",
            "delete",
            "pod",
            name,
            "-n",
            "default",
            "--ignore-not-found",
            "--wait=false",
            check=False,
        )
    probes = ROOT / "clusters/staging/observability/probes/public-apps.yaml"
    urls = sorted(
        {
            line.strip()[2:]
            for line in probes.read_text().splitlines()
            if line.strip().startswith("- https://")
        }
    )
    if not urls:
        fail("no canonical staging public health URLs were discovered")
    for url in urls:
        run(
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "15",
            "--output",
            os.devnull,
            url,
        )
    print(f"OK: {len(urls)} canonical public staging endpoints are reachable")


def status() -> None:
    for args in (
        ("kubectl", "-n", "kube-system", "get", "deploy", "coredns", "-o", "wide"),
        (
            "kubectl",
            "-n",
            "kube-system",
            "get",
            "deploy,svc",
            "-l",
            "app.kubernetes.io/name=traefik",
            "-o",
            "wide",
        ),
        (
            "kubectl",
            "get",
            "pods",
            "-A",
            "-l",
            "app.kubernetes.io/name=cloudflare-tunnel",
            "-o",
            "wide",
        ),
    ):
        run(*args)


def reconcile(env: str) -> None:
    guard(env)
    run("kubectl", "apply", "-f", str(TRAEFIK))
    run(
        "kubectl",
        "-n",
        "kube-system",
        "patch",
        "deployment",
        "coredns",
        "--type=strategic",
        "--patch-file",
        str(COREDNS),
    )
    run(
        "kubectl",
        "-n",
        "kube-system",
        "rollout",
        "status",
        "deployment/coredns",
        f"--timeout={TIMEOUT}",
    )
    for deployment in ("coredns", "traefik"):
        run(
            "kubectl",
            "-n",
            "kube-system",
            "wait",
            f"deployment/{deployment}",
            "--for=jsonpath={.status.readyReplicas}=2",
            f"--timeout={TIMEOUT}",
        )
    run(
        "kubectl",
        "-n",
        "kube-system",
        "rollout",
        "status",
        "deployment/traefik",
        f"--timeout={TIMEOUT}",
    )


def apply(env: str) -> None:
    reconcile(env)
    verify(env)


def rollback(env: str) -> None:
    guard(env)
    run("kubectl", "delete", "-f", str(TRAEFIK), "--ignore-not-found")
    run(
        "kubectl",
        "-n",
        "kube-system",
        "patch",
        "deployment",
        "coredns",
        "--type=strategic",
        "--patch-file",
        str(COREDNS_ROLLBACK),
    )
    run(
        "kubectl",
        "-n",
        "kube-system",
        "rollout",
        "status",
        "deployment/coredns",
        f"--timeout={TIMEOUT}",
    )
    print("Rollback complete: packaged Traefik defaults and one CoreDNS replica restored.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("render", "status", "apply", "reconcile", "verify", "rollback")
    )
    parser.add_argument("environment", nargs="?", default="")
    args = parser.parse_args()
    if args.command == "render":
        print("--- # Traefik HelmChartConfig\n" + TRAEFIK.read_text(), end="")
        print("--- # CoreDNS strategic merge patch\n" + COREDNS.read_text(), end="")
    elif args.command == "status":
        status()
    elif args.command == "verify":
        verify(args.environment.removeprefix("env="))
    elif args.command == "apply":
        apply(args.environment.removeprefix("env="))
    elif args.command == "reconcile":
        reconcile(args.environment.removeprefix("env="))
    else:
        rollback(args.environment.removeprefix("env="))


if __name__ == "__main__":
    main()
