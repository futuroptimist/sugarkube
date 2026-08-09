#!/usr/bin/env python3
"""Fail-closed validation for generated Sugarkube Grafana dashboards and Helm renders."""

import argparse
import json
import re
from pathlib import Path

from generate_observability_dashboards import PROFILES, encoded, generate, output_path

ROOT = Path(__file__).resolve().parents[1]
DATASOURCE_UID = "prometheus"
DASHBOARD_PATH = "/var/lib/grafana/dashboards/sugarkube"
ROW_TITLES = [
    "Cluster and service health",
    "Workload health",
    "Node and Prometheus capacity",
    "Observability build identity",
    "DSPACE HTTP",
    "DSPACE runtime and release",
    "DSPACE feature traffic",
    "Blackbox monitoring",
    "DSPACE release integrity",
    "token.place relay and compute capacity",
    "token.place HTTP and release",
]
FORBIDDEN_LABELS = re.compile(
    r"{{\s*(instance|address|endpoint|url|device|uuid|system_uuid|provider_id|pod_cidr)\s*}}",
    re.IGNORECASE,
)
TABLE_COLUMNS = {
    "Scrape availability by job",
    "Node readiness",
    "Deployment replica deficit",
    "Observability component build identity",
    "DSPACE build identity",
    "Endpoint matrix",
    "HTTP response status",
    "Approved revision",
    "Active build revisions by pod",
    "token.place build identity",
}
CAPABILITY = 'dspace_release_approved_info{environment=~"$environment"}'


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"dashboard JSON is missing or malformed: {error}")
    if not isinstance(value, dict):
        fail("dashboard JSON root must be an object")
    return value, raw


def profile_for(dashboard: dict) -> str:
    identity = (dashboard.get("uid"), dashboard.get("title"))
    for profile, values in PROFILES.items():
        if identity == (values["uid"], values["title"]):
            return profile
    fail("dashboard title and UID do not match a supported profile")


def expressions(dashboard: dict) -> list[str]:
    return [
        target.get("expr", "")
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]


def validate_semantics(dashboard: dict) -> None:
    panels = dashboard.get("panels")
    if not isinstance(panels, list) or len(panels) != 60:
        fail("canonical dashboard must contain exactly 60 objects")
    if sum(panel.get("type") == "row" for panel in panels) != 11:
        fail("canonical dashboard must contain 11 rows and 49 data/content objects")
    if [panel["title"] for panel in panels if panel.get("type") == "row"] != ROW_TITLES:
        fail("canonical row order changed")
    ids = [panel.get("id") for panel in panels]
    if ids != list(range(1, 61)):
        fail("panel IDs must be stable consecutive integers")
    occupied = set()
    for panel in panels:
        grid = panel.get("gridPos", {})
        if not all(isinstance(grid.get(key), int) for key in ("x", "y", "w", "h")):
            fail("every object requires an integer grid position")
        cells = {
            (x, y)
            for x in range(grid["x"], grid["x"] + grid["w"])
            for y in range(grid["y"], grid["y"] + grid["h"])
        }
        if occupied & cells:
            fail("dashboard objects must not overlap")
        occupied |= cells
        if (
            panel.get("type") not in {"row", "text"}
            and panel.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA"
        ):
            fail(f"{panel.get('title')} must explicitly display NO DATA for absent telemetry")
    actual_tables = {panel["title"] for panel in panels if panel.get("type") == "table"}
    if actual_tables != TABLE_COLUMNS:
        fail("canonical dashboard must retain exactly the ten contracted tables")
    for panel in panels:
        if panel.get("type") != "table":
            continue
        targets = panel.get("targets", [])
        if (
            len(targets) != 1
            or targets[0].get("format") != "table"
            or targets[0].get("instant") is not True
            or targets[0].get("range") is not False
        ):
            fail(f"{panel['title']} must use one table-formatted instant-only target")
        transforms = panel.get("transformations", [])
        if len(transforms) != 1 or transforms[0].get("id") != "organize":
            fail(f"{panel['title']} must use exactly one organize transformation")
        options = transforms[0].get("options", {})
        if not options.get("indexByName") or not options.get("renameByName"):
            fail(f"{panel['title']} must explicitly order and rename visible columns")
        excluded = {key for key, value in options.get("excludeByName", {}).items() if value}
        if not ({"Time", "__name__"} <= excluded or {"Time", "Value", "__name__"} <= excluded):
            fail(f"{panel['title']} must hide raw table fields where applicable")
    variables = dashboard.get("templating", {}).get("list", [])
    if [item.get("name") for item in variables] != ["environment", "cluster", "app", "route"]:
        fail("variable shape must be environment, cluster, app, route")
    for variable in variables[:2]:
        if variable.get("type") != "constant" or variable.get("hide") != 2:
            fail("environment and cluster must be hidden constants")
    for variable in variables[2:]:
        if (
            variable.get("type") != "query"
            or not variable.get("includeAll")
            or variable.get("allValue") != ".*"
        ):
            fail("app and route must be visible query variables with All = .*")
    serialized = json.dumps(dashboard)
    if FORBIDDEN_LABELS.search(serialized):
        fail("dashboard exposes a forbidden raw identity label")
    exprs = expressions(dashboard)
    joined = "\n".join(exprs)
    if "kube_state_metrics_build_info" in joined:
        fail("unavailable kube-state-metrics build identity is forbidden")
    for expr in exprs:
        if (
            "or vector(0)" in expr or "or on() vector(0)" in expr
        ) and "max_over_time(up{" not in expr:
            fail("unconditional healthy-zero fallbacks are forbidden")
    for title in (
        "dChat request activity",
        "token.place dependency request activity",
        "Image-pin agreement",
        "DSPACE metrics-target health",
        "/chat synthetic result and freshness",
    ):
        panel = next(item for item in panels if item["title"] == title)
        if CAPABILITY not in " ".join(
            target.get("expr", "") for target in panel.get("targets", [])
        ):
            fail(f"{title} must gate zero/failure semantics on approved-release capability")
    if "-$environment-.*" not in joined:
        fail("blackbox jobs must be selected through $environment")
    for expr in exprs:
        if "tokenplace_" in expr and (
            'environment=~"$environment"' not in expr or 'cluster=~"$cluster"' not in expr
        ):
            fail("token.place selectors must use the environment and cluster variables")
    core = ("kube_", "node_", "prometheus_", "alertmanager_", "grafana_")
    for expr in exprs:
        if (
            any(metric in expr for metric in core)
            and not any(app in expr for app in ("dspace", "tokenplace"))
            and re.search(r"cluster\s*(?:=|=~)", expr)
        ):
            fail("core local Prometheus queries must not require external cluster labels")


def validate_dashboard(path: Path) -> tuple[str, str]:
    dashboard, raw = load(path)
    profile = profile_for(dashboard)
    expected = encoded(profile)
    if raw.encode() != expected.encode():
        fail("dashboard differs from the canonical generated artifact")
    if (
        dashboard["panels"] != generate("staging")["panels"]
        or dashboard["panels"] != generate("prod")["panels"]
    ):
        fail("staging and production panel arrays must be identical")
    validate_semantics(dashboard)
    counterpart = output_path("prod" if profile == "staging" else "staging")
    if counterpart.exists():
        other, _ = load(counterpart)
        if other.get("panels") != dashboard["panels"]:
            fail("committed staging and production layouts have drifted")
    return profile, raw


def rendered_payload(rendered: str, filename: str) -> str:
    pattern = re.compile(rf"(?m)^\s*{re.escape(filename)}:\s*\|-?\s*$")
    matches = list(pattern.finditer(rendered))
    if len(matches) != 1:
        fail("Helm render must contain exactly one custom dashboard copy")
    following = rendered[matches[0].end() :].splitlines()
    content = []
    indent = None
    for line in following:
        if line.strip() and indent is None:
            indent = len(line) - len(line.lstrip())
        if indent is not None and line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        if indent is not None:
            content.append(line[indent:] if line.strip() else "")
    return "\n".join(content).rstrip() + "\n"


def validate_render(path: Path, profile: str, source: str) -> None:
    try:
        rendered = path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"rendered manifest is unavailable: {error}")
    filename = f'{PROFILES[profile]["uid"]}.json'
    payload = rendered_payload(rendered, filename)
    try:
        json.loads(payload)
    except json.JSONDecodeError as error:
        fail(f"rendered dashboard ConfigMap contains malformed JSON: {error}")
    if payload != source:
        fail("rendered dashboard differs from the version-controlled source")
    mount = f"{DASHBOARD_PATH}/{filename}"
    if rendered.count(mount) != 1 or rendered.count(f"subPath: {filename}") != 1:
        fail("rendered dashboard mount is missing or duplicated")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--rendered", type=Path)
    args = parser.parse_args()
    profile, source = validate_dashboard(args.dashboard)
    if args.rendered:
        validate_render(args.rendered, profile, source)


if __name__ == "__main__":
    main()
