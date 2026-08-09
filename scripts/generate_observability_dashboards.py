#!/usr/bin/env python3
"""Generate the environment-specific Grafana dashboards from one canonical template."""

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "platform/observability/dashboards/observability-dashboard.template.json"
PROFILES = {
    "staging": {
        "uid": "sugarkube-staging-observability",
        "title": "Sugarkube Staging Observability",
        "environment": "staging",
        "cluster": "sugarkube-int",
        "path": ROOT
        / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json",
    },
    "prod": {
        "uid": "sugarkube-prod-observability",
        "title": "Sugarkube Production Observability",
        "environment": "prod",
        "cluster": "sugarkube-prod",
        "path": ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json",
    },
}


def load_template() -> dict:
    """Load the authoritative, environment-neutral dashboard specification."""
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _replace(value, replacements):
    if isinstance(value, str):
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    return value


def render_dashboard(profile_name: str) -> dict:
    """Render a profile without consulting either committed generated artifact."""
    profile = PROFILES[profile_name]
    template = copy.deepcopy(load_template())
    return _replace(
        template,
        {
            "__UID__": profile["uid"],
            "__TITLE__": profile["title"],
            "__ENVIRONMENT__": profile["environment"],
            "__CLUSTER__": profile["cluster"],
        },
    )


def serialized_dashboard(profile_name: str) -> str:
    """Return the canonical byte representation committed to the repository."""
    return json.dumps(render_dashboard(profile_name), indent=2) + "\n"


def write_dashboards() -> None:
    for profile_name, profile in PROFILES.items():
        profile["path"].write_text(serialized_dashboard(profile_name), encoding="utf-8")


def check_dashboards() -> None:
    stale = []
    for profile_name, profile in PROFILES.items():
        try:
            actual = profile["path"].read_text(encoding="utf-8")
        except OSError:
            actual = None
        if actual != serialized_dashboard(profile_name):
            stale.append(str(profile["path"].relative_to(ROOT)))
    if stale:
        paths = "\n  ".join(stale)
        raise SystemExit(
            "ERROR: generated observability dashboard artifacts are stale:\n"
            f"  {paths}\nRun scripts/generate_observability_dashboards.py --write."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write both generated dashboards")
    mode.add_argument("--check", action="store_true", help="byte-check both generated dashboards")
    args = parser.parse_args()
    if args.write:
        write_dashboards()
    else:
        check_dashboards()


if __name__ == "__main__":
    main()
