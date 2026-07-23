#!/usr/bin/env python3
"""Detect and assert Sugarkube cluster identity from Kubernetes node labels."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

VALID_ENVS = {"dev", "staging", "prod"}


def norm(env: str) -> str:
    return "staging" if env == "int" else env


def kube_meta(kubeconfig: str) -> tuple[str, str]:
    def run(args: list[str]) -> str:
        try:
            return subprocess.run(args, check=False, text=True, capture_output=True).stdout.strip()
        except OSError:
            return ""
    base = ["kubectl", "--kubeconfig", kubeconfig, "config"]
    ctx = run(base + ["current-context"])
    server = ""
    if ctx:
        server = run(base + ["view", "-o", f"jsonpath={{.contexts[?(@.name==\"{ctx}\")].context.cluster}}"])
        if server:
            cluster_name = server
            server = run(base + ["view", "-o", f"jsonpath={{.clusters[?(@.name==\"{cluster_name}\")].cluster.server}}"])
    return ctx, server


def load_nodes(kubeconfig: str) -> dict:
    try:
        proc = subprocess.run(
            ["kubectl", "--kubeconfig", kubeconfig, "get", "nodes", "-o", "json"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"kubectl failed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "kubectl get nodes failed").strip())
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kubectl returned malformed node JSON: {exc}") from exc


def detect(kubeconfig: str) -> tuple[str, list[str], list[str], list[str]]:
    data = load_nodes(kubeconfig)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("no nodes returned by Kubernetes API")
    nodes: list[str] = []
    envs: list[str] = []
    clusters: list[str] = []
    missing: list[str] = []
    malformed: list[str] = []
    for item in items:
        meta = item.get("metadata", {}) if isinstance(item, dict) else {}
        name = str(meta.get("name") or "<unknown>")
        nodes.append(name)
        labels = meta.get("labels", {}) if isinstance(meta.get("labels", {}), dict) else {}
        raw_env = str(labels.get("sugarkube.env") or "").strip()
        cluster = str(labels.get("sugarkube.cluster") or "").strip()
        if cluster:
            clusters.append(cluster)
        if not raw_env:
            missing.append(name)
            continue
        env = norm(raw_env)
        if env not in VALID_ENVS:
            malformed.append(f"{name}={raw_env}")
        envs.append(env)
    if missing:
        raise ValueError("nodes missing sugarkube.env: " + ", ".join(missing))
    if malformed:
        raise ValueError("malformed sugarkube.env labels: " + ", ".join(malformed))
    uniq = sorted(set(envs))
    if len(uniq) != 1:
        raise ValueError("mixed sugarkube.env labels: " + ", ".join(uniq or ["<none>"]))
    return uniq[0], sorted(set(envs)), sorted(set(clusters)), nodes


def diag(prefix: str, requested: str | None, detected_envs: list[str], clusters: list[str], nodes: list[str], kubeconfig: str, detail: str | None = None) -> str:
    ctx, server = kube_meta(kubeconfig)
    lines = [prefix]
    if requested:
        lines.append(f"Requested env: {requested}")
    lines.append("Detected env(s): " + (", ".join(detected_envs) if detected_envs else "<unknown>"))
    lines.append("Cluster label(s): " + (", ".join(clusters) if clusters else "<none>"))
    if ctx:
        lines.append(f"Context: {ctx}")
    if server:
        lines.append(f"Server: {server}")
    lines.append("Connected nodes: " + (", ".join(nodes) if nodes else "<none>"))
    if detail:
        lines.append(f"Detail: {detail}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--kubeconfig", required=True)
    p.add_argument("--env", dest="requested")
    p.add_argument("--assert-env", action="store_true")
    args = p.parse_args()
    requested = norm((args.requested or "").strip()) if args.requested else None
    if args.assert_env and requested not in VALID_ENVS:
        print("ERROR: requested env must be dev|staging|prod.", file=sys.stderr)
        return 2
    try:
        detected, envs, clusters, nodes = detect(args.kubeconfig)
    except Exception as exc:
        print(diag("ERROR: unable to determine connected Kubernetes cluster environment. Refusing to run a mutating command.", requested, [], [], [], args.kubeconfig, str(exc)), file=sys.stderr)
        return 1
    if args.assert_env and requested != detected:
        print(diag(f"ERROR: requested env={requested}, but the connected Kubernetes cluster identifies as env={detected}.\nRefusing to run a mutating command.", requested, envs, clusters, nodes, args.kubeconfig), file=sys.stderr)
        return 1
    print(f"env={detected}")
    print("clusters=" + (",".join(clusters) if clusters else ""))
    print("nodes=" + ",".join(nodes))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
