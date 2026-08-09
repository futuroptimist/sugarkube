#!/usr/bin/env python3
"""Fail-closed validation for canonical Sugarkube Grafana dashboards and Helm renders."""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_observability_dashboards import (
    PROFILES,
    render_dashboard,
    serialized_dashboard,
)

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
FORBIDDEN_IDENTITY = re.compile(
    r"{{\s*(instance|address|endpoint|url|device|uuid|system_uuid|provider_id|pod_cidr)\s*}}",
    re.IGNORECASE,
)

TITLE = ""
UID = ""
DASHBOARD_FILE = ""
DASHBOARD_MOUNT = ""


def panels(dashboard: dict):
    """Yield every top-level or nested panel."""
    for panel in dashboard.get("panels", []):
        if isinstance(panel, dict):
            yield panel
            yield from panels(panel)


def panel_named(dashboard: dict, title: str) -> dict:
    matching = [panel for panel in panels(dashboard) if panel.get("title") == title]
    if len(matching) != 1:
        raise SystemExit(f"ERROR: dashboard must contain exactly one {title!r} panel.")
    return matching[0]


def configure_profile(dashboard: dict) -> str:
    """Select a supported identity and configure its rendered-file contract."""
    global TITLE, UID, DASHBOARD_FILE, DASHBOARD_MOUNT
    for name, profile in PROFILES.items():
        if (dashboard.get("uid"), dashboard.get("title")) == (
            profile["uid"],
            profile["title"],
        ):
            UID, TITLE = profile["uid"], profile["title"]
            DASHBOARD_FILE = f"{UID}.json"
            DASHBOARD_MOUNT = f"{DASHBOARD_PATH}/{DASHBOARD_FILE}"
            return name
    raise SystemExit("ERROR: dashboard title and UID do not match a supported profile.")


def _validate_grid(panel_list: list) -> None:
    ids = [panel.get("id") for panel in panel_list]
    if ids != list(range(1, 61)):
        raise SystemExit("ERROR: canonical panel IDs must be the stable integer sequence 1..60.")
    occupied = set()
    for panel in panel_list:
        grid = panel.get("gridPos", {})
        if set(grid) != {"x", "y", "w", "h"} or not all(
            isinstance(grid[key], int) for key in ("x", "y", "w", "h")
        ):
            raise SystemExit("ERROR: dashboard panels must have complete integer grid positions.")
        if grid["x"] < 0 or grid["y"] < 0 or grid["w"] <= 0 or grid["h"] <= 0:
            raise SystemExit("ERROR: dashboard panel grid positions must be positive and bounded.")
        cells = {
            (x, y)
            for x in range(grid["x"], grid["x"] + grid["w"])
            for y in range(grid["y"], grid["y"] + grid["h"])
        }
        if occupied & cells:
            raise SystemExit("ERROR: dashboard panel grid positions must not overlap.")
        occupied |= cells


def _validate_tables(dashboard: dict) -> None:
    tables = [panel for panel in panels(dashboard) if panel.get("type") == "table"]
    if len(tables) != 10:
        raise SystemExit("ERROR: canonical dashboard must contain exactly ten tables.")
    for panel in tables:
        targets = panel.get("targets", [])
        if len(targets) != 1:
            raise SystemExit(f"ERROR: {panel['title']} must use one simultaneous table frame.")
        target = targets[0]
        if (
            target.get("format") != "table"
            or target.get("instant") is not True
            or target.get("range") is not False
        ):
            raise SystemExit(f"ERROR: {panel['title']} must use an instant-only table target.")
        transformations = panel.get("transformations", [])
        if len(transformations) != 1 or transformations[0].get("id") != "organize":
            raise SystemExit(f"ERROR: {panel['title']} must use one organize transformation.")
        options = transformations[0].get("options", {})
        if not isinstance(options.get("indexByName"), dict) or not isinstance(
            options.get("renameByName"), dict
        ):
            raise SystemExit(f"ERROR: {panel['title']} must explicitly order and rename columns.")
        excluded = options.get("excludeByName", {})
        if not all(excluded.get(name) is True for name in ("Time", "__name__")):
            raise SystemExit(f"ERROR: {panel['title']} must hide Time and __name__ fields.")
        if "Value" not in options["indexByName"] and excluded.get("Value") is not True:
            raise SystemExit(f"ERROR: {panel['title']} must explicitly order or hide Value.")


def _validate_variables(dashboard: dict, profile_name: str) -> None:
    variables = dashboard.get("templating", {}).get("list", [])
    if [item.get("name") for item in variables] != ["environment", "cluster", "app", "route"]:
        raise SystemExit(
            "ERROR: dashboard variables must have canonical environment/cluster/app/route shape."
        )
    profile = PROFILES[profile_name]
    for variable, expected in zip(variables[:2], (profile["environment"], profile["cluster"])):
        if variable.get("type") != "constant" or variable.get("hide") != 2:
            raise SystemExit("ERROR: environment and cluster must be hidden constants.")
        if variable.get("query") != expected or variable.get("current") != {
            "text": expected,
            "value": expected,
        }:
            raise SystemExit("ERROR: hidden profile variables contain the wrong single value.")
    for variable in variables[2:]:
        if variable.get("type") != "query" or variable.get("includeAll") is not True:
            raise SystemExit(
                "ERROR: app and route must be visible query variables with All enabled."
            )
        if variable.get("allValue") != ".*":
            raise SystemExit("ERROR: app and route All values must expand to .*.")


def _validate_semantics(dashboard: dict) -> None:
    panel_list = list(panels(dashboard))
    if len(panel_list) != 60 or sum(panel.get("type") == "row" for panel in panel_list) != 11:
        raise SystemExit(
            "ERROR: canonical dashboard must contain 60 objects: 11 rows and 49 panels."
        )
    rows = [panel.get("title") for panel in panel_list if panel.get("type") == "row"]
    if rows != ROW_TITLES:
        raise SystemExit("ERROR: canonical dashboard row order changed.")
    _validate_grid(panel_list)
    _validate_tables(dashboard)
    if dashboard.get("schemaVersion") != 41 or dashboard.get("timezone") != "browser":
        raise SystemExit("ERROR: dashboard schema version or timezone changed.")
    if dashboard.get("editable") is not False or dashboard.get("refresh") != "30s":
        raise SystemExit("ERROR: dashboard immutability or refresh defaults changed.")
    if dashboard.get("time") != {"from": "now-6h", "to": "now"}:
        raise SystemExit("ERROR: dashboard default time range changed.")
    data_panels = [panel for panel in panel_list if panel.get("type") not in {"row", "text"}]
    if any(
        panel.get("fieldConfig", {}).get("defaults", {}).get("noValue") != "NO DATA"
        for panel in data_panels
    ):
        raise SystemExit(
            "ERROR: every data panel must explicitly display absent telemetry as NO DATA."
        )
    serialized = json.dumps(dashboard)
    expressions = "\n".join(
        target.get("expr", "")
        for panel in data_panels
        for target in panel.get("targets", [])
        if isinstance(target.get("expr"), str)
    )
    zero_fallback_panels = [
        panel.get("title")
        for panel in data_panels
        for target in panel.get("targets", [])
        if "or vector(0)" in target.get("expr", "") or "or on() vector(0)" in target.get("expr", "")
    ]
    if zero_fallback_panels != ["Public availability summary"]:
        raise SystemExit("ERROR: only retention-backed probe presence may use vector(0).")
    for title in ("dChat request activity", "token.place dependency request activity"):
        expression = panel_named(dashboard, title)["targets"][0]["expr"]
        if "dspace_instrumentation_up" not in expression or "0 *" not in expression:
            raise SystemExit("ERROR: event-rate zeroes must be instrumentation-gated.")
    for title in (
        "Image-pin agreement",
        "DSPACE metrics-target health",
        "/chat synthetic result and freshness",
    ):
        expressions_for_panel = " ".join(
            target.get("expr", "") for target in panel_named(dashboard, title).get("targets", [])
        )
        if (
            "0 *" in expressions_for_panel
            and "dspace_release_approved_info" not in expressions_for_panel
        ):
            raise SystemExit(
                "ERROR: DSPACE failure zeroes must be approved-release capability-gated."
            )
    image_pin = panel_named(dashboard, "Image-pin agreement")["targets"][0]["expr"]
    if '"image", "(.*)"' not in image_pin or '"image_digest", "(.*)"' not in image_pin:
        raise SystemExit("ERROR: image-pin agreement must join approved image and digest labels.")
    blackbox = " ".join(
        target.get("expr", "")
        for title in (
            "Public availability summary",
            "Endpoint matrix",
            "Probe duration",
            "HTTP response status",
            "TLS certificate lifetime",
        )
        for target in panel_named(dashboard, title).get("targets", [])
    )
    if "-$environment-.*" not in blackbox or "-staging-.*" in blackbox:
        raise SystemExit("ERROR: blackbox jobs must be selected through $environment.")
    tokenplace = " ".join(
        target.get("expr", "")
        for panel in data_panels
        if panel.get("title", "").startswith("token.place")
        for target in panel.get("targets", [])
    )
    for matcher in (
        'app="tokenplace"',
        'environment=~"$environment"',
        'release="tokenplace"',
        'cluster=~"$cluster"',
        'namespace="tokenplace"',
    ):
        if matcher not in tokenplace:
            raise SystemExit("ERROR: token.place queries must retain bounded profile matchers.")
    core_titles = {
        "Scrape availability by job",
        "Ready nodes",
        "Node readiness",
        "Deployment replica deficit",
        "Unready pods by namespace",
        "Problem pods by namespace",
        "Container restart rate",
        "Node CPU utilization",
        "Node memory utilization",
        "Root filesystem utilization",
        "Prometheus PVC utilization",
        "Prometheus active series",
        "Observability component build identity",
    }
    core = " ".join(
        target.get("expr", "")
        for panel in data_panels
        if panel.get("title") in core_titles
        for target in panel.get("targets", [])
    )
    if re.search(r"cluster\s*(?:=|=~)", core):
        raise SystemExit("ERROR: local core queries must not require external cluster labels.")
    if "kube_state_metrics_build_info" in serialized:
        raise SystemExit("ERROR: unavailable kube-state-metrics build identity is forbidden.")
    if FORBIDDEN_IDENTITY.search(serialized):
        raise SystemExit("ERROR: dashboard legends expose a forbidden raw identity label.")
    if any(
        name in serialized
        for name in (
            "tokenplace_chat_availability",
            "tokenplace_compute_nodes_schedulable",
            "tokenplace_shared_state_health",
        )
    ):
        raise SystemExit("ERROR: token.place Phase 2 metrics must remain absent.")
    datasource_uids = set(re.findall(r'"uid":\s*"([^"]+)"', serialized))
    if (
        not datasource_uids <= {DATASOURCE_UID, dashboard["uid"]}
        or DATASOURCE_UID not in datasource_uids
    ):
        raise SystemExit("ERROR: dashboard datasource references must use Prometheus UID.")


def validate_dashboard(path: Path) -> str:
    """Validate identity, canonical bytes, shared layout, and semantic safety."""
    try:
        raw = path.read_text(encoding="utf-8")
        dashboard = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: dashboard JSON is missing or malformed: {error}") from error
    if not isinstance(dashboard, dict):
        raise SystemExit("ERROR: dashboard JSON root must be an object.")
    profile_name = configure_profile(dashboard)
    expected = serialized_dashboard(profile_name)
    if raw != expected:
        raise SystemExit("ERROR: dashboard differs from its canonical generated profile.")
    _validate_variables(dashboard, profile_name)
    _validate_semantics(dashboard)
    other_name = "prod" if profile_name == "staging" else "staging"
    other_path = PROFILES[other_name]["path"]
    try:
        other = json.loads(other_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"ERROR: peer generated dashboard is missing or malformed: {error}"
        ) from error
    if dashboard.get("panels") != other.get("panels"):
        raise SystemExit("ERROR: staging and production panel arrays must be identical.")
    return raw


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dashboard", type=Path)
    parser.add_argument("--rendered", type=Path, help="also validate a rendered Helm manifest")
    args = parser.parse_args()
    dashboard_json = validate_dashboard(args.dashboard)
    if args.rendered:
        validate_render(args.rendered, dashboard_json)


if __name__ == "__main__":
    main()
