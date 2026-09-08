#!/usr/bin/env python3
"""Fail closed when rendered blackbox Probe schedules can exhaust app quotas."""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = {"hourly": 3600, "daily": 86400}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
ENVIRONMENTS = {"staging", "prod"}
DECLARATION_FIELDS = {
    "application",
    "environment",
    "probe",
    "route_class",
    "route",
    "method",
    "interval",
    "enabled",
    "bucket",
    "limits",
    "exemptions",
    "scrape_fanout",
    "request_multiplier",
    "safety_margin",
    "unlimited_operational",
}


class ContractError(ValueError):
    """A safe, repository-only validation error."""


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _duration(value, field="interval"):
    if not isinstance(value, str) or len(value) < 2:
        raise ContractError(f"{field} is malformed")
    unit = value[-1]
    if unit not in {"s", "m", "h"} or not value[:-1].isdigit():
        raise ContractError(f"{field} is malformed")
    seconds = int(value[:-1]) * {"s": 1, "m": 60, "h": 3600}[unit]
    if seconds <= 0:
        raise ContractError(f"{field} must be positive")
    return seconds


def _exact_path(value, field):
    if not isinstance(value, str) or not value.startswith("/"):
        raise ContractError(f"{field} must be an exact path")
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise ContractError(f"{field} must be an exact path without a query or fragment")
    return value


def _documents(text):
    return [doc for doc in yaml.safe_load_all(text) if isinstance(doc, dict)]


def render_active(environment, runner=subprocess.run):
    directory = ROOT / "clusters" / environment / "observability" / "probes"
    result = runner(
        ["kubectl", "kustomize", str(directory)], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise ContractError(f"unable to render active {environment} Probe Kustomize graph")
    return result.stdout


def load_modules(environment):
    path = (
        ROOT
        / "clusters"
        / environment
        / "observability"
        / "prometheus-blackbox-exporter.values.yaml"
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    modules = data.get("config", {}).get("modules", {})
    methods = {}
    for name, module in modules.items():
        method = module.get("http", {}).get("method")
        if method not in METHODS:
            raise ContractError(f"blackbox module {name} has an invalid or missing method")
        methods[name] = method
    common_values = yaml.safe_load(
        (
            ROOT
            / "platform"
            / "observability"
            / "helm"
            / "kube-prometheus-stack.values.common.yaml"
        ).read_text(encoding="utf-8")
    )
    environment_values = yaml.safe_load(
        (
            ROOT / "clusters" / environment / "observability" / "kube-prometheus-stack.values.yaml"
        ).read_text(encoding="utf-8")
    )
    # kube-prometheus-stack defaults to one replica when replicas is omitted.
    common_spec = common_values.get("prometheus", {}).get("prometheusSpec", {})
    environment_spec = environment_values.get("prometheus", {}).get("prometheusSpec", {})
    replicas = environment_spec.get("replicas", common_spec.get("replicas", 1))
    return methods, _positive_int(replicas, "Prometheus replicas")


def select_environment_contract(contract_data, environment):
    """Validate inventory structure before selecting one environment's declarations."""
    if not isinstance(contract_data, dict) or set(contract_data) != {"version", "probes"}:
        raise ContractError("quota contract has missing or unknown top-level fields")
    if contract_data["version"] != 1:
        raise ContractError("quota contract version must be 1")
    declarations = contract_data["probes"]
    if not isinstance(declarations, list):
        raise ContractError("quota contract probes must be a list")

    selected = []
    identities = set()
    for item in declarations:
        _validate_declaration(item)
        identity = (item["environment"], item["probe"])
        if identity in identities:
            raise ContractError("quota declaration identity is duplicated")
        identities.add(identity)
        if item["environment"] == environment:
            selected.append(item)
    return {"version": 1, "probes": selected}


def _validate_declaration(item):
    """Validate environment-independent declaration metadata."""
    if not isinstance(item, dict):
        raise ContractError("each quota declaration must be an object")
    if set(item) != DECLARATION_FIELDS:
        raise ContractError("quota declaration has missing or unknown metadata")
    if item["environment"] not in ENVIRONMENTS:
        raise ContractError("quota declaration has an invalid environment")
    name = item["probe"]
    if not isinstance(name, str) or not name.strip():
        raise ContractError("quota declaration identity is missing")
    for field in ("application", "route_class", "bucket"):
        if not isinstance(item[field], str) or not item[field].strip():
            raise ContractError(f"probe {name} has invalid {field}")
    _exact_path(item["route"], f"probe {name} route")
    if item["method"] not in METHODS:
        raise ContractError(f"probe {name} has unknown method")
    _duration(item["interval"])
    if not isinstance(item["enabled"], bool) or not isinstance(item["unlimited_operational"], bool):
        raise ContractError(f"probe {name} has invalid enabled/unlimited metadata")
    _positive_int(item["scrape_fanout"], "scrape_fanout")
    _positive_int(item["request_multiplier"], "request_multiplier")
    margin = item["safety_margin"]
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin < 1:
        raise ContractError(f"probe {name} has invalid safety_margin")
    exemptions = item["exemptions"]
    if not isinstance(exemptions, list):
        raise ContractError(f"probe {name} has malformed exemptions")
    exemption_keys = []
    for exemption in exemptions:
        if not isinstance(exemption, dict) or set(exemption) != {"route", "method"}:
            raise ContractError(f"probe {name} has malformed exemptions")
        try:
            exemption_route = _exact_path(exemption["route"], f"probe {name} exemption route")
        except ContractError as exc:
            raise ContractError(f"probe {name} has malformed exemptions") from exc
        if exemption["method"] not in METHODS:
            raise ContractError(f"probe {name} has malformed exemptions")
        exemption_keys.append((exemption_route, exemption["method"]))
    if len(exemption_keys) != len(set(exemption_keys)):
        raise ContractError(f"probe {name} has duplicate exemptions")
    limits = item["limits"]
    if item["unlimited_operational"]:
        if limits is not None or exemptions:
            raise ContractError(f"probe {name} has contradictory unlimited metadata")
    else:
        if not isinstance(limits, dict) or set(limits) != set(WINDOWS):
            raise ContractError(f"probe {name} has missing or ambiguous limits")
        for window in WINDOWS:
            _positive_int(limits[window], f"{window} limit")


def validate(environment, rendered, contract_data, module_methods, replicas):
    if environment not in ENVIRONMENTS:
        raise ContractError("environment must be staging or prod")
    if not isinstance(contract_data, dict) or contract_data.get("version") != 1:
        raise ContractError("quota contract version must be 1")
    declarations = contract_data.get("probes")
    if not isinstance(declarations, list):
        raise ContractError("quota contract probes must be a list")

    active = {}
    for doc in _documents(rendered):
        if doc.get("kind") != "Probe":
            continue
        meta, spec = doc.get("metadata", {}), doc.get("spec", {})
        name = meta.get("name")
        labels = meta.get("labels", {})
        targets = spec.get("targets", {}).get("staticConfig", {}).get("static")
        if not isinstance(name, str) or name in active:
            raise ContractError("rendered Probe identity is missing or duplicated")
        if labels.get("environment") != environment:
            raise ContractError(f"probe {name} has contradictory environment metadata")
        if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], str):
            raise ContractError(f"probe {name} must have exactly one static target")
        parts = urlsplit(targets[0])
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.query
            or parts.fragment
        ):
            raise ContractError(f"probe {name} target route is ambiguous")
        active[name] = {
            "application": labels.get("app"),
            "route_class": labels.get("route"),
            "route": parts.path or "/",
            "interval": spec.get("interval"),
            "module": spec.get("module"),
        }

    declared = {}
    buckets = defaultdict(lambda: {"hourly": 0, "daily": 0, "records": []})
    bucket_policies = {}
    for item in declarations:
        _validate_declaration(item)
        name = item["probe"]
        if not isinstance(name, str) or name in declared:
            raise ContractError("quota declaration identity is missing or duplicated")
        declared[name] = item
        if item["environment"] != environment:
            raise ContractError(f"probe {name} has contradictory environment metadata")
        route = item["route"]
        method = item["method"]
        seconds = _duration(item["interval"])
        fanout = _positive_int(item["scrape_fanout"], "scrape_fanout")
        multiplier = _positive_int(item["request_multiplier"], "request_multiplier")
        margin = item["safety_margin"]
        exemptions = item["exemptions"]
        exemption_keys = [(x["route"], x["method"]) for x in exemptions]
        limits = item["limits"]

        manifest = active.get(name)
        if item["enabled"] and manifest is None:
            raise ContractError(f"enabled quota declaration {name} is orphaned")
        if not item["enabled"]:
            if manifest is not None:
                raise ContractError(f"disabled quota declaration {name} matches an active Probe")
            continue
        expected = (item["application"], item["route_class"], route, item["interval"])
        actual = (
            manifest["application"],
            manifest["route_class"],
            manifest["route"],
            manifest["interval"],
        )
        if expected != actual:
            raise ContractError(f"probe {name} contract contradicts its rendered manifest")
        actual_method = module_methods.get(manifest["module"])
        if actual_method is None or actual_method != method:
            raise ContractError(f"probe {name} method contradicts its blackbox module")
        if fanout != replicas:
            raise ContractError(f"probe {name} scrape_fanout contradicts Prometheus replicas")
        policy_key = (item["application"], environment, item["bucket"])
        policy = (
            ("unlimited", margin)
            if item["unlimited_operational"]
            else ("metered", margin, limits["hourly"], limits["daily"])
        )
        if policy_key in bucket_policies and bucket_policies[policy_key] != policy:
            raise ContractError(f"probe {name} has contradictory shared-bucket policy")
        bucket_policies[policy_key] = policy
        if item["unlimited_operational"] or (route, method) in exemption_keys:
            continue
        key = (*policy_key, *policy)
        volume = fanout * multiplier
        for window, duration in WINDOWS.items():
            buckets[key][window] += math.ceil(duration / seconds) * volume
        buckets[key]["records"].append(name)

    missing = sorted(set(active) - set(declared))
    if missing:
        raise ContractError(f"active Probe lacks quota declaration: {missing[0]}")
    for key, totals in buckets.items():
        app, env, bucket, _, margin, hourly_limit, daily_limit = key
        limits = {"hourly": hourly_limit, "daily": daily_limit}
        for window in WINDOWS:
            usable = limits[window] * (1 - Fraction(str(margin)))
            if totals[window] >= usable:
                raise ContractError(
                    f"unsafe schedule: application={app} environment={env} bucket={bucket} "
                    f"window={window} volume={totals[window]} reviewed_limit={limits[window]}"
                )
    return len(active)


def main(argv=None):
    configured_dir = os.environ.get("SUGARKUBE_APP_CONFIG_DIR")
    config_dir = Path(configured_dir) if configured_dir else ROOT / "config" / "observability"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, choices=("staging", "prod"))
    parser.add_argument(
        "--contracts",
        type=Path,
        default=config_dir / "probe-quotas.yaml",
        help="reviewed quota contract YAML",
    )
    parser.add_argument(
        "--probes",
        type=Path,
        help="already-rendered Probe YAML (default: kubectl kustomize active graph)",
    )
    args = parser.parse_args(argv)
    try:
        contract = yaml.safe_load(args.contracts.read_text(encoding="utf-8"))
        # One inventory owns both environments. Validate its complete structure so
        # malformed declarations cannot disappear during environment selection.
        contract = select_environment_contract(contract, args.env)
        rendered = (
            args.probes.read_text(encoding="utf-8") if args.probes else render_active(args.env)
        )
        methods, replicas = load_modules(args.env)
        validate(args.env, rendered, contract, methods, replicas)
    except (OSError, yaml.YAMLError, ContractError) as exc:
        print(f"probe quota validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"probe quota validation passed: environment={args.env}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
