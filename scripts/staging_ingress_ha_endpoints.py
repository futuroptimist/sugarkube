#!/usr/bin/env python3
"""Safely summarize all EndpointSlices selected for one staging Service."""

import argparse
import ipaddress
import json
import sys


def fail(message):
    raise ValueError(message)


def optional_bool(value, field):
    if value is not None and not isinstance(value, bool):
        fail(f"{field} must be a boolean when present")
    return value


def endpoint_key(endpoint):
    addresses = endpoint.get("addresses")
    if (
        not isinstance(addresses, list)
        or not addresses
        or not all(isinstance(address, str) and address for address in addresses)
    ):
        fail("endpoint addresses must be a non-empty list of strings")
    addresses = tuple(sorted(set(addresses)))

    node = endpoint.get("nodeName")
    if node is not None and (not isinstance(node, str) or not node):
        fail("endpoint nodeName must be a non-empty string when present")

    target = endpoint.get("targetRef")
    if target is not None:
        if not isinstance(target, dict):
            fail("endpoint targetRef must be an object when present")
        target = tuple(
            target.get(key, "") for key in ("apiVersion", "kind", "namespace", "name", "uid")
        )
        if not all(isinstance(value, str) for value in target):
            fail("endpoint targetRef identity fields must be strings when present")
    else:
        target = ("", "", "", "", "")
    return node, addresses, target


def condition_state(endpoint):
    conditions = endpoint.get("conditions", {})
    if not isinstance(conditions, dict):
        fail("endpoint conditions must be an object when present")
    ready_value = optional_bool(conditions.get("ready"), "conditions.ready")
    serving_value = optional_bool(conditions.get("serving"), "conditions.serving")
    terminating_value = optional_bool(conditions.get("terminating"), "conditions.terminating")

    # EndpointSlice clients interpret absent ready as ready. Serving was added later and, when
    # absent, follows effective readiness; absent terminating means not terminating.
    ready = True if ready_value is None else ready_value
    serving = ready if serving_value is None else serving_value
    terminating = False if terminating_value is None else terminating_value
    return ready, serving, terminating


def describe(key):
    node, addresses, target = key
    families = []
    for address in addresses:
        try:
            families.append(f"IPv{ipaddress.ip_address(address).version}")
        except ValueError:
            families.append("non-IP")
    target_text = "/".join(part for part in (target[1], target[2], target[3]) if part) or "none"
    family_text = ",".join(sorted(set(families)))
    return f"node={node or '<none>'},addresses={len(addresses)}:{family_text},target={target_text}"


def endpoint_sort_key(key):
    """Order endpoints by their full identity without exposing addresses."""
    node, addresses, target = key
    return node or "", addresses, target


def summarize(document, service, minimum_nodes):
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        fail("input must be an EndpointSliceList object with an items array")
    items = document["items"]
    if not items:
        fail(f"no EndpointSlices found for Service {service}")

    grouped = {}
    for item in items:
        if not isinstance(item, dict):
            fail("EndpointSlice item must be an object")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            fail("EndpointSlice metadata must be an object when present")
        labels = metadata.get("labels", {})
        if not isinstance(labels, dict) or labels.get("kubernetes.io/service-name") != service:
            fail(f"EndpointSlice does not belong to Service {service}")
        endpoints = item.get("endpoints")
        if not isinstance(endpoints, list):
            fail("EndpointSlice endpoints must be an array")
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                fail("endpoint must be an object")
            grouped.setdefault(endpoint_key(endpoint), []).append(condition_state(endpoint))

    if not grouped:
        fail(f"EndpointSlices for Service {service} contain no endpoints")

    healthy = []
    unhealthy = []
    for key in sorted(grouped, key=endpoint_sort_key):
        states = grouped[key]
        # Conflicting duplicate observations fail closed until every copy is healthy.
        if all(ready and serving and not terminating for ready, serving, terminating in states):
            healthy.append(key)
        else:
            reasons = set()
            for ready, serving, terminating in states:
                if not ready:
                    reasons.add("not-ready")
                if not serving:
                    reasons.add("non-serving")
                if terminating:
                    reasons.add("terminating")
            unhealthy.append(f"{describe(key)} ({','.join(sorted(reasons))})")

    nodes = sorted({key[0] for key in healthy if key[0]})
    print(
        f"{service}: slices={len(items)} unique={len(grouped)} "
        f"healthy={len(healthy)} ready nodes={nodes}"
    )
    for detail in unhealthy:
        print(f"{service}: unhealthy {detail}")
    if not healthy:
        fail(f"Service {service} has no healthy EndpointSlice backends")
    if minimum_nodes and (len(healthy) < minimum_nodes or len(nodes) < minimum_nodes):
        display = "CoreDNS" if service == "kube-dns" else service
        fail(f"fewer than {minimum_nodes} healthy, hostname-spread {display} endpoints")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("service")
    parser.add_argument("--minimum-nodes", type=int, default=0)
    args = parser.parse_args()
    try:
        summarize(json.load(sys.stdin), args.service, args.minimum_nodes)
    except (json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: invalid EndpointSlice data: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
