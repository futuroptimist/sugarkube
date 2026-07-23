#!/usr/bin/env python3
"""Detect and assert Sugarkube cluster identity from Kubernetes node labels."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from typing import Any

VALID_ENVS = {"dev", "staging", "prod", "int"}


def normalize_env(value: str) -> str:
    return "staging" if value == "int" else value


def run_kubectl(kubeconfig: str | None) -> tuple[int, str, str, list[str]]:
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    cmd.extend(["get", "nodes", "-o", "json"])
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr, cmd


def kube_context(kubeconfig: str | None) -> str:
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    cmd.extend(["config", "current-context"])
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def kube_server(kubeconfig: str | None) -> str:
    cmd = ["kubectl"]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    cmd.extend(["config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"])
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def load_nodes(kubeconfig: str | None) -> tuple[int, list[dict[str, Any]] | None, str]:
    code, out, err, cmd = run_kubectl(kubeconfig)
    if code != 0:
        return code, None, f"kubectl failed ({' '.join(cmd)}): {err.strip() or out.strip()}"
    try:
        doc = json.loads(out)
    except json.JSONDecodeError as exc:
        return 1, None, f"kubectl returned malformed node JSON: {exc}"
    items = doc.get("items")
    if not isinstance(items, list):
        return 1, None, "kubectl node JSON did not contain an items list"
    return 0, items, ""


def inspect(kubeconfig: str | None) -> tuple[int, dict[str, Any] | None, str]:
    code, nodes, err = load_nodes(kubeconfig)
    context = kube_context(kubeconfig)
    server = kube_server(kubeconfig)
    if code != 0 or nodes is None:
        return 1, None, f"ERROR: unable to detect Sugarkube cluster identity.\nContext: {context}\nServer: {server}\n{err}"
    if not nodes:
        return 1, None, f"ERROR: unable to detect Sugarkube cluster identity: Kubernetes API returned zero nodes.\nContext: {context}\nServer: {server}"

    names: list[str] = []
    envs_raw: list[str] = []
    clusters: list[str] = []
    missing: list[str] = []
    malformed: list[str] = []
    for node in nodes:
        meta = node.get("metadata", {}) if isinstance(node, dict) else {}
        name = str(meta.get("name") or "<unnamed>")
        labels = meta.get("labels", {}) if isinstance(meta, dict) else {}
        env = str(labels.get("sugarkube.env") or "").strip()
        cluster = str(labels.get("sugarkube.cluster") or "").strip()
        names.append(name)
        if cluster:
            clusters.append(cluster)
        if not env:
            missing.append(name)
            continue
        envs_raw.append(env)
        if env not in VALID_ENVS:
            malformed.append(f"{name}={env}")

    if missing:
        return 1, None, f"ERROR: node(s) missing nonempty sugarkube.env label: {', '.join(missing)}.\nConnected nodes: {', '.join(names)}\nCluster labels: {', '.join(sorted(set(clusters))) or '<none>'}\nContext: {context}\nServer: {server}"
    if malformed:
        return 1, None, f"ERROR: malformed sugarkube.env label(s): {', '.join(malformed)}. Expected dev|staging|prod (legacy int normalizes to staging).\nConnected nodes: {', '.join(names)}\nContext: {context}\nServer: {server}"
    envs = [normalize_env(v) for v in envs_raw]
    unique_envs = sorted(set(envs))
    if len(unique_envs) != 1:
        counts = ", ".join(f"{env}={count}" for env, count in sorted(Counter(envs).items()))
        return 1, None, f"ERROR: connected Kubernetes cluster has mixed sugarkube.env labels after normalization: {counts}.\nConnected nodes: {', '.join(names)}\nCluster labels: {', '.join(sorted(set(clusters))) or '<none>'}\nContext: {context}\nServer: {server}"
    return 0, {"env": unique_envs[0], "raw_envs": sorted(set(envs_raw)), "clusters": sorted(set(clusters)), "nodes": names, "context": context, "server": server}, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", default=None)
    parser.add_argument("--request-env", default=None)
    parser.add_argument("--assert-env", action="store_true")
    args = parser.parse_args()
    requested = normalize_env((args.request_env or "").strip()) if args.request_env else ""
    if requested and requested not in {"dev", "staging", "prod"}:
        return fail("ERROR: requested env must be dev|staging|prod (legacy int is accepted as staging).")
    code, info, err = inspect(args.kubeconfig)
    if code != 0 or info is None:
        return fail(err)
    if args.assert_env and requested != info["env"]:
        return fail(
            f"ERROR: requested env={requested}, but the connected Kubernetes cluster identifies as env={info['env']}.\n"
            "Refusing to run a mutating command.\n"
            f"Detected raw env label(s): {', '.join(info['raw_envs'])}\n"
            f"Cluster label(s): {', '.join(info['clusters']) or '<none>'}\n"
            f"Context: {info['context']}\nServer: {info['server']}\n"
            f"Connected nodes: {', '.join(info['nodes'])}"
        )
    print(f"env={info['env']}")
    print(f"raw_envs={','.join(info['raw_envs'])}")
    print(f"clusters={','.join(info['clusters']) or '<none>'}")
    print(f"context={info['context']}")
    print(f"server={info['server']}")
    print(f"nodes={','.join(info['nodes'])}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
