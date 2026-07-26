#!/usr/bin/env python3
"""Fail-closed validation for the staging Grafana dashboard and Helm render."""

import argparse
import json
import re
from pathlib import Path

UID = "sugarkube-staging-observability"
TITLE = "Sugarkube Staging Observability"
DATASOURCE_UID = "prometheus"
REQUIRED_METRICS = {
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
EVENT_METRICS = {"dspace_dchat_requests_total", "dspace_dependency_requests_total"}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def validate_dashboard(path: Path) -> dict:
    try:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"dashboard JSON is missing: {path}")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"dashboard JSON is malformed: {error}")
    if not isinstance(dashboard, dict):
        fail("dashboard JSON must be an object")
    if dashboard.get("uid") != UID or dashboard.get("title") != TITLE:
        fail(f"dashboard identity must be title {TITLE!r} and UID {UID!r}")

    panels = dashboard.get("panels")
    if not isinstance(panels, list) or not panels:
        fail("dashboard must contain panels")
    ids = [panel.get("id") for panel in panels if isinstance(panel, dict)]
    if len(ids) != len(panels) or any(not isinstance(value, int) for value in ids):
        fail("every dashboard panel and row must have an integer ID")
    if len(ids) != len(set(ids)):
        fail("dashboard panel IDs must be unique")

    expressions = []
    datasource_uids = []
    for panel in panels:
        datasource = panel.get("datasource")
        if isinstance(datasource, dict):
            datasource_uids.append(datasource.get("uid"))
        for target in panel.get("targets", []):
            if isinstance(target, dict):
                expressions.append(target.get("expr", ""))
                target_datasource = target.get("datasource")
                if isinstance(target_datasource, dict):
                    datasource_uids.append(target_datasource.get("uid"))
    promql = "\n".join(expressions)
    missing = sorted(metric for metric in REQUIRED_METRICS if metric not in promql)
    if missing:
        fail(f"dashboard PromQL is missing required metric families: {', '.join(missing)}")
    for metric in EVENT_METRICS:
        matching = [expr for expr in expressions if metric in expr]
        if not matching or any("or vector(0)" not in expr for expr in matching):
            fail(f"event-driven metric {metric} must use a safe zero fallback")
    if not datasource_uids or set(datasource_uids) != {DATASOURCE_UID}:
        fail(f"all panel datasource references must use rendered datasource UID {DATASOURCE_UID!r}")
    serialized = json.dumps(dashboard)
    if re.search(r"\$\{?DS_|__INPUT|DATASOURCE_PLACEHOLDER", serialized, re.IGNORECASE):
        fail("dashboard contains an unresolved datasource placeholder")
    return dashboard


def validate_render(path: Path) -> None:
    try:
        rendered = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"Helm render is missing: {path}")
    if rendered.count(f'"uid": "{UID}"') != 1:
        fail("pinned Helm render must contain exactly one copy of the custom dashboard")
    if rendered.count("sugarkube-staging-observability.json:") != 1:
        fail("custom dashboard must occur once in the intended Grafana dashboard ConfigMap")
    required = (
        "name: kube-prometheus-stack-grafana-dashboards-sugarkube",
        "dashboard-provider: sugarkube",
        'mountPath: "/var/lib/grafana/dashboards/sugarkube/sugarkube-staging-observability.json"',
        "uid: prometheus",
    )
    for value in required:
        if value not in rendered:
            fail(f"pinned Helm render is missing expected provisioning content: {value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--render", type=Path)
    args = parser.parse_args()
    validate_dashboard(args.dashboard)
    if args.render:
        validate_render(args.render)


if __name__ == "__main__":
    main()
