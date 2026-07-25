#!/usr/bin/env python3
"""Privacy-safe validation of blackbox Prometheus API responses."""

import json
import os
import sys

EXPECTED = {
    ("dspace", "root"),
    ("dspace", "config"),
    ("dspace", "healthz"),
    ("dspace", "livez"),
    ("tokenplace", "root"),
    ("tokenplace", "healthz"),
    ("tokenplace", "livez"),
    ("tokenplace", "metadata"),
    ("danielsmith", "root"),
    ("danielsmith", "healthz"),
    ("danielsmith", "livez"),
    ("jobbot3000", "root"),
    ("jobbot3000", "healthz"),
    ("jobbot3000", "livez"),
    ("jobbot3000", "tracker"),
    ("jobbot3000", "manifest"),
}
FAMILIES = {
    "probe_success",
    "probe_duration_seconds",
    "probe_http_status_code",
    "probe_dns_lookup_time_seconds",
    "probe_ssl_earliest_cert_expiry_seconds",
}


def fail(message, code=9):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def response(value, description):
    if not isinstance(value, dict):
        fail(f"{description} response must be a JSON object.")
    if value.get("status") != "success":
        fail(f"{description} API response was unsuccessful.")
    data = value.get("data")
    if not isinstance(data, dict):
        fail(f"{description} response has an invalid data structure.")
    return data


try:
    document = json.load(sys.stdin)
except (UnicodeDecodeError, json.JSONDecodeError):
    fail("Prometheus response is malformed JSON.")
if not isinstance(document, dict) or set(document) != {"targets", "metrics"}:
    fail("Prometheus response bundle has an invalid structure.")

target_data = response(document["targets"], "Prometheus targets")
active = target_data.get("activeTargets")
if not isinstance(active, list):
    fail("Prometheus targets response has an invalid activeTargets field.")
discovered = {}
for item in active:
    if not isinstance(item, dict) or not isinstance(item.get("labels"), dict):
        fail("Prometheus targets response contains an invalid target.")
    labels = item["labels"]
    if labels.get("environment") != "staging" or labels.get("app") not in {x[0] for x in EXPECTED}:
        continue
    key = (labels.get("app"), labels.get("route"))
    health = item.get("health")
    if key not in EXPECTED or not isinstance(health, str):
        fail("Prometheus target contains unexpected or invalid bounded labels.")
    discovered[key] = health

metrics = document["metrics"]
if not isinstance(metrics, dict) or set(metrics) != FAMILIES:
    fail("required metric family response set is invalid.")
metric_sets = {}
zero = set()
for family, raw in metrics.items():
    data = response(raw, family)
    if data.get("resultType") != "vector" or not isinstance(data.get("result"), list):
        fail(f"{family} response is not a vector.")
    found = set()
    for sample in data["result"]:
        if not isinstance(sample, dict) or not isinstance(sample.get("metric"), dict):
            fail(f"{family} response contains an invalid sample.")
        labels = sample["metric"]
        if labels.get("environment") != "staging":
            continue
        key = (labels.get("app"), labels.get("route"))
        if key not in EXPECTED:
            fail(f"{family} contains unexpected bounded labels.")
        value = sample.get("value")
        if not isinstance(value, list) or len(value) != 2 or not isinstance(value[1], str):
            fail(f"{family} response contains an invalid sample value.")
        try:
            numeric = float(value[1])
        except ValueError:
            fail(f"{family} response contains a non-numeric sample value.")
        found.add(key)
        if family == "probe_success" and numeric != 1:
            zero.add(key)
    metric_sets[family] = found

healthy = set(discovered) == EXPECTED and all(v == "up" for v in discovered.values())
complete = all(values == EXPECTED for values in metric_sets.values())
if healthy and complete and not zero:
    raise SystemExit(0)
if os.environ.get("FINAL_ATTEMPT") == "1":
    print("ERROR: staging blackbox verification did not converge before timeout.", file=sys.stderr)
    for app, route in sorted(EXPECTED):
        health = discovered.get((app, route), "missing")
        series = (
            "present" if all((app, route) in value for value in metric_sets.values()) else "missing"
        )
        success = "down" if (app, route) in zero else "unknown" if series == "missing" else "up"
        print(
            json.dumps(
                {
                    "app": app,
                    "environment": "staging",
                    "route": route,
                    "health": health,
                    "series": series,
                    "probe_success": success,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
raise SystemExit(10)
