#!/usr/bin/env python3
"""Fail-closed validation for generated Sugarkube Grafana dashboards and Helm renders."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_observability_dashboards import PROFILES, render  # noqa: E402

DATASOURCE_UID = "prometheus"
DASHBOARD_PATH = "/var/lib/grafana/dashboards/sugarkube"
TITLE = ""
UID = ""
DASHBOARD_FILE = ""
DASHBOARD_MOUNT = ""
PROFILE_DIFFERENCES = {"uid", "title", "tags", "templating", "panels"}
FORBIDDEN_LABELS = {
    "instance",
    "ip",
    "address",
    "endpoint",
    "url",
    "device",
    "system_uuid",
    "provider_id",
    "pod_cidr",
    "uuid",
}
TOKENPLACE_DATA_TITLES = {
    "token.place scrape availability",
    "token.place instrumentation health",
    "token.place compute-node counts",
    "token.place oldest compute-node lease age",
    "token.place compute-node eviction rate",
    "token.place relay queue depth",
    "token.place oldest queued-request age",
    "token.place in-flight requests by pod",
    "token.place oldest in-flight age by pod",
    "token.place terminal outcome rate",
    "token.place HTTP request rate",
    "token.place HTTP 5xx ratio",
    "token.place HTTP latency percentiles",
    "token.place build identity",
}
EVENT_METRICS = {"dspace_dchat_requests_total", "dspace_dependency_requests_total"}
DSPACE_CHAT_PANEL_TITLES = {
    "DSPACE chat outcome rate",
    "DSPACE dependency outcome rate",
    "DSPACE primary-provider success ratio",
    "DSPACE fallback-use ratio",
    "DSPACE chat latency percentiles",
    "DSPACE dependency latency percentiles",
}
DSPACE_CHAT_METRICS = {
    "dspace_dchat_requests_total",
    "dspace_dchat_request_duration_seconds_bucket",
    "dspace_dependency_requests_total",
    "dspace_dependency_request_duration_seconds_bucket",
}
CAPABILITY = 'dspace_release_approved_info{environment=~"$environment"}'
CAPABILITY_PRESENCE_GATE = f"and on() (count({CAPABILITY}) > 0)"
DSPACE_HEALTH = 'dspace_instrumentation_up{environment=~"$environment"} == 1'
DSPACE_INSTRUMENTATION_HEALTH = 'min(dspace_instrumentation_up{environment=~"$environment"}) == 1'
DSPACE_TARGET_FAILURES = (
    '(count((up{namespace="dspace",service=~"dspace.*"} == 0) or '
    '((kube_pod_container_status_ready{namespace="dspace",container="dspace"} == 1 '
    'and on (namespace, pod) kube_pod_status_phase{namespace="dspace",phase="Running"} == 1 '
    'unless on (namespace, pod) kube_pod_deletion_timestamp{namespace="dspace"}) '
    'unless on (namespace, pod) up{namespace="dspace",service=~"dspace.*"})) or on() '
    f"(0 * count({CAPABILITY}))) {CAPABILITY_PRESENCE_GATE}"
)
DSPACE_COMPLETE_HEALTH_GATE = (
    f"and on() (({DSPACE_TARGET_FAILURES}) == 0) " f"and on() ({DSPACE_INSTRUMENTATION_HEALTH})"
)
FIVE_XX_RATIO_EXPRESSIONS = {
    "5xx error ratio": (
        '(sum(rate(dspace_http_requests_total{environment=~"$environment",status_class="5xx"}'
        "[$__rate_interval])) or on() (0 * sum(rate(dspace_http_requests_total{"
        'environment=~"$environment"}[$__rate_interval])))) / clamp_min(sum(rate('
        'dspace_http_requests_total{environment=~"$environment"}[$__rate_interval])), 1e-9)'
    ),
    "token.place HTTP 5xx ratio": (
        '(sum(rate(tokenplace_http_requests_total{app="tokenplace",environment=~"$environment",'
        'release="tokenplace",cluster=~"$cluster",namespace="tokenplace",status_class="5xx"}'
        "[$__rate_interval])) or on() (0 * sum(rate(tokenplace_http_requests_total{"
        'app="tokenplace",environment=~"$environment",release="tokenplace",cluster=~"$cluster",'
        'namespace="tokenplace"}[$__rate_interval])))) / clamp_min(sum(rate('
        'tokenplace_http_requests_total{app="tokenplace",environment=~"$environment",'
        'release="tokenplace",cluster=~"$cluster",namespace="tokenplace"}'
        "[$__rate_interval])), 1e-9)"
    ),
}
DANIEL_CACHE_HEALTH_GATE = (
    'max(daniel_github_cache_collection_up{environment=~"$environment",'
    'name=~"danielsmith-github-cache-$environment",cluster=~"$cluster"}) == 1 '
    'and on() max(daniel_github_cache_monitoring_enabled{environment=~"$environment",'
    'name=~"danielsmith-github-cache-$environment",cluster=~"$cluster"}) == 1 '
    "and on() (time() - max(daniel_github_cache_collection_timestamp_seconds{"
    'environment=~"$environment",name=~"danielsmith-github-cache-$environment",'
    'cluster=~"$cluster"}) <= 910)'
)
DANIEL_CACHE_PANEL_CONTRACT = {
    "Daniel cache state": (
        [
            (
                "max by (state) (daniel_github_cache_state) "
                f"and on() ({DANIEL_CACHE_HEALTH_GATE})",
                "{{state}}",
            ),
            (
                "max by (category) (daniel_github_cache_refresh_failure) "
                f"and on() ({DANIEL_CACHE_HEALTH_GATE})",
                "failure {{category}}",
            ),
            (
                'max(daniel_github_cache_monitoring_enabled{environment=~"$environment",'
                'name=~"danielsmith-github-cache-$environment",cluster=~"$cluster"})',
                "monitoring enabled",
            ),
            (
                'max(daniel_github_cache_collection_up{environment=~"$environment",'
                'name=~"danielsmith-github-cache-$environment",cluster=~"$cluster"})',
                "collection up",
            ),
        ],
        "short",
    ),
    "Daniel cache freshness": (
        [
            (
                "time() - max(daniel_github_cache_last_success_unixtime_seconds) "
                "and on() (max(daniel_github_cache_last_success_unixtime_seconds) > 0) "
                f"and on() ({DANIEL_CACHE_HEALTH_GATE})",
                "age",
            )
        ],
        "s",
    ),
    "Daniel cache completeness": (
        [
            (
                "max by (completeness) (daniel_github_cache_data_completeness) "
                f"and on() ({DANIEL_CACHE_HEALTH_GATE})",
                "{{completeness}}",
            )
        ],
        "short",
    ),
    "Daniel cache refresh duration": (
        [
            (
                "max(daniel_github_cache_refresh_duration_milliseconds) "
                f"and on() ({DANIEL_CACHE_HEALTH_GATE})",
                "duration",
            )
        ],
        "ms",
    ),
    "Daniel cache retained-data age": (
        [
            (
                "max(daniel_github_cache_retained_data_age_seconds) "
                f"and on() ({DANIEL_CACHE_HEALTH_GATE})",
                "age",
            )
        ],
        "s",
    ),
}
DANIEL_PANEL_CONTRACT = {
    "Daniel collection/document status": (
        "max by (environment, status) "
        '(daniel_performance_document_status{environment=~"$environment"})',
        "short",
        "{{environment}} {{status}}",
    ),  # noqa: E501
    "Daniel measurement age": (
        "time() - max by (environment, instance, job) "
        '(daniel_performance_measurement_timestamp_seconds{environment=~"$environment"})',
        "s",
        "{{environment}} age",
    ),  # noqa: E501
    "Daniel performance result state": (
        "max by (environment, state) ((max by (environment, instance, job, state) "
        '(daniel_performance_result_state{environment=~"$environment"})) and '
        "on(environment, instance, job) (max by (environment, instance, job) "
        '(daniel_performance_measurement_timestamp_seconds{environment=~"$environment"}) '
        "> time() - 86400))",
        "short",
        "{{environment}} {{state}}",
    ),  # noqa: E501
    "Daniel application-ready duration": (
        "max by (environment, renderer_class, renderer_state, fallback_status) ((max by "
        "(environment, instance, job, renderer_class, renderer_state, fallback_status) "
        '(daniel_performance_application_ready_seconds{environment=~"$environment",'
        'statistic="p95"})) and on(environment, instance, job) (max by '
        "(environment, instance, job) "
        '(daniel_performance_measurement_timestamp_seconds{environment=~"$environment"}) '
        "> time() - 86400))",
        "s",
        "{{environment}} {{renderer_class}} {{renderer_state}} {{fallback_status}} p95",
    ),  # noqa: E501
    "Daniel controlled interaction latency": (
        "max by (environment, renderer_class, renderer_state, fallback_status, statistic) "
        "((max by (environment, instance, job, renderer_class, renderer_state, "
        "fallback_status, statistic) "
        '(daniel_performance_interaction_latency_seconds{environment=~"$environment"})) '
        "and on(environment, instance, job) (max by (environment, instance, job) "
        '(daniel_performance_measurement_timestamp_seconds{environment=~"$environment"}) '
        "> time() - 86400))",
        "s",
        "{{environment}} {{renderer_class}} {{renderer_state}} {{fallback_status}} {{statistic}}",
    ),  # noqa: E501
    "Daniel renderer and fallback state": (
        "max by (environment, renderer_class, renderer_state, fallback_status) (((max by "
        "(environment, instance, job, renderer_class) "
        '(daniel_performance_renderer_class{environment=~"$environment"} == 1)) * '
        "on(environment, instance, job) group_left(renderer_state) (max by "
        "(environment, instance, job, renderer_state) "
        '(daniel_performance_renderer_state{environment=~"$environment"} == 1)) * '
        "on(environment, instance, job) group_left(fallback_status) (max by "
        "(environment, instance, job, fallback_status) "
        '(daniel_performance_fallback_status{environment=~"$environment"} == 1))) '
        "and on(environment, instance, job) (max by (environment, instance, job) "
        '(daniel_performance_measurement_timestamp_seconds{environment=~"$environment"}) '
        "> time() - 86400))",
        "short",
        "{{environment}} {{renderer_class}} {{renderer_state}} {{fallback_status}}",
    ),  # noqa: E501
    "Daniel controlled frame time": (
        "max by (environment, renderer_class, renderer_state, fallback_status, statistic) "
        "((max by (environment, instance, job, renderer_class, renderer_state, "
        "fallback_status, statistic) "
        '(daniel_performance_frame_time_seconds{environment=~"$environment"})) and '
        "on(environment, instance, job) (max by (environment, instance, job) "
        '(daniel_performance_measurement_timestamp_seconds{environment=~"$environment"}) '
        "> time() - 86400))",
        "s",
        "{{environment}} {{renderer_class}} {{renderer_state}} {{fallback_status}} {{statistic}}",
    ),  # noqa: E501
}
DANIEL_VISITOR_SELECTOR = (
    'application="danielsmith",environment=~"$environment",'
    'name=~"danielsmith-visitor-journey-$environment",cluster=~"$cluster"'
)
DANIEL_VISITOR_BASE_SELECTOR = (
    'application="danielsmith",environment=~"$environment",'
    'name=~"danielsmith-visitor-journey-$environment"'
)
DANIEL_VISITOR_IDENTITY = "application, environment, name, cluster"


def _visitor_metric(metric, extra_selector=""):
    selector = DANIEL_VISITOR_BASE_SELECTOR + extra_selector
    return (
        f'label_replace(({metric}{{{selector},cluster=~"$cluster"}} or '
        f'{metric}{{{selector},cluster=""}}), "cluster", "${{CLUSTER}}", "cluster", "^$")'
    )


DANIEL_VISITOR_EXPECTED = _visitor_metric("danielsmith_visitor_journey_monitoring_expected")
DANIEL_VISITOR_ENABLED = _visitor_metric("danielsmith_visitor_journey_monitoring_enabled")
DANIEL_VISITOR_FRESHNESS = _visitor_metric(
    "danielsmith_visitor_journey_freshness_timestamp_seconds"
)
DANIEL_VISITOR_CURRENT = f"(time() - {DANIEL_VISITOR_FRESHNESS} <= 1020)"
DANIEL_VISITOR_ACTIVE_STATE = (
    _visitor_metric(
        "danielsmith_visitor_journey_state",
        ',state=~"success|recovered|failure"',
    )
    + " == 1"
)
DANIEL_VISITOR_EXPECTED_ENABLED = (
    f"({DANIEL_VISITOR_EXPECTED} == 1) and on ({DANIEL_VISITOR_IDENTITY}) "
    f"({DANIEL_VISITOR_ENABLED} == 1)"
)
DANIEL_VISITOR_FAILURE_STAGE = _visitor_metric(
    "danielsmith_visitor_journey_failure_stage", ',failure_stage!="none"'
)
DANIEL_VISITOR_UNAVAILABLE_STATE = _visitor_metric(
    "danielsmith_visitor_journey_state", ',state=~"unavailable|stale"'
)
DANIEL_VISITOR_PANEL_CONTRACT = {
    "Daniel visitor journey state": (
        f"max by (state) (({_visitor_metric('danielsmith_visitor_journey_state')}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_EXPECTED_ENABLED}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) {DANIEL_VISITOR_CURRENT})",
        "short",
        "{{state}}",
    ),
    "Daniel visitor journey success": (
        f"max by ({DANIEL_VISITOR_IDENTITY}) "
        f"({_visitor_metric('danielsmith_visitor_journey_success')}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_EXPECTED_ENABLED}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) {DANIEL_VISITOR_CURRENT} "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_ACTIVE_STATE})",
        "short",
        "success",
    ),
    "Daniel visitor journey freshness": (
        f"time() - max by ({DANIEL_VISITOR_IDENTITY}) "
        f"({DANIEL_VISITOR_FRESHNESS}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_EXPECTED_ENABLED})",
        "s",
        "age",
    ),
    "Daniel visitor journey aggregate duration": (
        f"max by ({DANIEL_VISITOR_IDENTITY}) "
        f"({_visitor_metric('danielsmith_visitor_journey_duration_seconds')}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_EXPECTED_ENABLED}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) {DANIEL_VISITOR_CURRENT} "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_ACTIVE_STATE})",
        "s",
        "duration",
    ),
    "Daniel visitor journey failure stage": (
        f"max by ({DANIEL_VISITOR_IDENTITY}, failure_stage) "
        f"({DANIEL_VISITOR_FAILURE_STAGE}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_EXPECTED_ENABLED}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) {DANIEL_VISITOR_CURRENT} "
        f"and on ({DANIEL_VISITOR_IDENTITY}) "
        f"({_visitor_metric('danielsmith_visitor_journey_state', ',state=\"failure\"')} == 1)",
        "short",
        "{{failure_stage}}",
    ),
    "Daniel visitor journey unavailable or stale": (
        f"max by (state) (label_replace((({DANIEL_VISITOR_EXPECTED} == 1) "
        f"unless on ({DANIEL_VISITOR_IDENTITY}) {DANIEL_VISITOR_FRESHNESS}) or "
        f"(({DANIEL_VISITOR_EXPECTED} == 1) and on ({DANIEL_VISITOR_IDENTITY}) "
        f'(time() - {DANIEL_VISITOR_FRESHNESS} > 1020)), "state", "stale", "", "") or '
        f"(({DANIEL_VISITOR_UNAVAILABLE_STATE}) "
        f"and on ({DANIEL_VISITOR_IDENTITY}) ({DANIEL_VISITOR_EXPECTED} == 1)))",
        "short",
        "{{state}}",
    ),
}
DANIEL_VISITOR_LAYOUT_CONTRACT = {
    "Daniel visitor journey": (79, "row", {"h": 1, "w": 24, "x": 0, "y": 247}),
    "Daniel visitor journey state": (80, "timeseries", {"h": 8, "w": 12, "x": 0, "y": 248}),
    "Daniel visitor journey success": (
        81,
        "timeseries",
        {"h": 8, "w": 12, "x": 12, "y": 248},
    ),
    "Daniel visitor journey freshness": (
        82,
        "timeseries",
        {"h": 8, "w": 12, "x": 0, "y": 256},
    ),
    "Daniel visitor journey aggregate duration": (
        83,
        "timeseries",
        {"h": 8, "w": 12, "x": 12, "y": 256},
    ),
    "Daniel visitor journey failure stage": (
        84,
        "timeseries",
        {"h": 8, "w": 12, "x": 0, "y": 264},
    ),
    "Daniel visitor journey unavailable or stale": (
        85,
        "timeseries",
        {"h": 8, "w": 12, "x": 12, "y": 264},
    ),
}

OVERVIEW_PANEL_CONTRACT = {
    "Desired versus ready replicas": {
        "metrics": {"kube_deployment_spec_replicas", "kube_deployment_status_replicas_ready"},
        "targets": 2,
    },
    "Serving workload node placement": {
        "metrics": {
            "kube_pod_info",
            "kube_pod_status_ready",
            "kube_pod_status_phase",
            "kube_pod_deletion_timestamp",
        },
        "targets": 1,
    },
    "Memory working set versus configured limit": {
        "metrics": {"container_memory_working_set_bytes", "kube_pod_container_resource_limits"},
        "targets": 2,
    },
    "CPU throttling": {
        "metrics": {
            "container_memory_working_set_bytes",
            "container_cpu_cfs_throttled_periods_total",
            "container_cpu_cfs_periods_total",
        },
        "targets": 1,
    },
    "Deployment image coordinates": {
        "metrics": {
            "kube_pod_container_info",
            "kube_pod_status_ready",
            "kube_pod_status_phase",
            "kube_pod_deletion_timestamp",
        },
        "targets": 1,
    },
    "Application build identity": {
        "metrics": {"dspace_build_info", "tokenplace_build_info"},
        "targets": 1,
    },
}


def _metric_selectors_are_workload_scoped(expression: str, metrics: set[str]) -> bool:
    """Return whether every required metric selector carries the workload matcher."""
    for metric in metrics:
        selectors = re.finditer(
            rf"(?<![a-zA-Z0-9_:]){re.escape(metric)}(?![a-zA-Z0-9_:])" r"(?:\s*\{([^{}]*)\})?",
            expression,
        )
        if any(
            match.group(1) is None or 'namespace=~"$workload"' not in match.group(1)
            for match in selectors
        ):
            return False
    return True


def _metric_matchers(expression: str, metric: str) -> list[str]:
    """Return the matcher text for every selector of one metric."""
    return [
        match.group(1) or ""
        for match in re.finditer(
            rf"(?<![a-zA-Z0-9_:]){re.escape(metric)}(?![a-zA-Z0-9_:])" r"(?:\s*\{([^{}]*)\})?",
            expression,
        )
    ]


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


def panel_expression(dashboard: dict, title: str) -> str:
    targets = panel_named(dashboard, title).get("targets", [])
    if len(targets) != 1 or not isinstance(targets[0].get("expr"), str):
        raise SystemExit(f"ERROR: {title} must contain exactly one PromQL target.")
    return re.sub(r"\s+", " ", targets[0]["expr"])


def _has_outer_presence_gate(expression: str, presence_gate: str) -> bool:
    """Return whether one parenthesized result is followed by a presence gate."""
    normalized = re.sub(r"\s+", " ", expression).strip()
    suffix = " " + presence_gate
    if not normalized.endswith(suffix):
        return False
    result = normalized[: -len(suffix)]
    if not result.startswith("(") or not result.endswith(")"):
        return False
    depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(result):
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0 and index != len(result) - 1:
                return False
            if depth < 0:
                return False
    return depth == 0 and not quoted


def _has_outer_capability_presence_gate(expression: str) -> bool:
    return _has_outer_presence_gate(expression, CAPABILITY_PRESENCE_GATE)


def _has_outer_dspace_instrumentation_presence_gate(expression: str) -> bool:
    return _has_outer_presence_gate(expression, DSPACE_COMPLETE_HEALTH_GATE)


def configure_profile(dashboard: dict) -> bool:
    """Select the supported profile and configure rendered mount identity."""
    global TITLE, UID, DASHBOARD_FILE, DASHBOARD_MOUNT
    identity = (dashboard.get("uid"), dashboard.get("title"))
    selected = next(
        (
            name
            for name, profile in PROFILES.items()
            if identity == (profile["UID"], profile["TITLE"])
        ),
        None,
    )
    if selected is None:
        raise SystemExit("ERROR: dashboard title and UID do not match a supported profile.")
    UID, TITLE = identity
    DASHBOARD_FILE = f"{UID}.json"
    DASHBOARD_MOUNT = f"{DASHBOARD_PATH}/{DASHBOARD_FILE}"
    return selected == "prod"


def _expected_dashboard(dashboard: dict) -> dict:
    production = configure_profile(dashboard)
    return json.loads(render(PROFILES["prod" if production else "staging"]))


def _validate_grid(items: list[dict]) -> None:
    if len(items) != 92 or sum(panel.get("type") == "row" for panel in items) != 15:
        raise SystemExit("ERROR: canonical dashboard must contain exactly 92 objects and 15 rows.")
    ids = [panel.get("id") for panel in items]
    if ids != list(range(1, 93)):
        raise SystemExit(
            "ERROR: canonical dashboard panel IDs must be stable consecutive integers."
        )
    rectangles = []
    for panel in items:
        position = panel.get("gridPos", {})
        if any(not isinstance(position.get(key), int) for key in ("x", "y", "w", "h")):
            raise SystemExit("ERROR: dashboard panels must have valid integer grid positions.")
        if (
            position["x"] < 0
            or position["y"] < 0
            or position["w"] <= 0
            or position["h"] <= 0
            or position["x"] + position["w"] > 24
        ):
            raise SystemExit("ERROR: dashboard panels must have valid integer grid positions.")
        if panel.get("type") == "row":
            continue
        rect = (
            position["x"],
            position["y"],
            position["x"] + position["w"],
            position["y"] + position["h"],
        )
        if any(
            rect[0] < other[2] and rect[2] > other[0] and rect[1] < other[3] and rect[3] > other[1]
            for other in rectangles
        ):
            raise SystemExit("ERROR: dashboard panel grid positions must not overlap.")
        rectangles.append(rect)


def _validate_semantics(dashboard: dict) -> None:
    items = list(panels(dashboard))
    for title, (expected_targets, expected_unit) in DANIEL_CACHE_PANEL_CONTRACT.items():
        daniel_panel = panel_named(dashboard, title)
        targets = daniel_panel.get("targets", [])
        defaults = daniel_panel.get("fieldConfig", {}).get("defaults", {})
        expected = [
            {"refId": chr(ord("A") + index), "expr": expression, "legendFormat": legend}
            for index, (expression, legend) in enumerate(expected_targets)
        ]
        if (
            targets != expected
            or defaults.get("unit") != expected_unit
            or defaults.get("noValue") != "NO DATA"
            or any("vector(0)" in expression for expression, _legend in expected_targets)
        ):
            raise SystemExit(f"ERROR: {title} does not match the bounded Daniel cache contract.")
    for title, (
        expected_id,
        expected_type,
        expected_grid_position,
    ) in DANIEL_VISITOR_LAYOUT_CONTRACT.items():
        visitor_panel = panel_named(dashboard, title)
        if (
            visitor_panel.get("id") != expected_id
            or visitor_panel.get("type") != expected_type
            or visitor_panel.get("gridPos") != expected_grid_position
        ):
            raise SystemExit(f"ERROR: {title} does not match the stable visitor layout contract.")
    _validate_grid(items)
    data_panels = [panel for panel in items if panel.get("type") not in {"row", "text"}]
    if any(
        panel.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA"
        for panel in data_panels
    ):
        raise SystemExit("ERROR: every data panel must explicitly preserve NO DATA.")
    tables = [panel for panel in items if panel.get("type") == "table"]
    if len(tables) != 12:
        raise SystemExit("ERROR: canonical dashboard must contain exactly twelve tables.")
    for table in tables:
        targets = table.get("targets", [])
        transforms = table.get("transformations", [])
        if (
            len(targets) != 1
            or targets[0].get("format") != "table"
            or targets[0].get("instant") is not True
            or targets[0].get("range") is not False
        ):
            raise SystemExit("ERROR: tables require one table-formatted instant-only target.")
        if len(transforms) != 1 or transforms[0].get("id") != "organize":
            raise SystemExit(
                "ERROR: tables require exactly one deterministic organize transformation."
            )
        options = transforms[0].get("options", {})
        if not options.get("indexByName") or not options.get("renameByName"):
            raise SystemExit("ERROR: tables must explicitly order and rename visible columns.")
        excluded = {key for key, value in options.get("excludeByName", {}).items() if value}
        if not {"Time", "__name__"} <= excluded:
            raise SystemExit("ERROR: tables must hide Time and __name__ fields.")
    variables = dashboard.get("templating", {}).get("list", [])
    if [variable.get("name") for variable in variables] != [
        "environment",
        "cluster",
        "app",
        "route",
        "workload",
    ]:
        raise SystemExit("ERROR: dashboard variables must use the canonical shape.")
    for variable in variables[:2]:
        if (
            variable.get("type") != "constant"
            or variable.get("hide") != 2
            or variable.get("multi") is not False
        ):
            raise SystemExit(
                "ERROR: environment and cluster must be hidden single-value constants."
            )
    if any(
        variable.get("allValue") != ".*" or variable.get("includeAll") is not True
        for variable in variables[2:4]
    ):
        raise SystemExit("ERROR: app and route variables must expose All = .*.")
    workload = variables[4]
    if (
        workload.get("type") != "custom"
        or workload.get("query") != "dspace,tokenplace,danielsmith"
        or workload.get("includeAll") is not True
        or workload.get("multi") is not True
        or workload.get("allValue") != "dspace|tokenplace|danielsmith"
    ):
        raise SystemExit("ERROR: workload selector must contain exactly the three supported apps.")
    expressions = [
        target["expr"]
        for panel in items
        for target in panel.get("targets", [])
        if isinstance(target.get("expr"), str)
    ]
    expression_text = "\n".join(expressions)

    overview_row = panel_named(
        dashboard, "Cross-application resource, placement and release overview"
    )
    if overview_row.get("type") != "row":
        raise SystemExit("ERROR: cross-application overview must be a dedicated row.")
    for title, contract in OVERVIEW_PANEL_CONTRACT.items():
        overview_panel = panel_named(dashboard, title)
        targets = overview_panel.get("targets", [])
        overview_expressions = [target.get("expr", "") for target in targets]
        combined = "\n".join(overview_expressions)
        if len(targets) != contract["targets"] or not contract["metrics"] <= set(
            re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", combined)
        ):
            raise SystemExit(f"ERROR: {title} does not contain its required metric contract.")
        if any(
            not _metric_selectors_are_workload_scoped(expression, contract["metrics"])
            for expression in overview_expressions
        ):
            raise SystemExit(f"ERROR: {title} must use the dedicated workload namespace scope.")
        if any("vector(0)" in expression for expression in overview_expressions):
            raise SystemExit(f"ERROR: {title} must preserve unsupported or missing data.")
    for title in ("Serving workload node placement", "Deployment image coordinates"):
        expression = panel_expression(dashboard, title)
        if not all(
            fragment in expression
            for fragment in (
                'kube_pod_status_ready{namespace=~"$workload",condition="true"} == 1',
                'kube_pod_status_phase{namespace=~"$workload",phase="Running"} == 1',
                'unless on (namespace, pod) kube_pod_deletion_timestamp{namespace=~"$workload"}',
            )
        ):
            raise SystemExit(
                f"ERROR: {title} must exclude unready, non-Running, and terminating pods."
            )
    serving_target = panel_named(dashboard, "Serving workload node placement")["targets"][0]
    if serving_target.get("instant") is not True or serving_target.get("range") is not False:
        raise SystemExit("ERROR: serving-node placement must be an instant-only current value.")
    placement = panel_expression(dashboard, "Serving workload node placement")
    if "count by (namespace) (count by (namespace, node)" not in placement:
        raise SystemExit(
            "ERROR: placement must count distinct serving nodes without pod double counting."
        )
    replicas = panel_named(dashboard, "Desired versus ready replicas")
    if any(
        not target["expr"].startswith("max by (namespace, deployment)")
        or "sum by" in target["expr"]
        or "{{deployment}}" not in target.get("legendFormat", "")
        for target in replicas["targets"]
    ):
        raise SystemExit("ERROR: replica overview must preserve namespace and deployment identity.")
    memory = panel_named(dashboard, "Memory working set versus configured limit")
    if any(
        "max by (namespace, pod, container)" not in target["expr"] for target in memory["targets"]
    ):
        raise SystemExit("ERROR: memory overview must deduplicate container scrape series.")
    memory_text = "\n".join(target["expr"] for target in memory["targets"])
    if any(
        fragment not in memory_text
        for fragment in (
            'pod!=""',
            'container!=""',
            'container!="POD"',
            'resource="memory"',
            "> 0",
            "and on (namespace, pod, container)",
            "count by (namespace)",
            "== count by (namespace)",
        )
    ):
        raise SystemExit("ERROR: memory limits require complete positive container coverage.")
    cpu = panel_expression(dashboard, "CPU throttling")
    if (
        any(
            fragment not in cpu
            for fragment in (
                'pod!=""',
                'container!=""',
                'container!="POD"',
                "and on (namespace, pod, container)",
                "> 0",
                "count by (namespace)",
                "== count by (namespace)",
            )
        )
        or cpu.count("container_memory_working_set_bytes") < 4
        or cpu.count(
            "and on (namespace, pod, container) max by (namespace, pod, container) "
            "(container_memory_working_set_bytes"
        )
        < 3
        or cpu.count("== count by (namespace)") != 1
    ):
        raise SystemExit(
            "ERROR: CPU throttling requires complete observed, matched, positive container coverage."
        )
    image_panel = panel_named(dashboard, "Deployment image coordinates")
    image_expression = panel_expression(dashboard, "Deployment image coordinates")
    if (
        "not runtime/build proof" not in image_panel.get("description", "")
        or "image_spec" not in image_expression
        or "max by (namespace, pod, container, image_spec)" not in image_expression
        or "{{image_spec}}" not in image_panel["targets"][0].get("legendFormat", "")
        or image_panel["transformations"][0]["options"]["renameByName"].get("image_spec")
        != "Configured image coordinate"
    ):
        raise SystemExit("ERROR: image coordinates must disclaim runtime/build proof.")
    build_expression = panel_expression(dashboard, "Application build identity")
    dspace_matchers = _metric_matchers(build_expression, "dspace_build_info")
    token_matchers = _metric_matchers(build_expression, "tokenplace_build_info")
    if (
        len(dspace_matchers) != 1
        or 'environment=~"$environment"' not in dspace_matchers[0]
        or len(token_matchers) != 1
        or 'environment=~"$environment"' not in token_matchers[0]
        or 'cluster=~"$cluster"' not in token_matchers[0]
        or 'app="tokenplace"' not in token_matchers[0]
        or 'release="tokenplace"' not in token_matchers[0]
    ):
        raise SystemExit("ERROR: build identity selectors must retain exact profile scope.")
    if "kube_state_metrics_build_info" in expression_text:
        raise SystemExit("ERROR: unavailable kube-state-metrics build identity is forbidden.")
    if re.search(
        r"cluster\s*(?:=|=~)", "\n".join(expr for expr in expressions if "$cluster" not in expr)
    ):
        raise SystemExit("ERROR: core local queries must not select an external cluster label.")
    token_expressions = [
        target["expr"]
        for title in TOKENPLACE_DATA_TITLES
        for target in panel_named(dashboard, title).get("targets", [])
    ]
    if any(
        'environment=~"$environment"' not in expr or 'cluster=~"$cluster"' not in expr
        for expr in token_expressions
    ):
        raise SystemExit("ERROR: token.place queries require environment and cluster variables.")
    if any("vector(0)" in expr for expr in token_expressions):
        raise SystemExit("ERROR: token.place queries must preserve missing data.")
    for title, (
        expected_expression,
        expected_unit,
        expected_legend,
    ) in DANIEL_PANEL_CONTRACT.items():
        daniel_panel = panel_named(dashboard, title)
        targets = daniel_panel.get("targets", [])
        defaults = daniel_panel.get("fieldConfig", {}).get("defaults", {})
        if (
            len(targets) != 1
            or targets[0].get("expr") != expected_expression
            or targets[0].get("legendFormat") != expected_legend
            or defaults.get("unit") != expected_unit
            or defaults.get("noValue") != "NO DATA"
            or "vector(0)" in expected_expression
        ):
            raise SystemExit(f"ERROR: {title} does not match the bounded Daniel contract.")
    for title, (
        expected_expression,
        expected_unit,
        expected_legend,
    ) in DANIEL_VISITOR_PANEL_CONTRACT.items():
        cluster_value = next(
            variable["current"]["value"]
            for variable in variables
            if variable.get("name") == "cluster"
        )
        expected_expression = expected_expression.replace("${CLUSTER}", cluster_value)
        visitor_panel = panel_named(dashboard, title)
        targets = visitor_panel.get("targets", [])
        defaults = visitor_panel.get("fieldConfig", {}).get("defaults", {})
        if (
            len(targets) != 1
            or targets[0].get("expr") != expected_expression
            or targets[0].get("legendFormat") != expected_legend
            or defaults.get("unit") != expected_unit
            or defaults.get("noValue") != "NO DATA"
            or "vector(0)" in expected_expression
        ):
            raise SystemExit(f"ERROR: {title} does not match the visitor journey contract.")
    for title, expected in FIVE_XX_RATIO_EXPRESSIONS.items():
        if panel_expression(dashboard, title) != expected:
            raise SystemExit(f"ERROR: {title} must use its request-family-gated 5xx zero contract.")
    chat_panels = [panel_named(dashboard, title) for title in DSPACE_CHAT_PANEL_TITLES]
    chat_expressions = [
        target.get("expr", "") for panel in chat_panels for target in panel.get("targets", [])
    ]
    if any('environment=~"$environment"' not in expression for expression in chat_expressions):
        raise SystemExit("ERROR: DSPACE chat queries require environment scoping.")
    if not DSPACE_CHAT_METRICS <= {
        metric for metric in DSPACE_CHAT_METRICS if metric in "\n".join(chat_expressions)
    }:
        raise SystemExit("ERROR: DSPACE chat panels must cover counters and latency histograms.")
    for title, metric, dimension in (
        ("DSPACE chat outcome rate", "dspace_dchat_requests_total", "provider"),
        ("DSPACE dependency outcome rate", "dspace_dependency_requests_total", "dependency"),
    ):
        rate = f'rate({metric}{{environment=~"$environment"}}[$__rate_interval])'
        expected = [
            f"(sum by ({dimension}, outcome) ({rate})) {DSPACE_COMPLETE_HEALTH_GATE}",
            f"((0 * count({DSPACE_HEALTH})) unless on() sum({rate})) "
            f"{DSPACE_COMPLETE_HEALTH_GATE}",
        ]
        targets = panel_named(dashboard, title).get("targets", [])
        if (
            [target.get("expr") for target in targets] != expected
            or targets[0].get("legendFormat") != f"{{{{{dimension}}}}} {{{{outcome}}}}"
            or targets[1].get("legendFormat") != "idle"
            or any("label_replace" in expression for expression in expected)
        ):
            raise SystemExit(f"ERROR: {title} must use the complete health-gated idle contract.")
    for title in ("DSPACE chat latency percentiles", "DSPACE dependency latency percentiles"):
        targets = panel_named(dashboard, title).get("targets", [])
        expected_dimension = "provider" if "chat latency" in title else "dependency"
        metric = (
            "dspace_dchat_request_duration_seconds"
            if expected_dimension == "provider"
            else "dspace_dependency_request_duration_seconds"
        )
        expected = [
            f"((histogram_quantile(.{quantile}, sum by (le, {expected_dimension}, outcome) "
            f'(rate({metric}_bucket{{environment=~"$environment"}}[$__rate_interval])))) '
            f"and on ({expected_dimension}, outcome) (sum by ({expected_dimension}, outcome) "
            f'(rate({metric}_count{{environment=~"$environment"}}[$__rate_interval])) > 0)) '
            f"{DSPACE_COMPLETE_HEALTH_GATE}"
            for quantile in ("50", "95", "99")
        ]
        if len(targets) != 3 or [target.get("expr") for target in targets] != expected:
            raise SystemExit(
                f"ERROR: {title} requires p50/p95/p99 histograms grouped by le, "
                f"{expected_dimension}, and outcome."
            )
    primary = panel_expression(dashboard, "DSPACE primary-provider success ratio")
    fallback = panel_expression(dashboard, "DSPACE fallback-use ratio")
    profile = next(profile for profile in PROFILES.values() if profile["UID"] == dashboard["uid"])
    provider = profile["PRIMARY_PROVIDER"]
    primary_selector = (
        'dspace_dchat_requests_total{environment=~"$environment",' f'provider="{provider}"'
    )
    if (
        primary.count(primary_selector) != 2
        or primary.count('outcome="success"') != 1
        or 'outcome!="fallback_used"' in primary
        or primary.count("dspace_dchat_requests_total") != 2
    ):
        raise SystemExit(
            "ERROR: primary success must include fallback outcomes in its denominator."
        )
    if (
        fallback.count("dspace_dchat_requests_total") != 2
        or fallback.count('outcome="fallback_used"') != 1
    ):
        raise SystemExit("ERROR: fallback-use ratio must use all chat requests as its denominator.")
    expected_primary = (
        "((sum(rate("
        + primary_selector
        + ',outcome="success"}[$__rate_interval])) or on() (0 * count('
        + DSPACE_HEALTH
        + "))) / clamp_min(sum(rate("
        + primary_selector
        + "}[$__rate_interval])) or on() (0 * count("
        + DSPACE_HEALTH
        + f")), 1e-9)) {DSPACE_COMPLETE_HEALTH_GATE}"
    )
    expected_fallback = (
        '((sum(rate(dspace_dchat_requests_total{environment=~"$environment",'
        'outcome="fallback_used"}[$__rate_interval])) or on() (0 * count('
        + DSPACE_HEALTH
        + '))) / clamp_min(sum(rate(dspace_dchat_requests_total{environment=~"$environment"}'
        "[$__rate_interval])) or on() (0 * count("
        + DSPACE_HEALTH
        + f")), 1e-9)) {DSPACE_COMPLETE_HEALTH_GATE}"
    )
    if primary != expected_primary or fallback != expected_fallback:
        raise SystemExit("ERROR: DSPACE ratios must use the complete health-gated contracts.")
    if any(
        "divided by" not in panel.get("description", "").lower()
        for panel in chat_panels
        if "ratio" in panel.get("title", "").lower()
    ):
        raise SystemExit("ERROR: every DSPACE chat ratio must document its denominator.")
    capability_targets = {
        "Image-pin agreement": [panel_expression(dashboard, "Image-pin agreement")],
        "DSPACE metrics-target health": [
            panel_expression(dashboard, "DSPACE metrics-target health")
        ],
        "/chat synthetic result and freshness": [
            re.sub(r"\s+", " ", target.get("expr", ""))
            for target in panel_named(dashboard, "/chat synthetic result and freshness").get(
                "targets", []
            )
        ],
    }
    for title, targets in capability_targets.items():
        if not targets or any(
            not _has_outer_capability_presence_gate(expression) for expression in targets
        ):
            raise SystemExit(
                f"ERROR: {title} requires an outer approved-release capability-presence gate."
            )
    for title in ("Image-pin agreement", "DSPACE metrics-target health"):
        if "0 * count(" + CAPABILITY not in capability_targets[title][0]:
            raise SystemExit(f"ERROR: {title} requires an approved-release-gated zero.")
    image_pin = panel_expression(dashboard, "Image-pin agreement")
    if '"^(docker-pullable://)?(.*)$"' not in image_pin:
        raise SystemExit("ERROR: image-pin comparison must normalize runtime image-ID prefixes.")
    if '"image_id", "unknown"' not in image_pin or '"image_spec", "unknown"' not in image_pin:
        raise SystemExit("ERROR: image-pin comparison must fail closed on missing metadata.")
    if (
        "0 * count(" + CAPABILITY
        not in panel_named(dashboard, "/chat synthetic result and freshness")["targets"][0]["expr"]
    ):
        raise SystemExit("ERROR: chat synthetic fallback requires approved-release capability.")
    blackbox = [expr for expr in expressions if "probe_" in expr or "blackbox-" in expr]
    if any("blackbox-" in expr and "-$environment-.*" not in expr for expr in blackbox):
        raise SystemExit("ERROR: blackbox jobs must use the environment variable.")
    serialized = json.dumps(dashboard)
    if re.search(r"{{\s*(?:" + "|".join(FORBIDDEN_LABELS) + r")\s*}}", serialized, re.I):
        raise SystemExit("ERROR: dashboard legends expose a forbidden raw identity label.")


def validate_dashboard(path: Path) -> str:
    dashboard = load_dashboard(path)
    expected = _expected_dashboard(dashboard)
    _validate_semantics(dashboard)
    # This authoritative comparison independently locks titles, types, queries,
    # transformations, IDs, order, and grid positions to the shared template.
    if dashboard != expected:
        differing = sorted(
            key for key in set(dashboard) | set(expected) if dashboard.get(key) != expected.get(key)
        )
        raise SystemExit(
            "ERROR: dashboard differs from canonical generated profile: " + ", ".join(differing)
        )
    return path.read_text(encoding="utf-8")


def validate_render(path: Path, dashboard_json: str) -> None:
    try:
        configure_profile(json.loads(dashboard_json))
    except json.JSONDecodeError as error:
        raise SystemExit("ERROR: dashboard JSON is malformed.") from error
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
