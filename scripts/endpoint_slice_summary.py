#!/usr/bin/env python3
"""Summarize and validate all EndpointSlices selected for one Service."""

import argparse
import json
import sys


def fail(message):
    raise ValueError(message)


def optional_bool(conditions, name):
    value = conditions.get(name)
    if value is not None and not isinstance(value, bool):
        fail(f"condition {name!r} must be boolean or null")
    return value


def summarize(document, service):
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        fail("EndpointSlice response must contain an items array")
    if not document["items"]:
        fail(f"no EndpointSlices found for Service {service}")

    records = set()
    for slice_ in document["items"]:
        if not isinstance(slice_, dict) or not isinstance(slice_.get("endpoints"), list):
            fail("each EndpointSlice must contain an endpoints array")
        for endpoint in slice_["endpoints"]:
            if not isinstance(endpoint, dict):
                fail("each EndpointSlice endpoint must be an object")
            addresses = endpoint.get("addresses")
            if (not isinstance(addresses, list) or not addresses or
                    any(not isinstance(address, str) or not address for address in addresses)):
                fail("each EndpointSlice endpoint must have one or more string addresses")
            node = endpoint.get("nodeName")
            if node is not None and not isinstance(node, str):
                fail("endpoint nodeName must be a string or null")
            conditions = endpoint.get("conditions", {})
            if not isinstance(conditions, dict):
                fail("endpoint conditions must be an object")
            ready_value = optional_bool(conditions, "ready")
            serving_value = optional_bool(conditions, "serving")
            terminating_value = optional_bool(conditions, "terminating")
            # EndpointSlice clients must treat an absent ready as ready. Serving was
            # introduced later, so an absent value follows effective readiness.
            ready = ready_value is not False
            serving = ready if serving_value is None else serving_value
            terminating = terminating_value is True
            target = endpoint.get("targetRef")
            if target is not None and not isinstance(target, dict):
                fail("endpoint targetRef must be an object or null")
            target_text = "-" if target is None else "/".join(
                str(target.get(key, "-")) for key in ("kind", "namespace", "name", "uid")
            )
            records.add((node or "-", tuple(sorted(set(addresses))), ready, serving,
                         terminating, target_text))

    ordered = sorted(records, key=lambda record: (record[0], record[1], record[5], record[2:5]))
    healthy = [record for record in ordered if record[2] and record[3] and not record[4]]
    healthy_nodes = sorted({record[0] for record in healthy if record[0] != "-"})
    lines = [f"{service}: healthy endpoints={len(healthy)} nodes={healthy_nodes}"]
    for node, addresses, ready, serving, terminating, target in ordered:
        state = "healthy" if ready and serving and not terminating else "unhealthy"
        lines.append(
            f"  {state} node={node} addresses={','.join(addresses)} "
            f"ready={str(ready).lower()} serving={str(serving).lower()} "
            f"terminating={str(terminating).lower()} targetRef={target}"
        )
    return "\n".join(lines), len(healthy), len(healthy_nodes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--min-healthy", type=int, default=1)
    parser.add_argument("--min-nodes", type=int, default=0)
    args = parser.parse_args()
    try:
        document = json.load(sys.stdin)
        output, healthy, nodes = summarize(document, args.service)
        print(output)
        if healthy < args.min_healthy or nodes < args.min_nodes:
            fail(f"Service {args.service} has fewer than the required healthy endpoints/nodes")
    except (json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: invalid EndpointSlice data: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
