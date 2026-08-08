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
    "dspace_release_approved_info",
    "kube_pod_container_info",
    "dspace_chat_synthetic_success",
    "dspace_chat_synthetic_timestamp_seconds",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "probe_duration_seconds",
    "probe_http_status_code",
    "probe_ssl_earliest_cert_expiry",
    "tokenplace_compute_nodes_registered",
    "tokenplace_compute_nodes_healthy",
    "tokenplace_compute_node_lease_age_seconds",
    "tokenplace_compute_node_evictions_total",
    "tokenplace_relay_queue_depth",
    "tokenplace_relay_oldest_queued_request_age_seconds",
    "tokenplace_relay_in_flight_requests",
    "tokenplace_relay_oldest_in_flight_age_seconds",
    "tokenplace_relay_request_outcomes_total",
    "tokenplace_http_requests_total",
    "tokenplace_http_request_duration_seconds_bucket",
    "tokenplace_instrumentation_up",
    "tokenplace_build_info",
}
EVENT_METRICS = {"dspace_dchat_requests_total", "dspace_dependency_requests_total"}
OPERATIONAL_ROUTES = '"/(healthz|livez|metrics)"'
BLACKBOX_JOB_MATCHER = (
    'job=~"probe/monitoring/blackbox-(dspace|tokenplace|danielsmith|jobbot3000)-staging-.*"'
)
TOKENPLACE_ROWS = {
    "token.place relay and compute capacity",
    "token.place HTTP and release",
}
TOKENPLACE_PANELS = {
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
PHASE_TWO_METRICS = {
    "tokenplace_chat_availability",
    "tokenplace_compute_nodes_schedulable",
    "tokenplace_availability_reason",
    "tokenplace_shared_state_health",
    "tokenplace_relay_chat_available",
    "tokenplace_relay_schedulable_compute_nodes",
    "tokenplace_relay_chat_availability_state",
    "tokenplace_relay_state_store_up",
}
TOKENPLACE_LABELS = {
    "app",
    "environment",
    "release",
    "cluster",
    "namespace",
    "pod",
    "reason",
    "provider_mode",
    "outcome",
    "route",
    "status_class",
    "le",
    "version",
    "revision",
}
TOKENPLACE_PROMQL_FUNCTIONS = {
    "clamp_min",
    "histogram_quantile",
    "max",
    "min",
    "rate",
    "sum",
}
TOKENPLACE_PROMQL_MODIFIERS = {
    "and",
    "bool",
    "group_left",
    "group_right",
    "ignoring",
    "offset",
    "on",
    "or",
    "unless",
}
TOKENPLACE_CANONICAL_MATCHERS = {
    "app": ("=", '"tokenplace"'),
    "environment": ("=~", '"$environment"'),
    "release": ("=", '"tokenplace"'),
    "cluster": ("=", '"sugarkube-int"'),
    "namespace": ("=", '"tokenplace"'),
}
TOKENPLACE_RATE_METRICS = {
    "tokenplace_compute_node_evictions_total",
    "tokenplace_relay_request_outcomes_total",
    "tokenplace_http_requests_total",
    "tokenplace_http_request_duration_seconds_bucket",
}


def parse_tokenplace_matchers(matchers: str) -> dict:
    """Parse the deliberately small matcher grammar used by token.place panels."""
    parsed = {}
    for entry in matchers.split(","):
        match = re.fullmatch(
            r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(=~|!~|!=|=)\s*("(?:\\.|[^"\\])*")\s*',
            entry,
        )
        if not match or match.group(1) in parsed:
            raise ValueError("malformed or duplicate matcher")
        parsed[match.group(1)] = match.groups()[1:]
    return parsed


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
    panel = panel_named(dashboard, title)
    targets = panel.get("targets", [])
    if len(targets) != 1 or not isinstance(targets[0].get("expr"), str):
        raise SystemExit(f"ERROR: {title} must contain exactly one PromQL target.")
    return re.sub(r"\s+", " ", targets[0]["expr"])


def has_serving_pod_filter(expression: str) -> bool:
    return all(
        token in expression
        for token in (
            'kube_pod_container_status_ready{namespace="dspace",container="dspace"} == 1',
            "and on (namespace, pod) "
            'kube_pod_status_phase{namespace="dspace",phase="Running"} == 1',
            'unless on (namespace, pod) kube_pod_deletion_timestamp{namespace="dspace"}',
        )
    )


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

    revisions = panel_expression(dashboard, "Active build revisions by pod")
    if (
        "dspace_build_info" not in revisions
        or "and on (namespace, pod)" not in revisions
        or not has_serving_pod_filter(revisions)
    ):
        raise SystemExit("ERROR: active build revisions must include only serving DSPACE pods.")

    image_agreement = panel_expression(dashboard, "Image-pin agreement")
    if not has_serving_pod_filter(image_agreement) or "or on() vector(0)" not in image_agreement:
        raise SystemExit(
            "ERROR: image-pin agreement must filter serving pods and return a healthy zero."
        )

    target_panel = panel_named(dashboard, "DSPACE metrics-target health")
    target_health = panel_expression(dashboard, "DSPACE metrics-target health")
    if (
        not has_serving_pod_filter(target_health)
        or 'unless on (namespace, pod) up{namespace="dspace",service=~"dspace.*"}'
        not in target_health
        or 'up{namespace="dspace",service=~"dspace.*"} == 0' not in target_health
        or "count(" not in target_health
        or "or on() vector(0)" not in target_health
        or target_panel.get("targets", [{}])[0].get("legendFormat")
        != "down or missing serving targets"
        or "Zero is healthy; missing targets fail closed."
        not in target_panel.get("description", "")
    ):
        raise SystemExit(
            "ERROR: DSPACE metrics-target health must count down or missing serving targets."
        )


def validate_tokenplace_semantics(dashboard: dict) -> None:
    all_items = list(panels(dashboard))
    for title in TOKENPLACE_ROWS | TOKENPLACE_PANELS:
        matching = [panel for panel in all_items if panel.get("title") == title]
        if len(matching) != 1:
            raise SystemExit(f"ERROR: dashboard must contain exactly one {title!r} panel.")
    if any(panel_named(dashboard, title).get("type") != "row" for title in TOKENPLACE_ROWS):
        raise SystemExit("ERROR: token.place section headings must remain dashboard rows.")

    token_panels_by_title = {title: panel_named(dashboard, title) for title in TOKENPLACE_PANELS}
    expected_targets = {title: 1 for title in TOKENPLACE_PANELS}
    expected_targets["token.place compute-node counts"] = 2
    expected_targets["token.place HTTP latency percentiles"] = 3
    for title, expected_count in expected_targets.items():
        targets = token_panels_by_title[title].get("targets")
        if (
            not isinstance(targets, list)
            or len(targets) != expected_count
            or any(
                not isinstance(target, dict) or not target.get("expr", "").strip()
                for target in targets
            )
        ):
            raise SystemExit(
                f"ERROR: {title} must contain exactly {expected_count} non-empty target(s)."
            )

    token_panels = list(token_panels_by_title.values())
    expressions = [
        target.get("expr", "")
        for panel in token_panels
        for target in panel.get("targets", [])
        if isinstance(target, dict)
    ]
    if not expressions:
        raise SystemExit("ERROR: token.place panels must contain queries.")
    if any(
        "vector(0)" in expression or re.search(r"\bor\s+(?:on\(\)\s+)?0\b", expression)
        for expression in expressions
    ):
        raise SystemExit(
            "ERROR: token.place queries must preserve missing data instead of substituting zero."
        )
    if any(re.search(r"\blabel_(?:replace|join)\s*\(", expression) for expression in expressions):
        raise SystemExit("ERROR: token.place queries must not synthesize labels.")

    expected_metrics = {
        "token.place scrape availability": {"up"},
        "token.place instrumentation health": {"tokenplace_instrumentation_up"},
        "token.place compute-node counts": {
            "tokenplace_compute_nodes_registered",
            "tokenplace_compute_nodes_healthy",
        },
        "token.place oldest compute-node lease age": {"tokenplace_compute_node_lease_age_seconds"},
        "token.place compute-node eviction rate": {"tokenplace_compute_node_evictions_total"},
        "token.place relay queue depth": {"tokenplace_relay_queue_depth"},
        "token.place oldest queued-request age": {
            "tokenplace_relay_oldest_queued_request_age_seconds"
        },
        "token.place in-flight requests by pod": {"tokenplace_relay_in_flight_requests"},
        "token.place oldest in-flight age by pod": {
            "tokenplace_relay_oldest_in_flight_age_seconds"
        },
        "token.place terminal outcome rate": {"tokenplace_relay_request_outcomes_total"},
        "token.place HTTP request rate": {"tokenplace_http_requests_total"},
        "token.place HTTP 5xx ratio": {"tokenplace_http_requests_total"},
        "token.place HTTP latency percentiles": {"tokenplace_http_request_duration_seconds_bucket"},
        "token.place build identity": {"tokenplace_build_info"},
    }
    for title, intended in expected_metrics.items():
        panel_expressions = [target["expr"] for target in token_panels_by_title[title]["targets"]]
        found = set()
        for expression in panel_expressions:
            selectors = list(
                re.finditer(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\s*\{([^{}]*)\}", expression)
            )
            consumed_selector_ends = []
            for selector in selectors:
                metric, matchers = selector.groups()
                found.add(metric)
                try:
                    parsed_matchers = parse_tokenplace_matchers(matchers)
                except ValueError:
                    parsed_matchers = None
                allowed_matchers = dict(TOKENPLACE_CANONICAL_MATCHERS)
                if title == "token.place HTTP 5xx ratio":
                    allowed_matchers["status_class"] = ("=", '"5xx"')
                if (
                    metric not in intended
                    or parsed_matchers is None
                    or any(
                        parsed_matchers.get(key) != value
                        for key, value in TOKENPLACE_CANONICAL_MATCHERS.items()
                    )
                    or any(key not in allowed_matchers for key in parsed_matchers)
                    or any(allowed_matchers[key] != value for key, value in parsed_matchers.items())
                ):
                    raise SystemExit(
                        f"ERROR: {title} must use only its intended metric family "
                        "with the canonical target selector."
                    )
                suffix = expression[selector.end() :]
                range_match = re.match(r"\[\$__rate_interval\]", suffix)
                if metric in TOKENPLACE_RATE_METRICS:
                    if not range_match or not re.search(
                        r"\brate\s*\(\s*$", expression[: selector.start()]
                    ):
                        raise SystemExit(
                            f"ERROR: {title} rate ranges must be attached to a metric "
                            "selector directly inside rate()."
                        )
                    consumed_selector_ends.append(selector.end() + range_match.end())
                else:
                    if range_match:
                        raise SystemExit(
                            f"ERROR: {title} has a range outside an intended rate expression."
                        )
                    consumed_selector_ends.append(selector.end())
            without_selectors = "".join(
                expression[end:start]
                for (end, start) in zip(
                    [0, *consumed_selector_ends],
                    [*(selector.start() for selector in selectors), len(expression)],
                )
            )
            selector_free = re.sub(r'"(?:\\.|[^"\\])*"', "", without_selectors)
            if re.search(
                r"\$(?:[a-zA-Z_][a-zA-Z0-9_]*|\{[a-zA-Z_][a-zA-Z0-9_]*\})",
                selector_free,
            ):
                raise SystemExit(
                    f"ERROR: {title} contains a template variable outside its permitted "
                    "canonical selector or rate range."
                )
            if "[" in selector_free or "]" in selector_free:
                raise SystemExit(f"ERROR: {title} contains an invalid range expression.")
            selector_free = re.sub(
                r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)",
                "",
                selector_free,
            )
            selector_free = re.sub(
                rf"\b(?:{'|'.join(TOKENPLACE_PROMQL_FUNCTIONS)})\s*(?=\()",
                "",
                selector_free,
            )
            selector_free = re.sub(
                rf"\b(?:{'|'.join(TOKENPLACE_PROMQL_MODIFIERS)})\b",
                "",
                selector_free,
            )
            selector_free = re.sub(
                r"(?<![a-zA-Z_:])(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?",
                "",
                selector_free,
                flags=re.IGNORECASE,
            )
            if re.search(r"\b[a-zA-Z_:][a-zA-Z0-9_:]*\b", selector_free):
                raise SystemExit(
                    f"ERROR: {title} contains a bare or unverified metric selector; "
                    "the canonical target selector is required."
                )
        if found != intended:
            raise SystemExit(f"ERROR: {title} must use its intended metric family.")

    for title in (
        "token.place scrape availability",
        "token.place instrumentation health",
    ):
        panel = token_panels_by_title[title]
        target = panel["targets"][0]
        mappings = panel.get("fieldConfig", {}).get("defaults", {}).get("mappings", [])
        mapping_options = mappings[0].get("options", {}) if len(mappings) == 1 else {}
        if (
            target.get("instant") is not True
            or target.get("range") is not False
            or mapping_options.get("0", {}).get("text") != "UNHEALTHY"
            or mapping_options.get("1", {}).get("text") != "HEALTHY"
            or panel.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA"
        ):
            raise SystemExit(
                "ERROR: token.place health stats must be instant-only and distinguish "
                "healthy, unhealthy, and NO DATA."
            )

    logical = {
        "tokenplace_compute_nodes_registered",
        "tokenplace_compute_nodes_healthy",
        "tokenplace_compute_node_lease_age_seconds",
        "tokenplace_relay_queue_depth",
        "tokenplace_relay_oldest_queued_request_age_seconds",
    }
    for metric in logical:
        matching = [expression for expression in expressions if metric in expression]
        if not matching or any(
            not re.search(rf"\bmax(?:\s+by\s*\([^)]*\))?\s*\([^)]*{metric}", expression)
            for expression in matching
        ):
            raise SystemExit(f"ERROR: logical gauge {metric} must use explicit max deduplication.")

    direct_max = {
        "tokenplace_compute_nodes_registered",
        "tokenplace_compute_nodes_healthy",
        "tokenplace_compute_node_lease_age_seconds",
    }
    for metric in direct_max:
        expression = next(expr for expr in expressions if metric in expr)
        if not re.match(rf"^max\s*\(\s*{metric}\{{", expression):
            raise SystemExit(f"ERROR: logical gauge {metric} must use direct max deduplication.")

    grouped_gauges = {
        "token.place relay queue depth": ("tokenplace_relay_queue_depth", "provider_mode"),
        "token.place oldest queued-request age": (
            "tokenplace_relay_oldest_queued_request_age_seconds",
            "provider_mode",
        ),
        "token.place in-flight requests by pod": (
            "tokenplace_relay_in_flight_requests",
            "pod",
        ),
        "token.place oldest in-flight age by pod": (
            "tokenplace_relay_oldest_in_flight_age_seconds",
            "pod",
        ),
    }
    for title, (metric, label) in grouped_gauges.items():
        target = token_panels_by_title[title]["targets"][0]
        if not re.match(rf"^max\s+by\s*\(\s*{label}\s*\)\s*\(\s*{metric}\{{", target["expr"]):
            qualifier = "remain per pod and " if label == "pod" else ""
            raise SystemExit(f"ERROR: {title} must {qualifier}use max by ({label}).")
        if target.get("legendFormat") != f"{{{{{label}}}}}":
            raise SystemExit(f"ERROR: {title} must use a {label} legend.")

    counters = {
        "tokenplace_compute_node_evictions_total": "reason",
        "tokenplace_relay_request_outcomes_total": "outcome",
        "tokenplace_http_requests_total": None,
    }
    for metric, bounded_group in counters.items():
        matching = [expression for expression in expressions if metric in expression]
        if not matching or any(
            "sum" not in expression
            or f"rate({metric}" not in expression
            or "[$__rate_interval]" not in expression
            for expression in matching
        ):
            raise SystemExit(f"ERROR: process-local counter {metric} must use a summed rate.")
        if bounded_group and any(
            f"sum by ({bounded_group})" not in expression for expression in matching
        ):
            raise SystemExit(f"ERROR: {metric} must remain grouped by bounded {bounded_group}.")

    direct_counter_groups = {
        "tokenplace_compute_node_evictions_total": "reason",
        "tokenplace_relay_request_outcomes_total": "outcome",
    }
    for metric, label in direct_counter_groups.items():
        expression = next(expr for expr in expressions if metric in expr)
        pattern = (
            rf"^sum\s+by\s*\(\s*{label}\s*\)\s*\(\s*rate\s*\(\s*"
            rf"{metric}\{{.*\}}\[\$__rate_interval\]\s*\)\s*\)\s*$"
        )
        if not re.match(pattern, expression):
            raise SystemExit(f"ERROR: {metric} must directly use sum by ({label}) of rate.")

    request_rate = token_panels_by_title["token.place HTTP request rate"]["targets"][0]["expr"]
    if not re.match(
        r"^sum\s+by\s*\(\s*route\s*,\s*status_class\s*\)\s*\(\s*rate\s*\(\s*"
        r"tokenplace_http_requests_total\{.*\}\[\$__rate_interval\]\s*\)\s*\)\s*$",
        request_rate,
    ):
        raise SystemExit(
            "ERROR: token.place HTTP request rate must group by route and status_class."
        )

    ratio = token_panels_by_title["token.place HTTP 5xx ratio"]["targets"][0]["expr"]
    numerator, separator, denominator = ratio.partition(" / ")
    if (
        not separator
        or 'status_class="5xx"' not in numerator
        or re.search(r"status_class\s*(?:=|=~|!=|!~)", denominator)
        or not re.match(r"^clamp_min\s*\(\s*sum\s*\(\s*rate\s*\(", denominator)
        or not re.search(r"\)\s*,\s*1e-9\s*\)\s*$", denominator)
    ):
        raise SystemExit(
            "ERROR: token.place HTTP 5xx ratio must select 5xx and use an unfiltered "
            "clamp_min denominator."
        )

    for title in (
        "token.place in-flight requests by pod",
        "token.place oldest in-flight age by pod",
    ):
        target = panel_named(dashboard, title).get("targets", [{}])[0]
        if "by (pod)" not in target.get("expr", "") or "{{pod}}" not in target.get(
            "legendFormat", ""
        ):
            raise SystemExit("ERROR: token.place in-flight gauges must remain visible per pod.")
    build = panel_named(dashboard, "token.place build identity")
    build_target = build.get("targets", [{}])[0]
    if (
        "max by (pod, version, revision)" not in build_target.get("expr", "")
        or build_target.get("legendFormat") != "{{pod}} {{version}} {{revision}}"
        or build_target.get("instant") is not True
        or build_target.get("range") is not False
    ):
        raise SystemExit(
            "ERROR: token.place build identity must remain per pod, version, and revision."
        )
    latency = panel_named(dashboard, "token.place HTTP latency percentiles")
    if {target.get("legendFormat", "").split(" ", 1)[0] for target in latency["targets"]} != {
        "p50",
        "p95",
        "p99",
    } or any(
        "histogram_quantile(" not in target.get("expr", "")
        or "sum by (le, route)" not in target.get("expr", "")
        or "rate(tokenplace_http_request_duration_seconds_bucket" not in target.get("expr", "")
        for target in latency.get("targets", [])
    ):
        raise SystemExit(
            "ERROR: token.place latency must use histogram bucket rates and bounded grouping."
        )
    if any(
        panel.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA"
        for panel in token_panels
    ):
        raise SystemExit("ERROR: token.place panels must display missing series as NO DATA.")

    token_serialized = json.dumps(token_panels)
    expression_text = "\n".join(expressions)
    used_labels = set(
        re.findall(r"(?:\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|=~|!=|!~)", expression_text)
    )
    for labels in re.findall(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\(([^)]*)\)",
        expression_text,
    ):
        used_labels.update(label.strip() for label in labels.split(",") if label.strip())
    used_labels.update(re.findall(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}", token_serialized))
    if not used_labels <= TOKENPLACE_LABELS:
        raise SystemExit("ERROR: token.place queries or legends contain an unsafe label.")
    if any(metric in token_serialized for metric in PHASE_TWO_METRICS):
        raise SystemExit("ERROR: token.place Phase 2 metrics must not be presented as implemented.")


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
    positions = []
    for panel in panels(dashboard):
        position = panel.get("gridPos", {})
        if (
            any(not isinstance(position.get(key), int) for key in ("x", "y", "w", "h"))
            or position.get("x", -1) < 0
            or position.get("y", -1) < 0
            or position.get("w", 0) <= 0
            or position.get("h", 0) <= 0
            or position.get("x", 0) + position.get("w", 0) > 24
        ):
            raise SystemExit("ERROR: dashboard panels must have valid integer grid positions.")
        if panel.get("type") == "row":
            continue
        rectangle = (
            position["x"],
            position["y"],
            position["x"] + position["w"],
            position["y"] + position["h"],
        )
        if any(
            rectangle[0] < other[2]
            and rectangle[2] > other[0]
            and rectangle[1] < other[3]
            and rectangle[3] > other[1]
            for other in positions
        ):
            raise SystemExit("ERROR: dashboard panel grid positions must not overlap.")
        positions.append(rectangle)
    validate_dashboard_semantics(dashboard)
    validate_tokenplace_semantics(dashboard)
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
    urls = set(re.findall(r"https?://[^)\\\" ]+", serialized, re.IGNORECASE))
    approved_urls = {
        "https://github.com/futuroptimist/sugarkube/blob/main/docs/"
        "observability-dspace-release-integrity.md",
        "https://github.com/futuroptimist/sugarkube/blob/main/deployment-evidence/"
        "dspace/staging/main-018687f-20260805T035722Z.json",
    }
    if urls != approved_urls:
        raise SystemExit(
            "ERROR: dashboard raw URLs must be the exact reviewed runbook/evidence allowlist."
        )
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
