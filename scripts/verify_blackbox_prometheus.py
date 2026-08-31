#!/usr/bin/env python3
"""Privacy-safe validation of blackbox Prometheus API responses."""

import json
import os
import sys

ROUTES = {
    "dspace": ("root", "config", "healthz", "livez"),
    "tokenplace": ("root", "healthz", "livez", "metadata"),
    "danielsmith": ("root", "healthz", "livez"),
    "jobbot3000": ("root", "healthz", "livez", "tracker", "manifest"),
    "gitshelves": ("root", "healthz", "livez", "baseplate", "module"),
}


def expected(environment):
    return {
        f"blackbox-{app}-{environment}-{route}": (app, route, environment)
        for app, routes in ROUTES.items()
        for route in routes
    }


FAMILIES = {
    "probe_success",
    "probe_duration_seconds",
    "probe_http_status_code",
    "probe_dns_lookup_time_seconds",
    "probe_ssl_earliest_cert_expiry",
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


def validate_probes(document):
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        fail("Probe response has an invalid structure.", 7)
    found = {}
    for item in items:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        if not isinstance(metadata, dict):
            fail("Probe response contains an invalid object.", 7)
        labels = metadata.get("labels")
        if not isinstance(labels, dict) or not isinstance(metadata.get("name"), str):
            fail("Probe response contains an invalid object.", 7)
        name = metadata["name"]
        if name in found:
            fail("Probe response contains a duplicate lifecycle-owned name.", 7)
        spec = item.get("spec")
        targets = spec.get("targets") if isinstance(spec, dict) else None
        static_config = targets.get("staticConfig") if isinstance(targets, dict) else None
        target_labels = static_config.get("labels") if isinstance(static_config, dict) else None
        expected_labels = (labels.get("app"), labels.get("route"), labels.get("environment"))
        if (
            not isinstance(target_labels, dict)
            or expected_labels
            != (
                target_labels.get("app"),
                target_labels.get("route"),
                target_labels.get("environment"),
            )
            or labels.get("release") != "kube-prometheus-stack"
        ):
            fail("Probe metadata and target labels do not match the lifecycle contract.", 7)
        found[name] = expected_labels
    if found != EXPECTED:
        fail(f"{ENVIRONMENT} Probe names or app/route/environment mappings are incorrect.", 7)


args = sys.argv[1:]
if (
    len(args) not in (2, 3)
    or args[0] != "--env"
    or args[1] not in {"staging", "prod"}
    or (len(args) == 3 and args[2] != "--probes")
):
    fail("explicit --env staging or --env prod is required.")
ENVIRONMENT = args[1]
EXPECTED = expected(ENVIRONMENT)
EXPECTED_JOBS = {f"probe/monitoring/{name}": labels for name, labels in EXPECTED.items()}

try:
    document = json.load(sys.stdin)
except (UnicodeDecodeError, json.JSONDecodeError):
    fail("response is malformed JSON.")
if args[-1:] == ["--probes"]:
    validate_probes(document)
    raise SystemExit(0)

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
    job = labels.get("job")
    if job not in EXPECTED_JOBS:
        continue
    key = (labels.get("app"), labels.get("route"), labels.get("environment"))
    health = item.get("health")
    if key != EXPECTED_JOBS[job] or not isinstance(health, str):
        fail("Prometheus target contains invalid lifecycle-owned labels.")
    if key in discovered:
        fail("Prometheus targets contain a duplicate lifecycle-owned target.")
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
        job = labels.get("job")
        if job not in EXPECTED_JOBS:
            continue
        key = (labels.get("app"), labels.get("route"), labels.get("environment"))
        if key != EXPECTED_JOBS[job]:
            fail(f"{family} contains invalid lifecycle-owned labels.")
        if key in found:
            fail(f"{family} contains a duplicate lifecycle-owned series.")
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

healthy = set(discovered) == set(EXPECTED.values()) and all(v == "up" for v in discovered.values())
complete = all(values == set(EXPECTED.values()) for values in metric_sets.values())
if healthy and complete and not zero:
    raise SystemExit(0)
if os.environ.get("FINAL_ATTEMPT") == "1":
    print(
        f"ERROR: {ENVIRONMENT} blackbox verification did not converge before timeout.",
        file=sys.stderr,
    )
    for app, route, environment in sorted(EXPECTED.values()):
        health = discovered.get((app, route, environment), "missing")
        series = (
            "present"
            if all((app, route, environment) in value for value in metric_sets.values())
            else "missing"
        )
        success = (
            "down"
            if (app, route, environment) in zero
            else "unknown" if series == "missing" else "up"
        )
        print(
            json.dumps(
                {
                    "app": app,
                    "environment": environment,
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
