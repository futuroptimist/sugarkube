#!/usr/bin/env python3
"""Validate the redacted Kubernetes inventory emitted by staging_ingress_ha.sh."""

import json
import sys


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def ready_pod_nodes(items, name):
    nodes = []
    for pod in items:
        statuses = pod.get("status", {}).get("containerStatuses", [])
        ready = (
            pod.get("status", {}).get("phase") == "Running"
            and statuses
            and all(status.get("ready") is True for status in statuses)
        )
        if ready and pod.get("spec", {}).get("nodeName"):
            nodes.append(pod["spec"]["nodeName"])
    if len(nodes) < 2:
        fail(f"{name} has {len(nodes)} ready pods; at least 2 are required")
    if len(set(nodes)) < 2:
        fail(f"{name} ready pods are not spread across at least 2 nodes")
    print(f"{name}: {len(nodes)} ready pods on {len(set(nodes))} nodes")


def main():
    try:
        inventory = json.load(sys.stdin)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"cluster inventory is not valid JSON ({error})")
    for key in ("coredns", "traefik", "cloudflare"):
        value = inventory.get(key)
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            fail(f"cluster inventory is missing {key} pod data")
        ready_pod_nodes(value["items"], key)
    for key in ("dns_endpoints", "traefik_endpoints"):
        addresses = inventory.get(key, {}).get("subsets", [])
        ready = sum(len(subset.get("addresses", [])) for subset in addresses)
        if ready < 1:
            fail(f"{key.removesuffix('_endpoints')} Service has no ready backend")
        print(f"{key.removesuffix('_endpoints')} Service: {ready} ready backends")


if __name__ == "__main__":
    main()
