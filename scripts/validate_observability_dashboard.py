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
    "dspace_release_approved_info",
    "dspace_deployment_image_pin_matches",
    "dspace_chat_synthetic_success",
    "dspace_chat_synthetic_last_run_timestamp_seconds",
}
EVENT_METRICS = {"dspace_dchat_requests_total", "dspace_dependency_requests_total"}
OPERATIONAL_ROUTES = '"/(healthz|livez|metrics)"'
BLACKBOX_JOB_MATCHER = (
    'job=~"probe/monitoring/blackbox-(dspace|tokenplace|danielsmith|jobbot3000)-staging-.*"'
)


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


def panel_named(dashboard: dict, title: str) -> dict:
    matching = [panel for panel in panels(dashboard) if panel.get("title") == title]
    if len(matching) != 1:
        raise SystemExit(f"ERROR: dashboard must contain exactly one {title!r} panel.")
    return matching[0]


def validate_dashboard_semantics(dashboard: dict) -> None:
    variables = {
        variable.get("name"): variable
        for variable in dashboard.get("templating", {}).get("list", [])
        if isinstance(variable, dict)
    }
    expected_labels = {"app": "Probe application", "route": "Probe route"}
    if any(
        variables.get(name, {}).get("label") != label for name, label in expected_labels.items()
    ):
        raise SystemExit("ERROR: blackbox variables must use probe-specific visible labels.")

    distribution = panel_named(dashboard, "Status-class distribution")
    if distribution.get("type") not in {"piechart", "bargauge"}:
        raise SystemExit("ERROR: status-class distribution must use a categorical visualization.")
    distribution_targets = distribution.get("targets", [])
    if not distribution_targets or any(
        target.get("instant") is not True or target.get("range") is not False
        for target in distribution_targets
    ):
        raise SystemExit(
            "ERROR: status-class distribution must be an instant selected-window query."
        )
    if any(
        "increase(" not in target.get("expr", "")
        or "$__range" not in target.get("expr", "")
        or "sum by (status_class)" not in target.get("expr", "")
        or 'environment=~"$environment"' not in target.get("expr", "")
        for target in distribution_targets
    ):
        raise SystemExit("ERROR: status-class distribution must summarize the selected window.")
    distribution_colors = {
        override.get("matcher", {})
        .get("options"): override.get("properties", [{}])[0]
        .get("value", {})
        .get("fixedColor")
        for override in distribution.get("fieldConfig", {}).get("overrides", [])
    }
    if distribution_colors != {"2xx": "green", "4xx": "orange", "5xx": "red"}:
        raise SystemExit("ERROR: status-class distribution must use explicit status-class colors.")

    user_rate = panel_named(dashboard, "User request rate by route and status class")
    user_expressions = [target.get("expr", "") for target in user_rate.get("targets", [])]
    if not user_expressions or any(
        f"route!~{OPERATIONAL_ROUTES}" not in expression for expression in user_expressions
    ):
        raise SystemExit("ERROR: user request rate must exclude operational routes.")
    operational_rate = panel_named(dashboard, "Operational request rate")
    if not any(
        f"route=~{OPERATIONAL_ROUTES}" in target.get("expr", "")
        for target in operational_rate.get("targets", [])
    ):
        raise SystemExit("ERROR: operational request rate must retain health and metrics routes.")

    summary = panel_named(dashboard, "Public availability summary")
    summary_targets = summary.get("targets", [])
    if (
        not isinstance(summary_targets, list)
        or len(summary_targets) != 3
        or any(
            not isinstance(target, dict)
            or not isinstance(target.get("expr"), str)
            or target.get("instant") is not True
            or target.get("range") is not False
            or "sum(" not in target.get("expr", "")
            or " by (environment, app, route) " not in target.get("expr", "")
            or BLACKBOX_JOB_MATCHER not in target.get("expr", "")
            or any(
                selector not in target.get("expr", "")
                for selector in (
                    'environment=~"$environment"',
                    'app=~"$app"',
                    'route=~"$route"',
                )
            )
            for target in summary_targets
        )
    ):
        raise SystemExit(
            "ERROR: public availability must be a three-value instant aggregate summary."
        )
    summary_by_legend = {
        target.get("legendFormat"): target.get("expr", "") for target in summary_targets
    }
    healthy_expression = re.sub(r"\s+", " ", summary_by_legend.get("Healthy endpoints", ""))
    failed_expression = re.sub(r"\s+", " ", summary_by_legend.get("Failed endpoints", ""))
    missing_expression = re.sub(r"\s+", " ", summary_by_legend.get("Missing probe data", ""))
    if "== bool 1" not in healthy_expression or "== bool 0" not in failed_expression:
        raise SystemExit("ERROR: availability counts must use boolean healthy and failed sums.")
    if (
        "max_over_time(up{" not in missing_expression
        or "[7d]" not in missing_expression
        or ">= bool 0" not in missing_expression
        or " - (sum(" not in missing_expression
        or "probe_success{" not in missing_expression
        or "or vector(0)" not in missing_expression
    ):
        raise SystemExit(
            "ERROR: missing probe data must compare retention-backed discovered "
            "probes with current samples."
        )
    if {target.get("legendFormat") for target in summary_targets} != {
        "Healthy endpoints",
        "Failed endpoints",
        "Missing probe data",
    } or summary.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA":
        raise SystemExit(
            "ERROR: public availability must distinguish healthy, failed, and no data."
        )
    missing_colors = [
        prop.get("value", {}).get("fixedColor")
        for override in summary.get("fieldConfig", {}).get("overrides", [])
        if isinstance(override, dict)
        and override.get("matcher", {}).get("options") == "Missing probe data"
        for prop in override.get("properties", [])
        if isinstance(prop, dict) and prop.get("id") == "color"
    ]
    if missing_colors != ["yellow"]:
        raise SystemExit("ERROR: missing probe data must be a compact yellow summary value.")

    matrix = panel_named(dashboard, "Endpoint matrix")
    if matrix.get("type") != "table" or not matrix.get("targets"):
        raise SystemExit("ERROR: dashboard must retain the detailed endpoint matrix.")


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
    validate_dashboard_semantics(dashboard)
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
    urls = set(re.findall(r'https?://[^)\" ]+', serialized, re.IGNORECASE))
    allowed_urls = {
        "https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-dspace-release-integrity.md",
        "https://github.com/futuroptimist/sugarkube/blob/main/deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json",
    }
    if urls != allowed_urls:
        raise SystemExit("ERROR: dashboard links must be the exact reviewed runbook and evidence URLs.")
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
