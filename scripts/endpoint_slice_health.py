#!/usr/bin/env python3
"""Summarize every EndpointSlice for one Service without exposing workload data."""

import argparse
import json
import sys


def fail(message):
    raise ValueError(message)


def load_endpoints(stream):
    try:
        document = json.load(stream)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail(f"malformed EndpointSlice JSON: {exc.msg}")
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        fail("malformed EndpointSlice list: expected an items array")
    if not document["items"]:
        fail("no EndpointSlices found for Service")

    endpoints = {}
    for slice_index, endpoint_slice in enumerate(document["items"]):
        if not isinstance(endpoint_slice, dict) or not isinstance(
            endpoint_slice.get("endpoints"), list
        ):
            fail(f"malformed EndpointSlice at index {slice_index}: expected an endpoints array")
        for endpoint_index, endpoint in enumerate(endpoint_slice["endpoints"]):
            where = f"slice {slice_index}, endpoint {endpoint_index}"
            if not isinstance(endpoint, dict):
                fail(f"malformed endpoint at {where}: expected an object")
            addresses = endpoint.get("addresses")
            if (
                not isinstance(addresses, list)
                or not addresses
                or any(not isinstance(address, str) or not address for address in addresses)
            ):
                fail(f"malformed endpoint at {where}: addresses must be non-empty strings")
            node = endpoint.get("nodeName")
            if node is not None and not isinstance(node, str):
                fail(f"malformed endpoint at {where}: nodeName must be a string or null")
            conditions = endpoint.get("conditions", {})
            if not isinstance(conditions, dict):
                fail(f"malformed endpoint at {where}: conditions must be an object")
            for condition in ("ready", "serving", "terminating"):
                if condition in conditions and not isinstance(conditions[condition], bool):
                    fail(f"malformed endpoint at {where}: conditions.{condition} must be boolean")
            target = endpoint.get("targetRef")
            if target is not None and not isinstance(target, dict):
                fail(f"malformed endpoint at {where}: targetRef must be an object or null")

            # Address order and repeated Slice records are not meaningful. If controllers briefly
            # publish conflicting duplicates, merge conditions conservatively so an unhealthy copy
            # can never be hidden by a healthy one.
            key = (node or "", tuple(sorted(set(addresses))), json.dumps(target, sort_keys=True))
            healthy = (
                conditions.get("ready", True) is not False
                and conditions.get("serving", conditions.get("ready", True)) is not False
                and conditions.get("terminating", False) is not True
            )
            record = endpoints.setdefault(
                key,
                {
                    "addresses": key[1],
                    "node": node,
                    "target": target,
                    "healthy": True,
                    "states": set(),
                },
            )
            record["healthy"] = record["healthy"] and healthy
            state = ",".join(
                (
                    f"{name}={str(conditions[name]).lower()}"
                    if name in conditions
                    else f"{name}=absent"
                )
                for name in ("ready", "serving", "terminating")
            )
            record["states"].add(state)
    return [endpoints[key] for key in sorted(endpoints)]


def target_name(target):
    if not target:
        return "none"
    return "/".join(str(target.get(key, "?")) for key in ("kind", "namespace", "name"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("service")
    parser.add_argument("--minimum-healthy", type=int, default=0)
    parser.add_argument("--minimum-nodes", type=int, default=0)
    args = parser.parse_args()
    try:
        endpoints = load_endpoints(sys.stdin)
    except ValueError as exc:
        print(f"ERROR: {args.service}: {exc}", file=sys.stderr)
        return 2

    healthy = [endpoint for endpoint in endpoints if endpoint["healthy"]]
    nodes = sorted({endpoint["node"] for endpoint in healthy if endpoint["node"]})
    print(f"{args.service}: healthy endpoints={len(healthy)} nodes={nodes}")
    for endpoint in endpoints:
        state = "healthy" if endpoint["healthy"] else "UNHEALTHY"
        node = endpoint["node"] or "<none>"
        states = ";".join(sorted(endpoint["states"]))
        print(
            f"  {state}: addresses={','.join(endpoint['addresses'])} node={node} "
            f"target={target_name(endpoint['target'])} conditions={states}"
        )
    if len(healthy) < args.minimum_healthy or len(nodes) < args.minimum_nodes:
        print(
            f"ERROR: {args.service}: need at least {args.minimum_healthy} healthy endpoints "
            f"on {args.minimum_nodes} distinct named nodes",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
