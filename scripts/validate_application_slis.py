#!/usr/bin/env python3
"""Validate the bounded application SLI contract without interpreting probes as traffic."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "platform/observability/application-slis.json"
REQUIRED = {
    "id",
    "application",
    "userJourney",
    "signalType",
    "dataSource",
    "numerator",
    "denominator",
    "exclusions",
    "observationWindow",
    "monitoring",
    "represents",
}
SIGNAL_TYPES = {"http_probe_health", "synthetic_completion", "actual_request_success"}
MONITORING_STATES = {"configured", "intentionally_disabled"}


def validate_document(document: object) -> None:
    if not isinstance(document, dict) or set(document) != {
        "schemaVersion",
        "retention",
        "objectives",
        "slis",
    }:
        raise ValueError(
            "contract must contain only schemaVersion, retention, objectives, and slis"
        )
    if document["schemaVersion"] != 1:
        raise ValueError("unsupported schemaVersion")
    retention = document["retention"]
    if (
        retention.get("minimumEnvironmentRetention") != "15d"
        or retention.get("maximumContractWindow") != "24h"
    ):
        raise ValueError("unsupported retention window")
    objective = document["objectives"]
    if objective.get("state") != "unmeasured" or objective.get("target") is not None:
        raise ValueError("a numerical objective requires separate reviewed repository evidence")
    if objective.get("budgetOutput") != "NO DATA" or objective.get("burnOutput") != "NO DATA":
        raise ValueError("unmeasured budget and burn outputs must be NO DATA")
    slis = document["slis"]
    if not isinstance(slis, list) or not slis:
        raise ValueError("slis must be a nonempty list")
    ids = set()
    for sli in slis:
        if not isinstance(sli, dict) or set(sli) != REQUIRED:
            raise ValueError("each SLI must contain exactly the required fields")
        if sli["id"] in ids:
            raise ValueError(f"duplicate SLI id: {sli['id']}")
        ids.add(sli["id"])
        if sli["signalType"] not in SIGNAL_TYPES or sli["monitoring"] not in MONITORING_STATES:
            raise ValueError(f"invalid state in {sli['id']}")
        if sli["observationWindow"] != "24h":
            raise ValueError("unsupported retention window")
        source = sli["dataSource"]
        if sli["signalType"] == "actual_request_success" and "probe_success" in source:
            raise ValueError("HTTP probe health cannot substitute for actual request success")
        if "or vector(0)" in source or "unconditional zero" in sli["denominator"].lower():
            raise ValueError("unconditional zero fallback hides missing or no-traffic telemetry")


def classify_counter_window(
    *, denominator: float | None, numerator: float | None, complete: bool, reset: bool
) -> str:
    """Classify a request window; callers must prove continuity independently."""
    if denominator is None or numerator is None:
        return "missing_or_stale_telemetry"
    if reset or not complete:
        return "reset_or_incomplete_history"
    if denominator == 0:
        return "no_eligible_traffic"
    return "successful_eligible_traffic" if numerator == denominator else "failed_eligible_traffic"


def classify_synthetic(
    *, expected: bool, enabled: bool, fresh: bool | None, success: bool | None
) -> str:
    if not expected or not enabled:
        return "intentionally_disabled"
    if fresh is not True or success is None:
        return "missing_or_stale_telemetry"
    return "successful_eligible_traffic" if success else "failed_eligible_traffic"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", nargs="?", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    validate_document(json.loads(args.contract.read_text(encoding="utf-8")))
    print(f"valid application SLI contract: {args.contract}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
