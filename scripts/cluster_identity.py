#!/usr/bin/env python3
"""Detect and assert Sugarkube cluster identity from Kubernetes node labels."""
from __future__ import annotations

import argparse, json, subprocess, sys
from typing import Any

VALID_ENVS = {"dev", "staging", "prod"}


def norm_env(value: str) -> str:
    return "staging" if value == "int" else value


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def kube(kubeconfig: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", "--kubeconfig", kubeconfig, *args])


def context_server(kubeconfig: str) -> tuple[str, str]:
    cp = kube(kubeconfig, "config", "view", "--minify", "-o", "json")
    if cp.returncode != 0:
        return ("unknown", "unknown")
    try:
        data = json.loads(cp.stdout or "{}")
        ctx = data.get("current-context") or "unknown"
        clusters = data.get("clusters") or []
        server = "unknown"
        if clusters:
            server = ((clusters[0] or {}).get("cluster") or {}).get("server") or "unknown"
        return (ctx, server)
    except Exception:
        return ("unknown", "unknown")


def fail(msg: str, *, kubeconfig: str, requested: str | None, nodes: list[dict[str, Any]] | None = None, detected: list[str] | None = None, clusters: list[str] | None = None, mutating: bool = False) -> int:
    ctx, server = context_server(kubeconfig)
    if requested:
        print(f"ERROR: requested env={requested}, but {msg}", file=sys.stderr)
    else:
        print(f"ERROR: {msg}", file=sys.stderr)
    if mutating:
        print("Refusing to run a mutating command.", file=sys.stderr)
    if detected is not None:
        print(f"Detected env(s): {', '.join(detected) if detected else '<none>'}", file=sys.stderr)
    if clusters is not None:
        print(f"Cluster label(s): {', '.join(clusters) if clusters else '<none>'}", file=sys.stderr)
    print(f"Kubeconfig: {kubeconfig}", file=sys.stderr)
    print(f"Context: {ctx}", file=sys.stderr)
    print(f"Server: {server}", file=sys.stderr)
    if nodes is not None:
        names = [str(n.get("metadata", {}).get("name") or "<unnamed>") for n in nodes]
        print(f"Connected nodes: {', '.join(names) if names else '<none>'}", file=sys.stderr)
    return 1


def detect(kubeconfig: str, requested: str | None, assert_match: bool, mutating: bool) -> int:
    cp = kube(kubeconfig, "get", "nodes", "-o", "json")
    if cp.returncode != 0:
        return fail(f"the Kubernetes API/node query failed: {(cp.stderr or cp.stdout).strip() or 'kubectl failed'}.", kubeconfig=kubeconfig, requested=requested, mutating=mutating)
    try:
        nodes = json.loads(cp.stdout).get("items", [])
    except Exception as exc:
        return fail(f"kubectl returned malformed node JSON: {exc}.", kubeconfig=kubeconfig, requested=requested, mutating=mutating)
    if not nodes:
        return fail("the connected Kubernetes cluster returned zero nodes.", kubeconfig=kubeconfig, requested=requested, nodes=[], mutating=mutating, detected=[], clusters=[])
    envs: list[str] = []
    clusters: list[str] = []
    missing: list[str] = []
    malformed: list[str] = []
    for n in nodes:
        md = n.get("metadata") or {}; labels = md.get("labels") or {}; name = md.get("name") or "<unnamed>"
        raw = str(labels.get("sugarkube.env") or "").strip()
        cl = str(labels.get("sugarkube.cluster") or "").strip()
        if cl and cl not in clusters: clusters.append(cl)
        if not raw:
            missing.append(name); continue
        normal = norm_env(raw)
        if normal not in VALID_ENVS:
            malformed.append(f"{name}={raw}"); continue
        if normal not in envs: envs.append(normal)
    if missing:
        return fail(f"node(s) are missing required sugarkube.env labels: {', '.join(missing)}.", kubeconfig=kubeconfig, requested=requested, nodes=nodes, detected=envs, clusters=clusters, mutating=mutating)
    if malformed:
        return fail(f"node(s) have malformed sugarkube.env labels: {', '.join(malformed)}.", kubeconfig=kubeconfig, requested=requested, nodes=nodes, detected=envs, clusters=clusters, mutating=mutating)
    if len(envs) != 1:
        return fail("the connected Kubernetes cluster has mixed environment labels.", kubeconfig=kubeconfig, requested=requested, nodes=nodes, detected=envs, clusters=clusters, mutating=mutating)
    detected = envs[0]
    if assert_match and requested and detected != requested:
        return fail(f"the connected Kubernetes cluster identifies as env={detected}.", kubeconfig=kubeconfig, requested=requested, nodes=nodes, detected=envs, clusters=clusters, mutating=mutating)
    print(detected)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--kubeconfig", required=True)
    p.add_argument("--requested-env")
    p.add_argument("--assert-match", action="store_true")
    p.add_argument("--mutating", action="store_true")
    a = p.parse_args()
    req = norm_env(a.requested_env) if a.requested_env else None
    return detect(a.kubeconfig, req, a.assert_match, a.mutating)

if __name__ == "__main__": sys.exit(main())
