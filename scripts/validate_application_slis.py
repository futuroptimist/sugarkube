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
SOURCES = {
    "http_probe_health": {"probe_success"},
    "synthetic_completion": {
        "dspace_chat_synthetic_success", "danielsmith_visitor_journey_success"
    },
    "actual_request_success": {
        "tokenplace_relay_request_outcomes_total", "dspace_dchat_requests_total"
    },
}
WINDOW = re.compile(r"^([1-9][0-9]*)([mhd])$")


class ContractError(ValueError):
    pass


def minutes(value: str) -> int:
    match = WINDOW.fullmatch(value)
    if not match:
        raise ContractError(f"invalid duration: {value!r}")
    amount, unit = int(match.group(1)), match.group(2)
    return amount * {"m": 1, "h": 60, "d": 1440}[unit]


def validate(document: dict) -> int:
    if set(document) != {"schemaVersion", "retention", "slis"} or document["schemaVersion"] != 1:
        raise ContractError("unsupported top-level SLI contract")
    retention = minutes(document["retention"])
    if retention > 90 * 1440:
        raise ContractError("retention exceeds the repository-supported 90d maximum")
    ids = set()
    for sli in document["slis"]:
        if set(sli) != FIELDS:
            raise ContractError("SLI fields must match the bounded schema")
        if sli["id"] in ids:
            raise ContractError("duplicate SLI id")
        ids.add(sli["id"])
        signal = sli["signalType"]
        if signal not in SIGNALS or sli["dataSource"] not in SOURCES.get(signal, set()):
            raise ContractError("data source cannot substitute one signal type for another")
        if signal == "actual_request_success" and "probe_" in (
            sli["numerator"] + sli["denominator"] + sli["dataSource"]
        ):
            raise ContractError("a probe cannot represent real-request success")
        if sli["objective"] is not None or sli["measurementState"] != "unmeasured":
            raise ContractError("no reviewed numerical objective exists; SLI must be unmeasured")
        if "vector(0)" in sli["numerator"] or "vector(0)" in sli["denominator"]:
            raise ContractError("unconditional zero fallback hides NO DATA")
        if minutes(sli["observationWindow"]) > retention:
            raise ContractError("observation window exceeds supported retention")
        if not sli["exclusions"] or not all(isinstance(item, str) for item in sli["exclusions"]):
            raise ContractError("exclusions must be a non-empty string list")
    if {sli["application"] for sli in document["slis"]} != {
        "token.place", "DSPACE", "danielsmith.io"
    }:
        raise ContractError("contract must cover the three applications")
    return len(ids)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        count = validate(json.loads(args.path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ContractError) as error:
        parser.error(str(error))
    print(f"validated {count} application SLIs (all unmeasured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
