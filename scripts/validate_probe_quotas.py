#!/usr/bin/env python3
"""Validate rendered synthetic Probe schedules against reviewed application quotas."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
ENVIRONMENTS = {"staging", "prod"}
REQUIRED = {
    "application",
    "environment",
    "probe",
    "route",
    "path",
    "method",
    "interval",
    "enabled",
    "bucket",
    "limits",
    "exemptions",
    "fanout",
    "requestMultiplier",
    "safetyMargin",
    "unlimited",
}
DURATION = re.compile(r"^([1-9][0-9]*)(ms|s|m|h)$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ValidationError(ValueError):
    """A safe, repository-owned contract or manifest validation error."""


def _yaml_json(path: Path) -> object:
    result = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "puts JSON.generate(YAML.load_stream(File.read(ARGV[0])))",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValidationError(f"could not parse repository YAML {path.relative_to(ROOT)}")
    return json.loads(result.stdout)


def _duration(value: object, field: str) -> float:
    if not isinstance(value, str) or not (match := DURATION.fullmatch(value)):
        raise ValidationError(f"{field} must be a positive integer duration using ms, s, m, or h")
    number, unit = match.groups()
    seconds = int(number) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    if seconds <= 0:
        raise ValidationError(f"{field} must be positive")
    return seconds


def _active_resources(environment: str, root: Path = ROOT) -> list[dict]:
    """Render the deliberately simple, lifecycle-owned Probe Kustomize graph."""
    directory = root / "clusters" / environment / "observability" / "probes"
    kustomization = _yaml_json(directory / "kustomization.yaml")
    if len(kustomization) != 1 or not isinstance(kustomization[0], dict):
        raise ValidationError("active Probe kustomization is malformed")
    config = kustomization[0]
    allowed = {"apiVersion", "kind", "resources"}
    if set(config) - allowed or config.get("kind") != "Kustomization":
        raise ValidationError("active Probe graph uses unsupported Kustomize transformations")
    resources = config.get("resources")
    if (
        not isinstance(resources, list)
        or not resources
        or not all(isinstance(x, str) for x in resources)
    ):
        raise ValidationError("active Probe kustomization requires a non-empty resources list")
    documents: list[dict] = []
    for resource in resources:
        path = (directory / resource).resolve()
        if path.parent != directory.resolve() or not path.is_file():
            raise ValidationError("active Probe graph resource must be a local file")
        for document in _yaml_json(path):
            if document is not None:
                if not isinstance(document, dict):
                    raise ValidationError("rendered Probe graph contains a non-object document")
                documents.append(document)
    return documents


def _module_methods(environment: str, root: Path = ROOT) -> dict[str, str]:
    path = (
        root
        / "clusters"
        / environment
        / "observability"
        / "prometheus-blackbox-exporter.values.yaml"
    )
    docs = _yaml_json(path)
    data = docs[0] if len(docs) == 1 else None
    modules = data.get("config", {}).get("modules") if isinstance(data, dict) else None
    if not isinstance(modules, dict):
        raise ValidationError("blackbox exporter values lack config.modules")
    result = {}
    for name, module in modules.items():
        method = module.get("http", {}).get("method") if isinstance(module, dict) else None
        if method not in HTTP_METHODS:
            raise ValidationError(f"blackbox module {name!r} has a missing or unknown method")
        result[name] = method
    return result


def _prometheus_fanout(environment: str, root: Path = ROOT) -> int:
    common = _yaml_json(
        root / "platform/observability/helm/kube-prometheus-stack.values.common.yaml"
    )[0]
    override = _yaml_json(
        root / f"clusters/{environment}/observability/kube-prometheus-stack.values.yaml"
    )[0]
    value = override.get("prometheus", {}).get("prometheusSpec", {}).get("replicas")
    if value is None:
        value = common.get("prometheus", {}).get("prometheusSpec", {}).get("replicas")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError("Prometheus replica fanout must be a positive integer")
    return value


def discover_probes(environment: str, root: Path = ROOT) -> dict[str, dict]:
    methods, fanout = _module_methods(environment, root), _prometheus_fanout(environment, root)
    probes: dict[str, dict] = {}
    for item in _active_resources(environment, root):
        if item.get("kind") != "Probe":
            raise ValidationError("active Probe graph contains a non-Probe object")
        meta, spec = item.get("metadata"), item.get("spec")
        if not isinstance(meta, dict) or not isinstance(spec, dict):
            raise ValidationError("rendered Probe is missing metadata or spec")
        name, labels = meta.get("name"), meta.get("labels")
        targets = spec.get("targets", {}).get("staticConfig", {}).get("static")
        if not isinstance(name, str) or name in probes or not isinstance(labels, dict):
            raise ValidationError("rendered Probe has a missing or duplicate identity")
        if labels.get("environment") != environment:
            raise ValidationError(f"Probe {name!r} has contradictory environment metadata")
        if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], str):
            raise ValidationError(f"Probe {name!r} must have exactly one static target")
        parsed = urlsplit(targets[0])
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValidationError(f"Probe {name!r} target must be one repository-owned HTTPS path")
        module = spec.get("module")
        if module not in methods:
            raise ValidationError(f"Probe {name!r} uses an unknown blackbox module")
        probes[name] = {
            "application": labels.get("app"),
            "environment": labels.get("environment"),
            "route": labels.get("route"),
            "path": parsed.path or "/",
            "method": methods[module],
            "interval": spec.get("interval"),
            "fanout": fanout,
        }
    return probes


def _contracts(config_dir: Path, environment: str) -> list[dict]:
    files = sorted(config_dir.glob("*.json"))
    if not files:
        raise ValidationError("quota config directory contains no JSON contracts")
    records: list[dict] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"quota contract file {path.name!r} is malformed") from exc
        if (
            not isinstance(data, dict)
            or set(data) != {"schemaVersion", "application", "probes"}
            or data.get("schemaVersion") != 1
            or not isinstance(data.get("application"), str)
            or not NAME.fullmatch(data["application"])
            or not isinstance(data.get("probes"), list)
        ):
            raise ValidationError(f"quota contract file {path.name!r} has an unsupported schema")
        if any(not isinstance(x, dict) for x in data["probes"]):
            raise ValidationError(
                f"quota contract file {path.name!r} contains a non-object declaration"
            )
        if any(x.get("environment") not in ENVIRONMENTS for x in data["probes"]):
            raise ValidationError(
                f"quota contract file {path.name!r} contains an unknown environment"
            )
        if any(x.get("application") != data["application"] for x in data["probes"]):
            raise ValidationError(
                f"quota contract file {path.name!r} contains contradictory application metadata"
            )
        records.extend(x for x in data["probes"] if x["environment"] == environment)
    return records


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def validate(environment: str, config_dir: Path, root: Path = ROOT) -> list[str]:
    if environment not in ENVIRONMENTS:
        raise ValidationError("environment must be staging or prod")
    active, records = discover_probes(environment, root), _contracts(config_dir, environment)
    seen: set[str] = set()
    groups: dict[tuple[str, str], dict] = {}
    exempted = 0
    for record in records:
        missing = REQUIRED - set(record)
        if missing:
            raise ValidationError(
                f"quota declaration is missing required fields: {', '.join(sorted(missing))}"
            )
        if set(record) != REQUIRED:
            raise ValidationError("quota declaration contains unknown fields")
        name = record["probe"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in seen:
            raise ValidationError(
                "quota declarations contain a missing, malformed, or duplicate probe identity"
            )
        seen.add(name)
        if record["environment"] != environment:
            raise ValidationError(
                f"quota declaration {name!r} has contradictory environment metadata"
            )
        for field in ("application", "route", "bucket"):
            if not isinstance(record[field], str) or not NAME.fullmatch(record[field]):
                raise ValidationError(f"quota declaration {name!r} has malformed {field}")
        if (
            not isinstance(record["path"], str)
            or not record["path"].startswith("/")
            or "?" in record["path"]
            or "#" in record["path"]
        ):
            raise ValidationError(f"quota declaration {name!r} has malformed path")
        if record["method"] not in HTTP_METHODS:
            raise ValidationError(f"quota declaration {name!r} has unknown method")
        interval = _duration(record["interval"], f"{name}.interval")
        if not isinstance(record["enabled"], bool) or not isinstance(record["unlimited"], bool):
            raise ValidationError(
                f"quota declaration {name!r} requires boolean enabled and unlimited fields"
            )
        fanout = _positive_int(record["fanout"], f"{name}.fanout")
        multiplier = _positive_int(record["requestMultiplier"], f"{name}.requestMultiplier")
        margin = record["safetyMargin"]
        if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin < 1:
            raise ValidationError(f"quota declaration {name!r} safetyMargin must be in [0, 1)")
        exemptions = record["exemptions"]
        if not isinstance(exemptions, list) or any(
            not isinstance(x, dict) or set(x) != {"path", "methods"} for x in exemptions
        ):
            raise ValidationError(f"quota declaration {name!r} has malformed exemptions")
        pairs: set[tuple[str, str]] = set()
        for exemption in exemptions:
            path, methods = exemption["path"], exemption["methods"]
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or not isinstance(methods, list)
                or not methods
            ):
                raise ValidationError(f"quota declaration {name!r} has malformed exemptions")
            for method in methods:
                if method not in HTTP_METHODS or (path, method) in pairs:
                    raise ValidationError(
                        f"quota declaration {name!r} has unknown or duplicate exemption"
                    )
                pairs.add((path, method))
        limits = record["limits"]
        if not isinstance(limits, dict) or set(limits) != {"hourly", "daily"}:
            raise ValidationError(
                f"quota declaration {name!r} requires exact hourly and daily limits"
            )
        if record["unlimited"]:
            if limits != {"hourly": None, "daily": None} or exemptions:
                raise ValidationError(
                    f"unlimited declaration {name!r} contradicts limits or exemptions"
                )
        else:
            hourly = _positive_int(limits["hourly"], f"{name}.limits.hourly")
            daily = _positive_int(limits["daily"], f"{name}.limits.daily")
        manifest = active.get(name)
        if record["enabled"]:
            if manifest is None:
                raise ValidationError(f"enabled quota declaration {name!r} has no active Probe")
            for field in (
                "application",
                "environment",
                "route",
                "path",
                "method",
                "interval",
                "fanout",
            ):
                if record[field] != manifest[field]:
                    raise ValidationError(
                        f"quota declaration {name!r} contradicts rendered Probe field {field}"
                    )
        elif manifest is not None:
            raise ValidationError(f"active Probe {name!r} is declared disabled")
        if not record["enabled"] or record["unlimited"]:
            continue
        if (record["path"], record["method"]) in pairs:
            exempted += 1
            continue
        key = (record["application"], record["bucket"])
        signature = (hourly, daily, float(margin))
        group = groups.setdefault(
            key, {"signature": signature, "hourly": 0, "daily": 0, "probes": []}
        )
        if group["signature"] != signature:
            raise ValidationError(
                f"shared quota bucket {key[0]}/{key[1]} has contradictory limits or margins"
            )
        executions = fanout * multiplier
        group["hourly"] += math.ceil(3600 / interval) * executions
        group["daily"] += math.ceil(86400 / interval) * executions
        group["probes"].append(name)
    undeclared = sorted(set(active) - seen)
    if undeclared:
        raise ValidationError(f"active Probe {undeclared[0]!r} lacks a quota declaration")
    for (application, bucket), group in groups.items():
        hourly, daily, margin = group["signature"]
        for window, volume, limit in (
            ("hourly", group["hourly"], hourly),
            ("daily", group["daily"], daily),
        ):
            usable = math.floor(limit * (1 - margin))
            if volume >= usable:
                names = ", ".join(sorted(group["probes"]))
                raise ValidationError(
                    f"{application}/{environment} bucket {bucket!r} {window} volume {volume} "
                    f"reaches or exceeds usable budget {usable} (reviewed limit {limit}); "
                    f"probes: {names}"
                )
    return [f"validated {len(active)} active {environment} Probes ({exempted} exact exemptions)"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", action="append", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument(
        "--config-dir", type=Path, default=ROOT / "platform/observability/probe-quotas"
    )
    args = parser.parse_args(argv)
    try:
        for environment in args.env:
            for message in validate(environment, args.config_dir):
                print(message)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
