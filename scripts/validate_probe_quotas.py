#!/usr/bin/env python3
"""Validate rendered Prometheus Probe schedules against reviewed application quotas."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
DURATION = re.compile(r"^([1-9][0-9]*)(ms|s|m|h)$")
WINDOWS = {"hourly": 3600, "daily": 86400}


class ValidationError(ValueError):
    pass


def _object(value, context):
    if not isinstance(value, dict):
        raise ValidationError(f"{context} must be an object")
    return value


def _required(obj, key, context, expected=None):
    if key not in obj:
        raise ValidationError(f"{context} is missing {key}")
    value = obj[key]
    if expected and not isinstance(value, expected):
        raise ValidationError(f"{context}.{key} has an invalid type")
    return value


def duration_seconds(value, context="interval"):
    if not isinstance(value, str) or not (match := DURATION.fullmatch(value)):
        raise ValidationError(f"{context} must be a positive duration using ms, s, m, or h")
    number, unit = match.groups()
    seconds = int(number) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    if seconds <= 0:
        raise ValidationError(f"{context} must be positive")
    return seconds


def _positive_int(value, context):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"{context} must be a positive integer")
    return value


def _path(value, context):
    if not isinstance(value, str) or not value.startswith("/") or "?" in value or "#" in value:
        raise ValidationError(f"{context} must be an exact absolute path without query or fragment")
    return value


def load_yaml_stream(path: Path):
    command = [
        "ruby",
        "-ryaml",
        "-rjson",
        "-e",
        "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
        str(path),
    ]
    try:
        return json.loads(
            subprocess.run(command, check=True, text=True, capture_output=True).stdout
        )
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise ValidationError(f"could not parse repository YAML: {path.relative_to(ROOT)}") from exc


def render_active_probes(environment: str):
    directory = ROOT / "clusters" / environment / "observability" / "probes"
    kustomization = load_yaml_stream(directory / "kustomization.yaml")
    if len(kustomization) != 1:
        raise ValidationError(f"{environment} probe Kustomize graph is malformed")
    resources = _object(kustomization[0], "Kustomization").get("resources")
    if (
        not isinstance(resources, list)
        or not resources
        or not all(isinstance(x, str) for x in resources)
    ):
        raise ValidationError(f"{environment} Probe Kustomize resources are missing or malformed")
    documents = []
    for resource in resources:
        candidate = (directory / resource).resolve()
        if directory.resolve() not in candidate.parents or not candidate.is_file():
            raise ValidationError(f"{environment} Probe Kustomize resource is invalid")
        documents.extend(load_yaml_stream(candidate))
    return documents


def module_methods(environment: str):
    docs = load_yaml_stream(
        ROOT
        / "clusters"
        / environment
        / "observability"
        / "prometheus-blackbox-exporter.values.yaml"
    )
    config = _object(docs[0], "blackbox values")
    modules = _object(_object(config.get("config"), "config").get("modules"), "config.modules")
    result = {}
    for name, module in modules.items():
        http = _object(_object(module, f"module {name}").get("http"), f"module {name}.http")
        method = http.get("method")
        if method not in METHODS:
            raise ValidationError(f"blackbox module {name} has a missing or unknown HTTP method")
        result[name] = method
    return result


def load_contract(environment: str, config_dir: Path | None = None):
    base = config_dir or ROOT / "config" / "observability-probe-quotas"
    path = base / f"{environment}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"quota contract for {environment} is missing or malformed") from exc


def active_probe_facts(documents, environment, methods):
    facts = {}
    for doc in documents:
        if not isinstance(doc, dict) or doc.get("kind") != "Probe":
            continue
        metadata = _object(doc.get("metadata"), "active Probe metadata")
        name = _required(metadata, "name", "active Probe", str)
        if name in facts:
            raise ValidationError(f"duplicate active Probe identity: {name}")
        labels = _object(metadata.get("labels"), f"active Probe {name} labels")
        app = _required(labels, "app", f"active Probe {name} labels", str)
        actual_env = _required(labels, "environment", f"active Probe {name} labels", str)
        route_class = _required(labels, "route", f"active Probe {name} labels", str)
        if actual_env != environment:
            raise ValidationError(f"active Probe {name} has contradictory environment metadata")
        spec = _object(doc.get("spec"), f"active Probe {name} spec")
        module = _required(spec, "module", f"active Probe {name} spec", str)
        if module not in methods:
            raise ValidationError(f"active Probe {name} references an unknown blackbox module")
        interval = _required(spec, "interval", f"active Probe {name} spec", str)
        duration_seconds(interval, f"active Probe {name} interval")
        static = _object(
            _object(spec.get("targets"), "targets").get("staticConfig"), "staticConfig"
        ).get("static")
        if not isinstance(static, list) or len(static) != 1 or not isinstance(static[0], str):
            raise ValidationError(f"active Probe {name} must have exactly one static target")
        parsed = urlsplit(static[0])
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or "@" in parsed.netloc
        ):
            raise ValidationError(f"active Probe {name} target is malformed")
        facts[name] = {
            "application": app,
            "environment": actual_env,
            "route_class": route_class,
            "route": parsed.path or "/",
            "method": methods[module],
            "interval": interval,
        }
    if not facts:
        raise ValidationError(f"{environment} active Probe graph contains no Probe objects")
    return facts


def validate(environment, documents, contract, methods):
    root = _object(contract, "quota contract")
    if root.get("schema_version") != 1 or root.get("environment") != environment:
        raise ValidationError(
            "quota contract has missing or contradictory schema/environment metadata"
        )
    policies = _required(root, "quota_policies", "quota contract", list)
    declarations = _required(root, "probes", "quota contract", list)
    policy_map = {}
    exemptions = defaultdict(set)
    unlimited = defaultdict(set)
    for index, raw in enumerate(policies):
        item = _object(raw, f"quota policy {index}")
        app = _required(item, "application", f"quota policy {index}", str)
        bucket = _required(item, "bucket", f"quota policy {index}", str)
        key = (app, bucket)
        if key in policy_map:
            raise ValidationError(f"duplicate quota policy: {app}/{bucket}")
        limits = _object(_required(item, "limits", f"quota policy {index}"), "limits")
        parsed_limits = {
            window: _positive_int(_required(limits, window, "limits"), f"limits.{window}")
            for window in WINDOWS
        }
        try:
            margin = Decimal(str(_required(item, "safety_margin", f"quota policy {index}")))
        except (InvalidOperation, ValueError):
            raise ValidationError(f"quota policy {app}/{bucket} has an invalid safety margin")
        if isinstance(item["safety_margin"], bool) or not Decimal(0) <= margin < Decimal(1):
            raise ValidationError(f"quota policy {app}/{bucket} has an invalid safety margin")
        for field, target in (("exemptions", exemptions), ("unlimited_endpoints", unlimited)):
            values = _required(item, field, f"quota policy {app}/{bucket}", list)
            for entry in values:
                entry = _object(entry, f"{field} entry")
                route = _path(_required(entry, "route", field, str), f"{field}.route")
                method = _required(entry, "method", field, str)
                if method not in METHODS:
                    raise ValidationError(f"{field} contains an unknown method")
                pair = (route, method)
                if pair in target[key]:
                    raise ValidationError(f"duplicate {field} declaration for {app}/{bucket}")
                target[key].add(pair)
        if exemptions[key] & unlimited[key]:
            raise ValidationError(
                f"quota policy {app}/{bucket} has contradictory endpoint metadata"
            )
        policy_map[key] = (parsed_limits, margin)

    actual = active_probe_facts(documents, environment, methods)
    declared = {}
    traffic = defaultdict(int)
    for index, raw in enumerate(declarations):
        item = _object(raw, f"probe contract {index}")
        name = _required(item, "probe", f"probe contract {index}", str)
        if name in declared:
            raise ValidationError(f"duplicate probe contract: {name}")
        declared[name] = item
        app = _required(item, "application", name, str)
        if _required(item, "environment", name, str) != environment:
            raise ValidationError(f"probe contract {name} has contradictory environment metadata")
        route_class = _required(item, "route_class", name, str)
        route = _path(_required(item, "route", name, str), f"{name}.route")
        method = _required(item, "method", name, str)
        if method not in METHODS:
            raise ValidationError(f"probe contract {name} has an unknown method")
        interval = _required(item, "interval", name, str)
        seconds = duration_seconds(interval, f"{name}.interval")
        enabled = _required(item, "enabled", name, bool)
        bucket = _required(item, "quota_bucket", name, str)
        fanout = _positive_int(_required(item, "scrape_fanout", name), f"{name}.scrape_fanout")
        multiplier = _positive_int(
            _required(item, "request_multiplier", name), f"{name}.request_multiplier"
        )
        key = (app, bucket)
        if key not in policy_map:
            raise ValidationError(f"probe contract {name} references an undeclared quota bucket")
        if name not in actual:
            raise ValidationError(f"orphaned probe contract: {name}")
        expected = {
            "application": app,
            "environment": environment,
            "route_class": route_class,
            "route": route,
            "method": method,
            "interval": interval,
        }
        if actual[name] != expected:
            raise ValidationError(f"probe contract {name} contradicts its active manifest")
        if (
            enabled
            and (route, method) not in exemptions[key]
            and (route, method) not in unlimited[key]
        ):
            for window, window_seconds in WINDOWS.items():
                traffic[(key, window)] += math.ceil(window_seconds / seconds) * fanout * multiplier

    missing = sorted(set(actual) - set(declared))
    if missing:
        raise ValidationError(f"active Probe lacks a quota contract: {missing[0]}")
    for key, (limits, margin) in policy_map.items():
        for window in WINDOWS:
            volume = traffic[(key, window)]
            usable = int(
                (Decimal(limits[window]) * (Decimal(1) - margin)).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            if volume >= usable:
                app, bucket = key
                raise ValidationError(
                    f"unsafe schedule: application={app} environment={environment} bucket={bucket} "
                    f"window={window} calculated_volume={volume} "
                    f"reviewed_limit={limits[window]} usable_budget={usable}"
                )
    return len(actual)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, choices=("staging", "prod"))
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--rendered-probes", type=Path)
    args = parser.parse_args(argv)
    try:
        documents = (
            json.loads(args.rendered_probes.read_text())["items"]
            if args.rendered_probes
            else render_active_probes(args.env)
        )
        count = validate(
            args.env, documents, load_contract(args.env, args.config_dir), module_methods(args.env)
        )
    except (ValidationError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: probe quota validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: validated {count} active {args.env} Probe quota contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
