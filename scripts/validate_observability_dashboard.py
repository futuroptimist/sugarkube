#!/usr/bin/env python3
"""Fail-closed validation for the staging Grafana dashboard and Helm render."""

import argparse
import json
import re
from pathlib import Path

TITLE = "Sugarkube Staging Observability"
UID = "sugarkube-staging-observability"
DATASOURCE_UID = "prometheus"
DASHBOARD_PATH = "/var/lib/grafana/dashboards/sugarkube"
DASHBOARD_FILE = f"{UID}.json"
DASHBOARD_MOUNT = f"{DASHBOARD_PATH}/{DASHBOARD_FILE}"
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
OPERATIONAL_ROUTES = r"/(healthz|livez|metrics)"


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


def require_panel(panel_by_title: dict, title: str) -> dict:
    panel = panel_by_title.get(title)
    if not panel:
        raise SystemExit(f"ERROR: dashboard is missing required panel {title!r}.")
    return panel


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
    panel_by_title = {panel.get("title"): panel for panel in panels(dashboard)}
    distribution = require_panel(panel_by_title, "Status-class distribution")
    distribution_targets = distribution.get("targets", [])
    if (
        distribution.get("type") not in {"barchart", "piechart"}
        or len(distribution_targets) != 1
        or any(
            target.get("instant") is not True or target.get("range") is not False
            for target in distribution_targets
        )
        or not distribution_targets[0]
        .get("expr", "")
        .startswith("sum by (status_class) (increase(dspace_http_requests_total{")
        or "[$__range]" not in distribution_targets[0].get("expr", "")
    ):
        raise SystemExit(
            "ERROR: status-class distribution must be a categorical instant selected-window query."
        )
    user_rate = require_panel(panel_by_title, "User request rate by route and status class")
    if not user_rate.get("targets") or any(
        f'route!~"{OPERATIONAL_ROUTES}"' not in target.get("expr", "")
        for target in user_rate["targets"]
    ):
        raise SystemExit("ERROR: user request rate must exclude health and metrics routes.")
    operational_rate = require_panel(panel_by_title, "Operational request rate")
    if not operational_rate.get("targets") or any(
        f'route=~"{OPERATIONAL_ROUTES}"' not in target.get("expr", "")
        for target in operational_rate["targets"]
    ):
        raise SystemExit("ERROR: operational request rate must contain health and metrics routes.")
    availability = require_panel(panel_by_title, "Public endpoint availability")
    availability_targets = availability.get("targets", [])
    if (
        availability.get("type") != "stat"
        or len(availability_targets) != 2
        or {target.get("legendFormat") for target in availability_targets}
        != {"Healthy endpoints", "Failed endpoints"}
        or any(
            target.get("instant") is not True or target.get("range") is not False
            for target in availability_targets
        )
        or any(
            not target.get("expr", "").startswith(
                "count((min by (environment, app, route) (probe_success{"
            )
            for target in availability_targets
        )
        or any("or on() vector" in target.get("expr", "") for target in availability_targets)
    ):
        raise SystemExit(
            "ERROR: public endpoint availability must be an aggregate, fail-closed instant summary."
        )
    endpoint_matrix = require_panel(panel_by_title, "Endpoint matrix")
    if endpoint_matrix.get("type") != "table" or not endpoint_matrix.get("targets"):
        raise SystemExit("ERROR: detailed endpoint matrix must remain available for diagnosis.")
    serialized = json.dumps(dashboard)
    if re.search(r"https?://", serialized, re.IGNORECASE):
        raise SystemExit("ERROR: dashboard must not contain embedded raw URLs.")
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
    try:
        rendered = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SystemExit(f"ERROR: rendered Helm output is missing or malformed: {error}") from error
    key = f"{DASHBOARD_FILE}:"
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
    provider_documents = [
        doc
        for doc in rendered.split("\n---")
        if "dashboardproviders.yaml:" in doc and "name: sugarkube" in doc
    ]
    if len(provider_documents) != 1:
        raise SystemExit("ERROR: Helm render must contain exactly one Sugarkube provider.")

    def scalar(value: str) -> str:
        value = value.strip()
        if value.startswith('"'):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as error:
                raise SystemExit(
                    "ERROR: rendered Helm output contains malformed YAML scalars."
                ) from error
            return decoded if isinstance(decoded, str) else ""
        if len(value) >= 2 and value[0] == value[-1] == "'":
            return value[1:-1].replace("''", "'")
        return value

    provider_paths = [
        scalar(value)
        for value in re.findall(r"(?m)^[ \t]*path:[ \t]*(.+?)[ \t]*$", provider_documents[0])
    ]
    if provider_paths != [DASHBOARD_PATH]:
        raise SystemExit(
            f"ERROR: rendered dashboard provider path must be exactly {DASHBOARD_PATH}."
        )
    mount_entries = []
    for match in re.finditer(
        r"(?m)^(?P<indent>[ \t]*)-[ \t]+(?P<key>\w+):[ \t]*(?P<value>.+?)\s*$",
        rendered,
    ):
        indent = len(match.group("indent"))
        following = rendered[match.end() :].splitlines()
        fields = {match.group("key"): scalar(match.group("value"))}
        for line in following:
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            field = re.match(r"^[ \t]+(\w+):[ \t]*(.+?)\s*$", line)
            if field:
                fields[field.group(1)] = scalar(field.group(2))
        if "mountPath" in fields or "subPath" in fields:
            mount_entries.append((fields.get("mountPath"), fields.get("subPath")))
    dashboard_mounts = [
        entry
        for entry in mount_entries
        if entry[0] == DASHBOARD_MOUNT or entry[1] == DASHBOARD_FILE
    ]
    if dashboard_mounts != [(DASHBOARD_MOUNT, DASHBOARD_FILE)]:
        raise SystemExit(
            f"ERROR: rendered dashboard mount must be exactly {DASHBOARD_MOUNT} "
            f"with subPath {DASHBOARD_FILE}."
        )
    # Decode the ConfigMap block scalar and compare the complete JSON object, so
    # changes to queries, labels, thresholds, or panel options cannot hide behind
    # matching metric-name counts.
    lines = document.splitlines()
    key_matches = [i for i, line in enumerate(lines) if line.strip().startswith(key)]
    if len(key_matches) != 1:
        raise SystemExit("ERROR: rendered dashboard ConfigMap key is malformed or duplicated.")
    key_index = key_matches[0]
    key_indent = len(lines[key_index]) - len(lines[key_index].lstrip())
    suffix = lines[key_index].strip()[len(key) :].strip()
    marker_index = key_index
    if not suffix:
        marker_index += 1
        if marker_index >= len(lines):
            raise SystemExit("ERROR: rendered dashboard ConfigMap block scalar is missing.")
        marker_indent = len(lines[marker_index]) - len(lines[marker_index].lstrip())
        suffix = lines[marker_index].strip()
        if marker_indent <= key_indent:
            raise SystemExit("ERROR: rendered dashboard ConfigMap block scalar is misplaced.")
    if suffix not in {"|", "|-", "|+"}:
        raise SystemExit("ERROR: rendered dashboard ConfigMap block scalar is malformed.")
    payload_lines = []
    for line in lines[marker_index + 1 :]:
        indent = len(line) - len(line.lstrip())
        if line.strip() and indent <= key_indent:
            break
        payload_lines.append(line)
    content_indents = [len(line) - len(line.lstrip()) for line in payload_lines if line.strip()]
    if not content_indents or min(content_indents) <= key_indent:
        raise SystemExit("ERROR: rendered dashboard ConfigMap payload is missing or misplaced.")
    payload_indent = min(content_indents)
    payload = [line[payload_indent:] if line.strip() else "" for line in payload_lines]
    try:
        rendered_dashboard = json.loads("\n".join(payload))
    except json.JSONDecodeError as error:
        raise SystemExit("ERROR: rendered dashboard ConfigMap contains malformed JSON.") from error
    if rendered_dashboard != json.loads(dashboard_json):
        raise SystemExit("ERROR: rendered dashboard differs from the version-controlled source.")


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
