#!/usr/bin/env python3
"""Generate environment dashboards from the canonical observability template."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "platform/observability/dashboards/sugarkube-observability.template.json"
PROFILES = {
    "staging": {
        "UID": "sugarkube-staging-observability",
        "TITLE": "Sugarkube Staging Observability",
        "ENVIRONMENT": "staging",
        "CLUSTER": "sugarkube-int",
        "path": ROOT
        / "clusters/staging/observability/dashboards/sugarkube-staging-observability.json",
    },
    "prod": {
        "UID": "sugarkube-prod-observability",
        "TITLE": "Sugarkube Production Observability",
        "ENVIRONMENT": "prod",
        "CLUSTER": "sugarkube-prod",
        "path": ROOT / "clusters/prod/observability/dashboards/sugarkube-prod-observability.json",
    },
}


def render(profile: dict[str, object]) -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    for name in ("UID", "TITLE", "ENVIRONMENT", "CLUSTER"):
        source = source.replace("${" + name + "}", str(profile[name]))
    document = json.loads(source)
    return json.dumps(document, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, profile in PROFILES.items():
        expected = render(profile)
        path = profile["path"]
        if args.write:
            path.write_text(expected, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
        elif not path.is_file() or path.read_bytes() != expected.encode():
            stale.append(name)
    if stale:
        print("ERROR: stale generated dashboard(s): " + ", ".join(stale), file=sys.stderr)
        return 1
    if args.check:
        print("generated observability dashboards are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
