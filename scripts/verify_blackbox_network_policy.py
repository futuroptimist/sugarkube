#!/usr/bin/env python3
"""Fail closed unless stdin is the exact lifecycle-owned NetworkPolicy JSON."""

import json
import sys

NAME = "allow-kube-prometheus-stack-to-blackbox-exporter"
EXPECTED_SPEC = {
    "podSelector": {
        "matchLabels": {
            "app.kubernetes.io/name": "prometheus",
            "operator.prometheus.io/name": "kube-prometheus-stack-prometheus",
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
EXPECTED_YAML_LINES = sorted(line.strip() for line in """
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
name: allow-kube-prometheus-stack-to-blackbox-exporter
namespace: monitoring
spec:
egress:
- ports:
- port: 9115
protocol: TCP
to:
- podSelector:
matchLabels:
app.kubernetes.io/instance: prometheus-blackbox-exporter
app.kubernetes.io/name: prometheus-blackbox-exporter
podSelector:
matchLabels:
app.kubernetes.io/name: prometheus
operator.prometheus.io/name: kube-prometheus-stack-prometheus
policyTypes:
- Egress
""".splitlines() if line.strip())


def main() -> int:
    if sys.argv[1:] == ["--rendered-yaml"]:
        actual = sorted(
            line.strip() for line in sys.stdin if line.strip() and not line.lstrip().startswith("#")
        )
        if actual != EXPECTED_YAML_LINES:
            print(
                "ERROR: rendered lifecycle NetworkPolicy differs from its required narrow semantics.",
                file=sys.stderr,
            )
            return 7
        return 0
    try:
        policy = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("ERROR: lifecycle NetworkPolicy response is malformed JSON.", file=sys.stderr)
        return 7
    if (
        policy.get("apiVersion") != "networking.k8s.io/v1"
        or policy.get("kind") != "NetworkPolicy"
        or policy.get("metadata", {}).get("name") != NAME
        or policy.get("metadata", {}).get("namespace") != "monitoring"
        or policy.get("spec") != EXPECTED_SPEC
    ):
        print(
            "ERROR: lifecycle NetworkPolicy is absent or differs from its required narrow semantics.",
            file=sys.stderr,
        )
        return 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
