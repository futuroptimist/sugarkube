#!/usr/bin/env python3
"""Validate the bounded, non-alerting application SLI inventory."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config/observability/application-slis.json"
FIELDS = {
    "id", "application", "userJourney", "signalType", "dataSource", "numerator",
    "denominator", "exclusions", "observationWindow", "objective", "measurementState",
}
SIGNALS = {"http_probe_health", "synthetic_completion", "actual_request_success"}
UNITS = {"m": 60, "h": 3600, "d": 86400}


class ContractError(ValueError):
    """The SLI contract is unsafe or ambiguous."""


def seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([mhd])", value) if isinstance(value, str) else None
    if not match:
        raise ContractError("observation and retention windows must be positive m/h/d durations")
    return int(match.group(1)) * UNITS[match.group(2)]


def validate(contract: object) -> int:
    if not isinstance(contract, dict) or set(contract) != {"schemaVersion", "retention", "slis"}:
        raise ContractError("contract must have the exact top-level schema")
    if contract["schemaVersion"] != 1 or not isinstance(contract["slis"], list):
        raise ContractError("unsupported schema version or SLI list")
    retention = seconds(contract["retention"])
    if retention > seconds("90d"):
        raise ContractError("retention exceeds the supported Prometheus history")
    ids = set()
    for sli in contract["slis"]:
        if not isinstance(sli, dict) or set(sli) != FIELDS:
            raise ContractError("every SLI must contain the exact documented fields")
        if sli["id"] in ids:
            raise ContractError("SLI ids must be unique")
        ids.add(sli["id"])
        if sli["signalType"] not in SIGNALS:
            raise ContractError("unsupported signal type")
        if seconds(sli["observationWindow"]) > retention:
            raise ContractError("observation window exceeds supported retention")
        if sli["objective"] is not None or sli["measurementState"] != "unmeasured":
            raise ContractError("an unreviewed numerical objective must remain unmeasured")
        expression = f'{sli["numerator"]} {sli["denominator"]}'
        if "or vector(0)" in expression or re.search(r"\bor\s+(?:on\(\)\s+)?vector\(0\)", expression):
            raise ContractError("unconditional zero fallback hides missing telemetry")
        if sli["signalType"] == "actual_request_success" and "probe_success" in expression:
            raise ContractError("a probe cannot substitute for actual request success")
        if sli["signalType"] == "http_probe_health" and sli["dataSource"] != "probe_success":
            raise ContractError("HTTP probe health must use the existing probe signal")
        if not sli["exclusions"] or not all(isinstance(item, str) for item in sli["exclusions"]):
            raise ContractError("exclusions must be a nonempty string list")
    required = {"dspace", "tokenplace", "danielsmith"}
    covered = {app for sli in contract["slis"] for app in sli["application"].split(",")}
    if not required <= covered or SIGNALS != {sli["signalType"] for sli in contract["slis"]}:
        raise ContractError("all applications and distinct signal types must be represented")
    return len(ids)


def classify_request_window(*, eligible, failed, telemetry, complete, reset=False) -> str:
    """Reference semantics used by focused tests and mirrored by recording rules."""
    if telemetry == "disabled":
        return "disabled"
    if telemetry != "fresh":
        return "missing_or_stale_telemetry"
    if reset or not complete:
        return "reset_or_incomplete_history"
    if eligible == 0:
        return "no_eligible_traffic"
    return "failed_eligible_traffic" if failed else "successful_eligible_traffic"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", nargs="?", type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        print(f"validated {validate(json.loads(args.contract.read_text()))} application SLIs")
    except (OSError, json.JSONDecodeError, ContractError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
