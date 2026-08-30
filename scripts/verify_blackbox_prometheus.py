#!/usr/bin/env python3
"""Privacy-safe validation of blackbox Prometheus API responses."""

import json
import os
import sys

ROUTES = {
    "blackbox-dspace-{environment}-root": ("dspace", "root"),
    "blackbox-dspace-{environment}-config": ("dspace", "config"),
    "blackbox-dspace-{environment}-healthz": ("dspace", "healthz"),
    "blackbox-dspace-{environment}-livez": ("dspace", "livez"),
    "blackbox-tokenplace-{environment}-root": ("tokenplace", "root"),
    "blackbox-tokenplace-{environment}-healthz": ("tokenplace", "healthz"),
    "blackbox-tokenplace-{environment}-livez": ("tokenplace", "livez"),
    "blackbox-tokenplace-{environment}-metadata": ("tokenplace", "metadata"),
    "blackbox-danielsmith-{environment}-root": ("danielsmith", "root"),
    "blackbox-danielsmith-{environment}-healthz": ("danielsmith", "healthz"),
    "blackbox-danielsmith-{environment}-livez": ("danielsmith", "livez"),
    "blackbox-gitshelves-{environment}-root": ("gitshelves", "root"),
    "blackbox-gitshelves-{environment}-healthz": ("gitshelves", "healthz"),
    "blackbox-gitshelves-{environment}-livez": ("gitshelves", "livez"),
    "blackbox-gitshelves-{environment}-baseplate": ("gitshelves", "baseplate"),
    "blackbox-gitshelves-{environment}-module": ("gitshelves", "module"),
    "blackbox-jobbot3000-{environment}-root": ("jobbot3000", "root"),
    "blackbox-jobbot3000-{environment}-healthz": ("jobbot3000", "healthz"),
    "blackbox-jobbot3000-{environment}-livez": ("jobbot3000", "livez"),
    "blackbox-jobbot3000-{environment}-tracker": ("jobbot3000", "tracker"),
    "blackbox-jobbot3000-{environment}-manifest": ("jobbot3000", "manifest"),
}


def parse_args():
    args = sys.argv[1:]
    if len(args) < 2 or args[:1] != ["--env"] or args[1] not in {"staging", "prod"}:
        fail("explicit --env staging or --env prod is required.")
    if args[2:] not in ([], ["--probes"]):
        fail("invalid verifier arguments.")
    return args[1], args[2:] == ["--probes"]


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


ENVIRONMENT, PROBES_ONLY = parse_args()
EXPECTED = {name.format(environment=ENVIRONMENT): labels for name, labels in ROUTES.items()}
EXPECTED_JOBS = {f"probe/monitoring/{name}": labels for name, labels in EXPECTED.items()}


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
        labels = metadata.get("labels") if isinstance(metadata, dict) else None
        if not isinstance(labels, dict) or not isinstance(metadata.get("name"), str):
            fail("Probe response contains an invalid object.", 7)
        name = metadata["name"]
        if name in found:
            fail("Probe response contains a duplicate name.", 7)
        if labels.get("environment") != ENVIRONMENT:
            fail("Probe response contains an invalid environment label.", 7)
        found[name] = (labels.get("app"), labels.get("route"))
    if found != EXPECTED:
        fail(f"{ENVIRONMENT} Probe names or app/route mappings are incorrect.", 7)


try:
    document = json.load(sys.stdin)
except (UnicodeDecodeError, json.JSONDecodeError):
    fail("response is malformed JSON.")
if PROBES_ONLY:
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
    key = (labels.get("app"), labels.get("route"))
    health = item.get("health")
    if (
        labels.get("environment") != ENVIRONMENT
        or key != EXPECTED_JOBS[job]
        or not isinstance(health, str)
    ):
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
        key = (labels.get("app"), labels.get("route"))
        if labels.get("environment") != ENVIRONMENT or key != EXPECTED_JOBS[job]:
            fail(f"{family} contains invalid lifecycle-owned labels.")
        value = sample.get("value")
        if not isinstance(value, list) or len(value) != 2 or not isinstance(value[1], str):
            fail(f"{family} response contains an invalid sample value.")
        try:
            numeric = float(value[1])
        except ValueError:
            fail(f"{family} response contains a non-numeric sample value.")
        if key in found:
            fail(f"{family} contains a duplicate lifecycle-owned series.")
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
    for app, route in sorted(EXPECTED.values()):
        health = discovered.get((app, route), "missing")
        series = (
            "present" if all((app, route) in value for value in metric_sets.values()) else "missing"
        )
        success = "down" if (app, route) in zero else "unknown" if series == "missing" else "up"
        print(
            json.dumps(
                {
                    "app": app,
                    "environment": ENVIRONMENT,
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
