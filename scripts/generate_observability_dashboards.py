#!/usr/bin/env python3
"""Generate the staging and production Grafana dashboards from one specification."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION = ROOT / "platform/observability/dashboards/sugarkube-observability.json"
PROFILES = {
    "staging": {
        "uid": "sugarkube-staging-observability",
        "title": "Sugarkube Staging Observability",
        "environment": "staging",
        "cluster": "sugarkube-int",
    },
    "prod": {
        "uid": "sugarkube-prod-observability",
        "title": "Sugarkube Production Observability",
        "environment": "prod",
        "cluster": "sugarkube-prod",
    },
}


def output_path(profile: str) -> Path:
    uid = PROFILES[profile]["uid"]
    return ROOT / "clusters" / profile / "observability/dashboards" / f"{uid}.json"


def generate(profile: str) -> dict:
    """Return a dashboard with only the approved identity substitutions applied."""
    dashboard = deepcopy(json.loads(SPECIFICATION.read_text(encoding="utf-8")))
    values = {key.upper(): value for key, value in PROFILES[profile].items()}

    def substitute(value):
        if isinstance(value, str):
            for key, replacement in values.items():
                value = value.replace("${" + key + "}", replacement)
            return value
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value

    return substitute(dashboard)


def encoded(profile: str) -> str:
    return json.dumps(generate(profile), indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="replace generated dashboard files")
    mode.add_argument("--check", action="store_true", help="fail when generated files are stale")
    args = parser.parse_args()
    stale = []
    for profile in PROFILES:
        path = output_path(profile)
        expected = encoded(profile)
        if args.write:
            path.write_text(expected, encoding="utf-8")
        elif not path.exists() or path.read_bytes() != expected.encode():
            stale.append(path.relative_to(ROOT))
    if stale:
        print("ERROR: stale generated dashboard(s): " + ", ".join(map(str, stale)), file=sys.stderr)
        print("Run: python3 scripts/generate_observability_dashboards.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
