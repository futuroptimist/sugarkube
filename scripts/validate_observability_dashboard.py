#!/usr/bin/env python3
"""Fail-closed validation for the staging Grafana dashboard and Helm render."""

import argparse
import json
import re
from pathlib import Path

TITLE = "Sugarkube Staging Observability"
UID = "sugarkube-staging-observability"
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


def load_dashboard(path: Path) -> dict:
    try:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: dashboard JSON is missing or malformed: {error}") from error
    if not isinstance(dashboard, dict):
        raise SystemExit("ERROR: dashboard JSON root must be an object.")
    return dashboard


def panels(dashboard: dict):
    for panel in dashboard.get("panels", []):
        if isinstance(panel, dict):
            yield panel
            yield from panels(panel)


def validate_dashboard(path: Path) -> str:
    dashboard = load_dashboard(path)
    if dashboard.get("uid") != UID or dashboard.get("title") != TITLE:
        raise SystemExit(f"ERROR: dashboard title must be {TITLE!r} and UID must be {UID!r}.")
    ids = [panel.get("id") for panel in panels(dashboard)]
    if (
        not ids
        or any(not isinstance(panel_id, int) for panel_id in ids)
        or len(ids) != len(set(ids))
    ):
        raise SystemExit("ERROR: dashboard panel IDs must be present, integer, and unique.")
    expressions = [
        target["expr"]
        for panel in panels(dashboard)
        for target in panel.get("targets", [])
        if isinstance(target, dict) and isinstance(target.get("expr"), str)
    ]
    expression_text = "\n".join(expressions)
    missing = sorted(metric for metric in REQUIRED_METRICS if metric not in expression_text)
    if missing:
        raise SystemExit(
            f"ERROR: dashboard is missing required PromQL metrics: {', '.join(missing)}"
        )
    for metric in EVENT_METRICS:
        matching = [expr for expr in expressions if metric in expr]
        if not matching or any("or on() vector(0)" not in expr for expr in matching):
            raise SystemExit(f"ERROR: event-driven metric {metric} must use a safe zero fallback.")
    serialized = json.dumps(dashboard)
    if re.search(r"\$\{?DS_|__inputs", serialized, re.IGNORECASE) or re.search(
        r"(?:\{|,)\s*target\s*(?:=|=~|!~|!=)|{{\s*target\s*}}", expression_text
    ):
        raise SystemExit(
            "ERROR: dashboard contains a datasource placeholder or unsafe raw target label."
        )
    datasource_refs = re.findall(r'"uid":\s*"([^"]+)"', serialized)
    if DATASOURCE_UID not in datasource_refs or any(
        uid not in {DATASOURCE_UID, UID} for uid in datasource_refs
    ):
        raise SystemExit(
            "ERROR: dashboard datasource references must use the rendered Prometheus UID."
        )
    return path.read_text(encoding="utf-8")


def validate_render(path: Path, dashboard_json: str) -> None:
    rendered = path.read_text(encoding="utf-8")
    key = f"{UID}.json:"
    if rendered.count(key) != 1 or rendered.count(f'"uid": "{UID}"') != 1:
        raise SystemExit("ERROR: Helm render must contain exactly one custom dashboard copy.")
    document = next((doc for doc in rendered.split("\n---") if key in doc), "")
    required = (
        "kind: ConfigMap",
        "dashboard-provider: sugarkube",
        "name: kube-prometheus-stack-grafana-dashboards-sugarkube",
        f'"title": "{TITLE}"',
    )
    if any(item not in document for item in required):
        raise SystemExit(
            "ERROR: custom dashboard is not in the intended Grafana provisioning ConfigMap."
        )
    # Ensure validation is tied to the source passed to --set-file, not merely a
    # coincidental title/UID in another chart dashboard.
    source = json.loads(dashboard_json)
    for metric in REQUIRED_METRICS:
        if document.count(metric) != json.dumps(source).count(metric):
            raise SystemExit(
                "ERROR: rendered dashboard differs from the version-controlled source."
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--rendered", type=Path)
    args = parser.parse_args()
    dashboard_json = validate_dashboard(args.dashboard)
    if args.rendered:
        validate_render(args.rendered, dashboard_json)


if __name__ == "__main__":
    main()
