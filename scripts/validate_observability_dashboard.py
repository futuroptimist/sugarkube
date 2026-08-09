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

from scripts.generate_observability_dashboards import PROFILES, render

DATASOURCE_UID = "prometheus"
DASHBOARD_PATH = "/var/lib/grafana/dashboards/sugarkube"
TITLE = ""
UID = ""
DASHBOARD_FILE = ""
DASHBOARD_MOUNT = ""
PROFILE_DIFFERENCES = {"uid", "title", "tags", "templating"}
FORBIDDEN_LABELS = {
    "instance",
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
CAPABILITY = 'dspace_release_approved_info{environment=~"$environment"}'


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
    if len(items) != 60 or sum(panel.get("type") == "row" for panel in items) != 11:
        raise SystemExit("ERROR: canonical dashboard must contain exactly 60 objects and 11 rows.")
    ids = [panel.get("id") for panel in items]
    if ids != list(range(1, 61)):
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
    _validate_grid(items)
    data_panels = [panel for panel in items if panel.get("type") not in {"row", "text"}]
    if any(
        panel.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA"
        for panel in data_panels
    ):
        raise SystemExit("ERROR: every data panel must explicitly preserve NO DATA.")
    tables = [panel for panel in items if panel.get("type") == "table"]
    if len(tables) != 10:
        raise SystemExit("ERROR: canonical dashboard must contain exactly ten tables.")
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
        for variable in variables[2:]
    ):
        raise SystemExit("ERROR: app and route variables must expose All = .*.")
    expressions = [
        target["expr"]
        for panel in items
        for target in panel.get("targets", [])
        if isinstance(target.get("expr"), str)
    ]
    expression_text = "\n".join(expressions)
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
    for metric in EVENT_METRICS:
        matches = [expr for expr in expressions if metric in expr]
        if not matches or any(
            "0 * count(dspace_instrumentation_up" not in expr for expr in matches
        ):
            raise SystemExit(f"ERROR: event-driven metric {metric} requires capability-gated zero.")
    for title in ("Image-pin agreement", "DSPACE metrics-target health"):
        if "0 * count(" + CAPABILITY not in panel_expression(dashboard, title):
            raise SystemExit(f"ERROR: {title} requires an approved-release-gated zero.")
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
