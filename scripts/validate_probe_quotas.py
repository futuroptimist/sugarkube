#!/usr/bin/env python3
"""Validate rendered blackbox Probe schedules against declarative application quotas."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import app_config  # noqa: E402

WINDOWS = {"hourly": 3600, "daily": 86400}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
REQUIRED = {
    "application",
    "environment",
    "probe",
    "route_class",
    "path",
    "method",
    "interval",
    "enabled",
    "bucket",
    "limits",
    "exemptions",
    "fanout",
    "request_multiplier",
    "safety_margin",
    "unlimited",
    "unlimited_reason",
}


class ValidationError(ValueError):
    """A safe, repository-metadata-only validation failure."""


def _duration(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*[smh]", value):
        raise ValidationError("interval must be a positive integer duration using s, m, or h")
    amount, unit = int(value[:-1]), value[-1]
    return amount * {"s": 1, "m": 60, "h": 3600}[unit]


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def _margin(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(
            "safety_margin must be a number greater than or equal to 0 and less than 1"
        )
    if isinstance(value, bool) or result < 0 or result >= 1:
        raise ValidationError(
            "safety_margin must be a number greater than or equal to 0 and less than 1"
        )
    return result


def _safe_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value):
        raise ValidationError(f"{field} must be a lowercase repository-owned identifier")
    return value


def _path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or urlsplit(value).query
        or urlsplit(value).fragment
    ):
        raise ValidationError(
            "path must be an exact absolute application-owned path without query or fragment"
        )
    return value


def validate_contract(raw: object, expected_app: str, expected_env: str) -> dict:
    if not isinstance(raw, dict) or set(raw) != REQUIRED:
        raise ValidationError("contract fields are missing, unknown, or ambiguous")
    contract = dict(raw)
    for field in ("application", "environment", "probe", "route_class", "bucket"):
        contract[field] = _safe_name(contract[field], field)
    if contract["application"] != expected_app or contract["environment"] != expected_env:
        raise ValidationError(
            "contract application or environment does not match its owning configuration"
        )
    contract["path"] = _path(contract["path"])
    if contract["method"] not in METHODS:
        raise ValidationError("method must be a supported uppercase HTTP method")
    contract["interval_seconds"] = _duration(contract["interval"])
    if not isinstance(contract["enabled"], bool) or not isinstance(contract["unlimited"], bool):
        raise ValidationError("enabled and unlimited must be booleans")
    contract["fanout"] = _positive_int(contract["fanout"], "fanout")
    contract["request_multiplier"] = _positive_int(
        contract["request_multiplier"], "request_multiplier"
    )
    contract["safety_margin_decimal"] = _margin(contract["safety_margin"])
    exemptions = contract["exemptions"]
    if not isinstance(exemptions, list):
        raise ValidationError("exemptions must be a list")
    seen_exemptions = set()
    for exemption in exemptions:
        if not isinstance(exemption, dict) or set(exemption) != {"path", "method"}:
            raise ValidationError("each exemption must contain exactly path and method")
        pair = (_path(exemption["path"]), exemption["method"])
        if pair[1] not in METHODS or pair in seen_exemptions:
            raise ValidationError(
                "exemptions contain an unknown method or duplicate exact declaration"
            )
        seen_exemptions.add(pair)
    contract["exemption_pairs"] = seen_exemptions
    limits = contract["limits"]
    if contract["unlimited"]:
        if (
            limits is not None
            or exemptions
            or not isinstance(contract["unlimited_reason"], str)
            or not contract["unlimited_reason"].strip()
        ):
            raise ValidationError(
                "unlimited contracts require null limits, no exemptions, and a reviewable reason"
            )
    else:
        if contract["unlimited_reason"] is not None:
            raise ValidationError("limited contracts must use a null unlimited_reason")
        if not isinstance(limits, dict) or set(limits) != set(WINDOWS):
            raise ValidationError("limited contracts require exactly hourly and daily limits")
        contract["limits"] = {key: _positive_int(limits[key], f"{key} limit") for key in WINDOWS}
    return contract


def _yaml_to_json(text: str) -> list[dict]:
    ruby = "require 'yaml'; require 'json'; puts JSON.generate(YAML.load_stream(STDIN.read))"
    result = subprocess.run(["ruby", "-e", ruby], input=text, text=True, capture_output=True)
    if result.returncode:
        raise ValidationError("rendered Probe YAML is malformed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValidationError("rendered Probe YAML could not be normalized")
    if not isinstance(value, list):
        raise ValidationError("rendered Probe graph is not a document list")
    return value


def render_probes(environment: str, rendered: Path | None = None) -> list[dict]:
    if rendered:
        text = rendered.read_text(encoding="utf-8")
    else:
        path = ROOT / "clusters" / environment / "observability" / "probes"
        result = subprocess.run(["kubectl", "kustomize", str(path)], text=True, capture_output=True)
        if result.returncode:
            raise ValidationError(f"{environment} active Probe Kustomize graph did not render")
        text = result.stdout
    return _yaml_to_json(text)


def module_methods(environment: str) -> dict[str, str]:
    path = (
        ROOT
        / "clusters"
        / environment
        / "observability"
        / "prometheus-blackbox-exporter.values.yaml"
    )
    documents = _yaml_to_json(path.read_text(encoding="utf-8"))
    try:
        modules = documents[0]["config"]["modules"]
        return {name: settings["http"]["method"] for name, settings in modules.items()}
    except (KeyError, TypeError, AttributeError):
        raise ValidationError(
            f"{environment} blackbox module method metadata is missing or malformed"
        )


def active_probe_facts(
    documents: list[dict], environment: str, methods: dict[str, str]
) -> dict[str, dict]:
    facts = {}
    for document in documents:
        if not isinstance(document, dict) or document.get("kind") != "Probe":
            continue
        metadata, spec = document.get("metadata"), document.get("spec")
        try:
            name = metadata["name"]
            labels = metadata["labels"]
            app, declared_env, route = labels["app"], labels["environment"], labels["route"]
            interval, module = spec["interval"], spec["module"]
            targets = spec["targets"]["staticConfig"]["static"]
        except (KeyError, TypeError):
            raise ValidationError(
                "an active Probe lacks required bounded identity or schedule metadata"
            )
        if declared_env != environment or not isinstance(targets, list) or len(targets) != 1:
            raise ValidationError("an active Probe has ambiguous environment or target metadata")
        if name in facts or module not in methods:
            raise ValidationError(
                "active Probe identity is duplicated or its HTTP method is unknown"
            )
        target = targets[0]
        parsed = urlsplit(target) if isinstance(target, str) else None
        if (
            not parsed
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError("an active Probe target is not one exact HTTPS application path")
        facts[name] = {
            "application": app,
            "environment": environment,
            "route_class": route,
            "path": parsed.path or "/",
            "method": methods[module],
            "interval": interval,
        }
    return facts


def load_contracts(
    applications: set[str], environment: str, config_dir: Path | None = None
) -> list[dict]:
    old = os.environ.get("SUGARKUBE_APP_CONFIG_DIR")
    if config_dir is not None:
        os.environ["SUGARKUBE_APP_CONFIG_DIR"] = str(config_dir)
    contracts = []
    try:
        for application in sorted(applications):
            config = app_config.load_config(application, environment)
            relative = config.get("SUGARKUBE_PROBE_QUOTA_CONFIG")
            if not relative:
                raise ValidationError(f"application {application} has no probe quota configuration")
            path = Path(relative)
            if not path.is_absolute():
                path = ROOT / path
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise ValidationError(
                    f"application {application} probe quota configuration is unreadable "
                    "or malformed"
                )
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "application",
                "environments",
            }:
                raise ValidationError(
                    f"application {application} quota document has an invalid top-level schema"
                )
            if payload["schema_version"] != 1 or payload["application"] != application:
                raise ValidationError(
                    f"application {application} quota document has contradictory ownership metadata"
                )
            environments = payload["environments"]
            if not isinstance(environments, dict) or set(environments) != {"staging", "prod"}:
                raise ValidationError(
                    f"application {application} quota document must own exactly staging "
                    "and prod metadata"
                )
            if not isinstance(environments[environment], list):
                raise ValidationError(
                    f"application {application} has no unambiguous {environment} quota contracts"
                )
            contracts.extend(
                validate_contract(item, application, environment)
                for item in environments[environment]
            )
    finally:
        if config_dir is not None:
            if old is None:
                os.environ.pop("SUGARKUBE_APP_CONFIG_DIR", None)
            else:
                os.environ["SUGARKUBE_APP_CONFIG_DIR"] = old
    return contracts


def validate(environment: str, probes: dict[str, dict], contracts: list[dict]) -> list[str]:
    by_probe = {}
    for contract in contracts:
        name = contract["probe"]
        if name in by_probe:
            raise ValidationError(f"duplicate contract for {environment} probe {name}")
        by_probe[name] = contract
    missing, orphaned = sorted(set(probes) - set(by_probe)), sorted(set(by_probe) - set(probes))
    if missing:
        raise ValidationError(f"undeclared active {environment} probe: {missing[0]}")
    if orphaned:
        raise ValidationError(f"orphaned {environment} quota declaration: {orphaned[0]}")
    buckets: dict[tuple, dict] = {}
    for name, probe in probes.items():
        contract = by_probe[name]
        for field in ("application", "environment", "route_class", "path", "method", "interval"):
            if contract[field] != probe[field]:
                raise ValidationError(
                    f"{environment} probe {name} contract does not match rendered {field}"
                )
        if (
            contract["unlimited"]
            or not contract["enabled"]
            or (contract["path"], contract["method"]) in contract["exemption_pairs"]
        ):
            continue
        key = (contract["application"], contract["bucket"])
        signature = (contract["limits"], contract["safety_margin_decimal"])
        if key in buckets and buckets[key]["signature"] != signature:
            raise ValidationError(f"{environment} bucket {key[1]} has contradictory quota metadata")
        bucket = buckets.setdefault(key, {"signature": signature, "volumes": defaultdict(int)})
        for window, seconds in WINDOWS.items():
            executions = math.ceil(seconds / contract["interval_seconds"])
            bucket["volumes"][window] += (
                executions * contract["fanout"] * contract["request_multiplier"]
            )
    output = []
    for (application, bucket_name), details in sorted(buckets.items()):
        limits, margin = details["signature"]
        for window in WINDOWS:
            volume, limit = details["volumes"][window], limits[window]
            usable = Decimal(limit) * (Decimal(1) - margin)
            if Decimal(volume) >= usable:
                raise ValidationError(
                    f"{application} {environment} bucket {bucket_name} {window} "
                    f"volume {volume} reaches reviewed limit {limit}"
                )
        output.append(
            f"validated application={application} environment={environment} bucket={bucket_name}"
        )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("staging", "prod", "all"), default="all")
    parser.add_argument("--rendered", type=Path, help="pre-rendered YAML (single environment only)")
    parser.add_argument("--config-dir", type=Path)
    args = parser.parse_args(argv)
    if args.rendered and args.env == "all":
        parser.error("--rendered requires one explicit environment")
    try:
        for environment in (("staging", "prod") if args.env == "all" else (args.env,)):
            documents = render_probes(environment, args.rendered)
            probes = active_probe_facts(documents, environment, module_methods(environment))
            contracts = load_contracts(
                {item["application"] for item in probes.values()}, environment, args.config_dir
            )
            for line in validate(environment, probes, contracts):
                print(line)
            print(f"validated {len(probes)} active {environment} Probe quota contracts")
    except (ValidationError, app_config.AppConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
