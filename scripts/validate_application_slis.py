#!/usr/bin/env python3
"""Validate the bounded, non-objective application SLI inventory."""

import json
import re
import sys
from pathlib import Path

ALLOWED_TYPES = {"http_probe_health", "synthetic_completion", "actual_request_success"}
REQUIRED = {
    "id", "application", "userJourney", "signalType", "dataSource", "numerator",
    "denominator", "exclusions", "observationWindow", "objective",
}
WINDOW = re.compile(r"^[1-9][0-9]*[mhd]$")


def validate(document: object) -> int:
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "retention", "slis"}:
        raise ValueError("contract must contain only schemaVersion, retention, and slis")
    if document["schemaVersion"] != 1 or document["retention"] != "90d":
        raise ValueError("unsupported schema or retention window")
    slis = document["slis"]
    if not isinstance(slis, list) or not slis:
        raise ValueError("slis must be a nonempty list")
    ids = set()
    for sli in slis:
        if not isinstance(sli, dict) or set(sli) != REQUIRED:
            raise ValueError("each SLI must use the exact bounded schema")
        if sli["id"] in ids or not re.fullmatch(r"[a-z0-9-]+", sli["id"]):
            raise ValueError("SLI ids must be unique and bounded")
        ids.add(sli["id"])
        if sli["signalType"] not in ALLOWED_TYPES:
            raise ValueError("unsupported signal type")
        if sli["objective"] is not None:
            raise ValueError("numerical objectives require a separately reviewed repository contract")
        if not WINDOW.fullmatch(sli["observationWindow"]):
            raise ValueError("unsupported observation window")
        if not isinstance(sli["exclusions"], list) or not sli["exclusions"]:
            raise ValueError("exclusions must be a nonempty list")
        joined = " ".join(str(sli[k]) for k in ("dataSource", "numerator", "denominator"))
        if sli["signalType"] == "actual_request_success" and "probe_success" in joined:
            raise ValueError("a probe cannot substitute for actual request success")
        if "or vector(0)" in joined or "or on() vector(0)" in joined:
            raise ValueError("unconditional zero fallback hides absent telemetry")
    return len(slis)


def main(argv=None) -> int:
    path = Path((argv or sys.argv[1:])[0])
    try:
        count = validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"validated {count} application SLIs (all objectives unmeasured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
