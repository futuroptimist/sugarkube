#!/usr/bin/env python3
"""Fail-closed checks for the staging Grafana dashboard and Helm rendering."""
import argparse
import json
from pathlib import Path

UID = "sugarkube-staging-observability"
TITLE = "Sugarkube Staging Observability"
METRICS = {
    "up", "dspace_instrumentation_up", "probe_success", "dspace_http_requests_total",
    "dspace_http_request_duration_seconds_bucket", "process_resident_memory_bytes",
    "dspace_build_info", "dspace_dchat_requests_total", "dspace_dependency_requests_total",
    "probe_duration_seconds", "probe_http_status_code", "probe_ssl_earliest_cert_expiry",
}


def fail(message):
    raise SystemExit(f"ERROR: dashboard validation failed: {message}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--rendered", type=Path)
    args = parser.parse_args()
    try:
        raw = args.dashboard.read_text(encoding="utf-8")
        dashboard = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"dashboard JSON is missing or malformed: {error}")
    if dashboard.get("uid") != UID or dashboard.get("title") != TITLE:
        fail("title or UID changed")
    panels = dashboard.get("panels")
    if not isinstance(panels, list) or not panels:
        fail("panels must be a non-empty list")
    ids = [panel.get("id") for panel in panels]
    if None in ids or len(ids) != len(set(ids)):
        fail("panel IDs must be present and unique")
    expressions = "\n".join(
        target.get("expr", "") for panel in panels for target in panel.get("targets", [])
    )
    missing = sorted(metric for metric in METRICS if metric not in expressions)
    if missing:
        fail("required metric families missing from PromQL: " + ", ".join(missing))
    for title in ("dChat request activity", "token.place dependency request activity"):
        panel = next((item for item in panels if item.get("title") == title), None)
        if not panel or not all("vector(0)" in target.get("expr", "") for target in panel.get("targets", [])):
            fail(f"{title} must use a zero fallback")
    serialized = json.dumps(dashboard)
    if "${DS_" in serialized or '"uid": "${' in serialized:
        fail("unresolved datasource placeholder")
    for panel in panels:
        for target in panel.get("targets", []):
            datasource = target.get("datasource", panel.get("datasource"))
            if datasource != {"type": "prometheus", "uid": "prometheus"}:
                fail(f"panel {panel.get('id')} has an invalid datasource reference")
    if args.rendered:
        rendered = args.rendered.read_text(encoding="utf-8")
        if rendered.count(f'"uid": "{UID}"') != 1:
            fail("pinned Helm render must contain exactly one dashboard copy")
        if "/var/lib/grafana/dashboards/default" not in rendered:
            fail("dashboard is not rendered into Grafana's default provisioning path")


if __name__ == "__main__":
    main()
