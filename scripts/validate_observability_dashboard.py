#!/usr/bin/env python3
"""Fail-closed validation for the staging Grafana dashboard and Helm render."""

import argparse
import json
from pathlib import Path

UID = "sugarkube-staging-observability"
TITLE = "Sugarkube Staging Observability"
METRICS = {
    "up",
    "dspace_instrumentation_up",
    "probe_success",
    "dspace_http_requests_total",
    "dspace_http_request_duration_seconds_bucket",
    "process_resident_memory_bytes",
    "dspace_build_info",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "probe_duration_seconds",
    "probe_http_status_code",
    "probe_ssl_earliest_cert_expiry",
}


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def validate(path: Path):
    try:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"dashboard JSON is missing or malformed: {exc}")
    if not isinstance(dashboard, dict):
        fail("dashboard JSON root must be an object")
    if dashboard.get("uid") != UID or dashboard.get("title") != TITLE:
        fail("dashboard UID or title changed")
    panels = dashboard.get("panels")
    if not isinstance(panels, list) or not panels:
        fail("dashboard panels must be a non-empty list")
    ids = [panel.get("id") for panel in panels]
    if None in ids or len(ids) != len(set(ids)):
        fail("panel IDs must be present and unique")
    encoded = json.dumps(dashboard)
    for metric in METRICS:
        if metric not in encoded:
            fail(f"required metric family is absent: {metric}")
    for metric in ("dspace_dchat_requests_total", "dspace_dependency_requests_total"):
        targets = [
            target.get("expr", "")
            for panel in panels
            for target in panel.get("targets", [])
            if metric in target.get("expr", "")
        ]
        if not targets or any("or on() vector(0)" not in target for target in targets):
            fail(f"{metric} must use the zero fallback")
    if "${DS_" in encoded or "${datasource" in encoded.lower():
        fail("dashboard contains an unresolved datasource placeholder")
    datasources = []
    for panel in panels:
        if panel.get("type") != "row":
            datasources.append(panel.get("datasource"))
        datasources.extend(target.get("datasource") for target in panel.get("targets", []))
    datasources.extend(
        item.get("datasource") for item in dashboard.get("templating", {}).get("list", [])
    )
    if not datasources or any(
        source != {"type": "prometheus", "uid": "prometheus"} for source in datasources
    ):
        fail("every datasource reference must use the chart-provisioned prometheus UID")
    return dashboard


def validate_render(path: Path):
    text = path.read_text(encoding="utf-8")
    marker = "sugarkube-staging-observability.json:"
    if text.count(marker) != 1:
        fail("pinned Helm render must contain exactly one dashboard provisioning entry")
    if text.count('"uid": "sugarkube-staging-observability"') != 1:
        fail("pinned Helm render must contain exactly one copy of the dashboard")
    mount = 'mountPath: "/var/lib/grafana/dashboards/default/sugarkube-staging-observability.json"'
    if text.count(mount) != 1:
        fail("dashboard must be mounted in the intended Grafana provisioning path")
    document = text[: text.index(marker)]
    if "kind: ConfigMap" not in document.rsplit("---", 1)[-1]:
        fail("dashboard must be provisioned through a Grafana ConfigMap")


parser = argparse.ArgumentParser()
parser.add_argument("dashboard", type=Path)
parser.add_argument("--rendered", type=Path)
args = parser.parse_args()
validate(args.dashboard)
if args.rendered:
    validate_render(args.rendered)
