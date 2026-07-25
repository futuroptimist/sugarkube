#!/usr/bin/env python3
"""Fail-closed validation for the blackbox lifecycle NetworkPolicy."""

import json
import sys

EXPECTED_SPEC = {
    "podSelector": {
        "matchLabels": {
            "app.kubernetes.io/instance": "kube-prometheus-stack-prometheus",
            "app.kubernetes.io/name": "prometheus",
        }
    },
    "policyTypes": ["Egress"],
    "egress": [
        {
            "to": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/instance": "prometheus-blackbox-exporter",
                            "app.kubernetes.io/name": "prometheus-blackbox-exporter",
                        }
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 9115}],
        }
    ],
}


def main() -> int:
    try:
        policy = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("ERROR: lifecycle NetworkPolicy response is not valid JSON.", file=sys.stderr)
        return 7
    if not isinstance(policy, dict) or policy.get("spec") != EXPECTED_SPEC:
        print("ERROR: lifecycle NetworkPolicy does not have the exact required egress policy.", file=sys.stderr)
        return 7
    metadata = policy.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("name") != (
        "allow-kube-prometheus-stack-to-blackbox-exporter"
    ) or metadata.get("namespace") != "monitoring":
        print("ERROR: lifecycle NetworkPolicy identity is invalid.", file=sys.stderr)
        return 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
