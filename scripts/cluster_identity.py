#!/usr/bin/env python3
"""Detect and assert Sugarkube cluster identity from Kubernetes node labels."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

VALID_ENVS = {"dev", "staging", "prod"}
LAST_DETAILS = {"envs": set(), "clusters": set(), "nodes": []}


def norm_env(value: str) -> str:
    value = value.strip().lower()
    return "staging" if value == "int" else value


def run_kubectl(kubeconfig: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["KUBECONFIG"] = kubeconfig
    return subprocess.run(["kubectl", *args], env=env, text=True, capture_output=True, check=False)


def safe_info(kubeconfig: str) -> tuple[str, str]:
    ctx = run_kubectl(kubeconfig, ["config", "current-context"])
    context = ctx.stdout.strip() if ctx.returncode == 0 else "unknown"
    server = "unknown"
    if context and context != "unknown":
        view = run_kubectl(kubeconfig, ["config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"])
        if view.returncode == 0 and view.stdout.strip():
            server = view.stdout.strip()
    return context, server


def fail(message: str, *, requested: str | None, detected: set[str], clusters: set[str], nodes: list[str], kubeconfig: str) -> int:
    context, server = safe_info(kubeconfig)
    print(f"ERROR: {message}", file=sys.stderr)
    if requested:
        print(f"Requested env: {requested}", file=sys.stderr)
    print(f"Detected env(s): {', '.join(sorted(detected)) if detected else '<none>'}", file=sys.stderr)
    print(f"Cluster label(s): {', '.join(sorted(clusters)) if clusters else '<none>'}", file=sys.stderr)
    print(f"Context: {context}", file=sys.stderr)
    print(f"Server: {server}", file=sys.stderr)
    print(f"Connected nodes: {', '.join(nodes) if nodes else '<none>'}", file=sys.stderr)
    return 1


def load_identity(kubeconfig: str, requested: str | None = None) -> tuple[int, str | None]:
    proc = run_kubectl(kubeconfig, ["get", "nodes", "-o", "json"])
    if proc.returncode != 0:
        return fail("failed to query Kubernetes nodes; refusing to trust cluster identity.", requested=requested, detected=set(), clusters=set(), nodes=[], kubeconfig=kubeconfig), None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return fail("kubectl returned malformed node JSON; refusing to trust cluster identity.", requested=requested, detected=set(), clusters=set(), nodes=[], kubeconfig=kubeconfig), None
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return fail("connected Kubernetes API returned zero nodes; refusing to run a mutating command.", requested=requested, detected=set(), clusters=set(), nodes=[], kubeconfig=kubeconfig), None

    nodes: list[str] = []
    envs: set[str] = set()
    clusters: set[str] = set()
    missing: list[str] = []
    malformed: list[str] = []
    for item in items:
        meta = item.get("metadata", {}) if isinstance(item, dict) else {}
        name = str(meta.get("name") or "<unnamed>")
        nodes.append(name)
        labels = meta.get("labels", {}) if isinstance(meta, dict) else {}
        raw_env = str(labels.get("sugarkube.env") or "").strip()
        raw_cluster = str(labels.get("sugarkube.cluster") or "").strip()
        if raw_cluster:
            clusters.add(raw_cluster)
        if not raw_env:
            missing.append(name)
            continue
        env = norm_env(raw_env)
        if env not in VALID_ENVS:
            malformed.append(f"{name}={raw_env}")
        envs.add(env)

    if missing:
        return fail(f"one or more nodes are missing sugarkube.env labels: {', '.join(missing)}.", requested=requested, detected=envs, clusters=clusters, nodes=nodes, kubeconfig=kubeconfig), None
    if malformed:
        return fail(f"one or more nodes have malformed sugarkube.env labels: {', '.join(malformed)}.", requested=requested, detected=envs, clusters=clusters, nodes=nodes, kubeconfig=kubeconfig), None
    LAST_DETAILS["envs"] = set(envs)
    LAST_DETAILS["clusters"] = set(clusters)
    LAST_DETAILS["nodes"] = list(nodes)
    if len(envs) != 1:
        return fail("mixed or ambiguous sugarkube.env labels detected; refusing to run a mutating command.", requested=requested, detected=envs, clusters=clusters, nodes=nodes, kubeconfig=kubeconfig), None
    detected = next(iter(envs))
    return 0, detected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["detect", "assert"])
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--env", default="")
    args = parser.parse_args()
    kubeconfig = str(Path(args.kubeconfig).expanduser())
    requested = norm_env(args.env) if args.env else None
    if requested and requested not in VALID_ENVS:
        print("ERROR: env must be one of dev|staging|prod (legacy int normalizes to staging).", file=sys.stderr)
        return 1
    code, detected = load_identity(kubeconfig, requested)
    if code != 0:
        return code
    assert detected is not None
    if args.command == "assert" and requested != detected:
        return fail(f"requested env={requested}, but the connected Kubernetes cluster identifies as env={detected}.\nRefusing to run a mutating command.", requested=requested, detected={detected}, clusters=LAST_DETAILS["clusters"], nodes=LAST_DETAILS["nodes"], kubeconfig=kubeconfig)
    print(detected)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
