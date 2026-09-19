#!/usr/bin/env python3
"""Validate the bounded, non-alerting application SLI inventory."""

import argparse
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config/observability/application-slis.json"
RULES = ROOT / "platform/observability/rules/application-slis.yaml"
FIELDS = {
    "id", "application", "userJourney", "signalType", "dataSource", "numerator",
    "denominator", "exclusions", "observationWindow", "objective", "measurementState",
}
OPTIONAL_FIELDS = {"monitoringState"}
SIGNALS = {"http_probe_health", "synthetic_completion", "actual_request_success"}
SOURCES = {
    "http_probe_health": {"probe_success"},
    "synthetic_completion": {
        "dspace_chat_synthetic_success", "danielsmith_visitor_journey_success",
        "encrypted_completion_lifecycle_state",
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
    if not isinstance(document, dict):
        raise ContractError("SLI contract must be an object")
    if (
        set(document) != {"schemaVersion", "retention", "slis"}
        or type(document["schemaVersion"]) is not int
        or document["schemaVersion"] != 1
    ):
        raise ContractError("unsupported top-level SLI contract")
    if not isinstance(document["retention"], str) or not document["retention"]:
        raise ContractError("retention must be a non-empty duration string")
    if not isinstance(document["slis"], list) or not document["slis"]:
        raise ContractError("slis must be a non-empty list")
    retention = minutes(document["retention"])
    if retention > 90 * 1440:
        raise ContractError("retention exceeds the repository-supported 90d maximum")
    ids = set()
    for sli in document["slis"]:
        if not isinstance(sli, dict):
            raise ContractError("each SLI must be an object")
        if not FIELDS <= set(sli) or set(sli) - FIELDS - OPTIONAL_FIELDS:
            raise ContractError("SLI fields must match the bounded schema")
        for field in FIELDS - {"objective", "exclusions"}:
            if not isinstance(sli[field], str) or not sli[field].strip():
                raise ContractError(f"{field} must be a non-empty string")
        if sli.get("monitoringState") not in (None, "disabled"):
            raise ContractError("monitoringState must be disabled when present")
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
        if re.search(r"\bor\s+(?:on\s*\([^)]*\)\s*)?vector\s*\(\s*0\s*\)", sli["numerator"] + " " + sli["denominator"]):
            raise ContractError("unconditional zero fallback hides NO DATA")
        if re.search(r"\bor\b[^\n]*(?:0\s*\*|\*\s*0)", sli["numerator"] + " " + sli["denominator"]):
            raise ContractError("zero fallback requires the matching eligible-traffic predicate")
        if minutes(sli["observationWindow"]) > retention:
            raise ContractError("observation window exceeds supported retention")
        if not isinstance(sli["exclusions"], list) or not sli["exclusions"] or not all(isinstance(item, str) and item.strip() for item in sli["exclusions"]):
            raise ContractError("exclusions must be a non-empty string list")
        if sli["dataSource"] == "encrypted_completion_lifecycle_state" and (
            sli.get("monitoringState") != "disabled"
            or "encrypted_completion_monitoring_enabled" not in sli["numerator"]
        ):
            raise ContractError("encrypted completion must be explicitly disabled and eligibility-gated")
    if {sli["application"] for sli in document["slis"]} != {
        "token.place", "DSPACE", "danielsmith.io"
    }:
        raise ContractError("contract must cover the three applications")
    return len(ids)


def validate_recording_labels(document: dict, rules_path: Path = RULES) -> None:
    """Ensure deployed recordings identify a canonical contract entry."""
    canonical = {
        (sli["application"], sli["id"], sli["signalType"])
        for sli in document["slis"]
    }
    try:
        groups = yaml.safe_load(rules_path.read_text(encoding="utf-8"))["groups"]
        rules = [rule for group in groups for rule in group["rules"]]
    except (OSError, TypeError, KeyError, yaml.YAMLError) as error:
        raise ContractError(f"invalid application SLI rules: {error}") from error
    for rule in rules:
        labels = rule.get("labels", {})
        identity = (labels.get("application"), labels.get("sli"), labels.get("signal_type"))
        if identity not in canonical:
            raise ContractError(f"recording rule labels are not canonical: {identity!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
        count = validate(document)
        validate_recording_labels(document)
    except (OSError, json.JSONDecodeError, ContractError) as error:
        parser.error(str(error))
    print(f"validated {count} application SLIs (all unmeasured)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
