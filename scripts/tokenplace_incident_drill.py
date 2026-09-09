#!/usr/bin/env python3
"""Build a fail-closed, privacy-safe token.place staging incident drill plan."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
SAFE_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
IMAGE = re.compile(r"[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}")
MODES = ("metrics-oom", "quota-exhaustion")
STAGING_HOST = "staging.token.place"


class DrillError(ValueError):
    """An error safe to show without echoing operator-supplied values."""


@dataclass(frozen=True)
class Coordinates:
    host: str
    kubeconfig: Path
    context: str
    environment: str
    namespace: str
    deployment: str
    container: str
    current_image: str
    replacement_image: str
    rollback_image: str
    replicas: int
    memory_limit: str
    service_monitor: str
    run_id: str


@dataclass(frozen=True)
class Inventory:
    namespace: str
    service_monitor: str
    selector_labels: tuple[tuple[str, str], ...]
    probes: tuple[tuple[str, str, str, str], ...]

    def probe_map(self) -> dict[str, dict[str, str]]:
        return {
            route_class: {"probe": name, "route": route, "method": method}
            for route_class, name, route, method in self.probes
        }


@dataclass(frozen=True)
class Preflight:
    """Validated coordinates and bounded classification; build_plan accepts only this type."""

    coordinates: Coordinates
    inventory: Inventory
    mode: str
    source: str
    classification: tuple[tuple[str, object], ...]
    degraded_metrics_supported: bool


@dataclass(frozen=True)
class QuotaEvidence:
    """Bounded aggregate route evidence produced by an authoritative observer."""

    root_status: int
    metadata_status: int
    livez_status: int
    healthz_status: int
    quota_validator_success: bool


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mode", choices=MODES, required=True)
    for name in (
        "host",
        "context",
        "environment",
        "namespace",
        "deployment",
        "container",
        "current-image",
        "replacement-image",
        "rollback-image",
        "memory-limit",
        "service-monitor",
        "run-id",
    ):
        result.add_argument(f"--{name}", required=True)
    result.add_argument("--kubeconfig", required=True, type=Path)
    result.add_argument("--replicas", required=True, type=int)
    result.add_argument("--snapshot", required=True, type=Path)
    result.add_argument("--evidence", required=True, type=Path)
    result.add_argument("--acknowledge-state-loss", action="store_true")
    result.add_argument("--dry-run", action="store_true", required=True)
    return result


def validate(args: argparse.Namespace) -> Coordinates:
    if args.environment != "staging" or args.context != "sugar-staging":
        raise DrillError("an explicit staging environment and sugar-staging context are required")
    if not args.kubeconfig.is_file():
        raise DrillError("kubeconfig is missing or is not a regular file")
    if not isinstance(args.host, str) or args.host.strip().lower().rstrip(".") != STAGING_HOST:
        raise DrillError("host must be the canonical token.place staging host")
    if args.replicas < 1:
        raise DrillError("replica count must be positive")
    for field in ("current_image", "replacement_image", "rollback_image"):
        if not IMAGE.fullmatch(getattr(args, field)):
            raise DrillError(f"{field.replace('_', ' ')} must use an immutable sha256 digest")
    if len({args.current_image, args.replacement_image, args.rollback_image}) != 3:
        raise DrillError("current, replacement, and rollback images must be distinct")
    if not re.fullmatch(r"[1-9][0-9]*(Mi|Gi)", args.memory_limit):
        raise DrillError("memory limit must be an explicit positive Mi or Gi quantity")
    for field in ("namespace", "deployment", "container", "service_monitor", "run_id"):
        if not SAFE_NAME.fullmatch(str(getattr(args, field))):
            raise DrillError(f"{field.replace('_', ' ')} is not an exact safe Kubernetes name")
    if not args.acknowledge_state_loss:
        raise DrillError(
            "explicit authorization for process-local and emptyDir state loss is required"
        )
    if args.evidence.exists():
        raise DrillError("evidence file must not already exist")
    return Coordinates(
        **{field: getattr(args, field) for field in Coordinates.__dataclass_fields__}
    )


def inventory(environment: str) -> Inventory:
    quota = yaml.safe_load((ROOT / "config/observability/probe-quotas.yaml").read_text())
    matches = [
        p
        for p in quota["probes"]
        if p["application"] == "tokenplace" and p["environment"] == environment
    ]
    route_classes = [p["route_class"] for p in matches]
    if len(route_classes) != len(set(route_classes)):
        raise DrillError("token.place quota inventory contains duplicate route classes")
    selected = {p["route_class"]: p for p in matches}
    expected = {
        "root": ("/", "GET"),
        "metadata": ("/api/v1/meta", "GET"),
        "livez": ("/livez", "GET"),
        "healthz": ("/healthz", "GET"),
    }
    if set(selected) != set(expected) or any(
        (selected[k]["route"], selected[k]["method"]) != v for k, v in expected.items()
    ):
        raise DrillError("token.place quota inventory is missing, ambiguous, or mismatched")
    metrics = json.loads((ROOT / "platform/observability/app-metrics.json").read_text())
    item = metrics["applications"]["tokenplace"]["environments"][environment]
    return Inventory(
        item["namespace"],
        item["serviceMonitorName"],
        tuple(sorted(item["serviceMonitor"]["selectorMatchLabels"].items())),
        tuple((k, selected[k]["probe"], *expected[k]) for k in expected),
    )


def _validate_snapshot(
    mode: str, c: Coordinates, inv: Inventory, snapshot: dict, source: str
) -> Preflight:
    if c.namespace != inv.namespace or c.service_monitor != inv.service_monitor:
        raise DrillError("ServiceMonitor coordinate differs from authoritative inventory")
    deployment = snapshot.get("deployment", {})
    expected_deployment = {
        "namespace": c.namespace,
        "name": c.deployment,
        "container": c.container,
        "replicas": c.replicas,
        "image": c.current_image,
        "memory_limit": c.memory_limit,
    }
    if any(deployment.get(k) != v for k, v in expected_deployment.items()):
        raise DrillError("live Deployment coordinates do not match reviewed coordinates")
    monitor = snapshot.get("service_monitor", {})
    if (
        monitor.get("namespace") != inv.namespace
        or monitor.get("name") != inv.service_monitor
        or monitor.get("selector_labels") != dict(inv.selector_labels)
    ):
        raise DrillError("live ServiceMonitor coordinates do not match inventory")
    live_probes = snapshot.get("probes")
    expected_probes = [
        {"namespace": "monitoring", "name": name, "route": route, "method": method}
        for _, name, route, method in inv.probes
    ]
    if (
        not isinstance(live_probes, list)
        or len(live_probes) != 4
        or sorted(live_probes, key=lambda p: p.get("name", ""))
        != sorted(expected_probes, key=lambda p: p["name"])
    ):
        raise DrillError("live Probe coordinates do not match inventory")
    evidence = snapshot.get("classification", {})
    if mode == "metrics-oom":
        if evidence.get("termination_reason") != "OOMKilled" or evidence.get("exit_code") != 137:
            raise DrillError("metrics-OOM classification requires OOMKilled with exit code 137")
        classification = (("termination_reason", "OOMKilled"), ("exit_code", 137))
    else:
        statuses = evidence.get("route_statuses")
        if (
            statuses != {"root": 429, "metadata": 429, "livez": 200, "healthz": 200}
            or evidence.get("quota_validator_success") is not True
        ):
            raise DrillError(
                "quota classification requires bounded 429/healthy evidence and validator success"
            )
        classification = (
            ("root_status", 429),
            ("metadata_status", 429),
            ("livez_status", 200),
            ("healthz_status", 200),
            ("quota_validator_success", True),
        )
    capability = deployment.get("metrics_mode")
    if capability not in (None, {"normal": "normal", "degraded": "degraded"}):
        raise DrillError("degraded metrics capability is not the supported reviewed contract")
    return Preflight(c, inv, mode, source, classification, capability is not None)


def preflight_snapshot(mode: str, c: Coordinates, snapshot: dict) -> Preflight:
    return _validate_snapshot(
        mode, c, inventory(c.environment), snapshot, "offline-reviewed-snapshot"
    )


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def preflight_live(
    mode: str,
    c: Coordinates,
    runner: Runner,
    quota_evidence: QuotaEvidence | None = None,
) -> Preflight:
    """Run authoritative identity first, then read the five exact live targets."""
    identity = [
        sys.executable,
        str(ROOT / "scripts/cluster_identity.py"),
        "assert",
        "--kubeconfig",
        str(c.kubeconfig),
        "--env",
        "staging",
    ]
    result = runner(identity)
    if result.returncode:
        raise DrillError("authoritative staging identity assertion failed")
    base = ["kubectl", "--kubeconfig", str(c.kubeconfig), "--context", c.context]
    requests = [
        (c.namespace, "deployment", c.deployment),
        (c.namespace, "servicemonitor", "tokenplace"),
    ]
    requests += [("monitoring", "probe", name) for _, name, _, _ in inventory(c.environment).probes]
    objects = []
    for namespace, kind, name in requests:
        result = runner(base + ["--namespace", namespace, "get", kind, name, "-o", "json"])
        if result.returncode:
            raise DrillError("exact live target lookup failed")
        try:
            objects.append(json.loads(result.stdout))
        except json.JSONDecodeError as exc:
            raise DrillError("exact live target returned invalid JSON") from exc
    snapshot = _normalise_live(c, objects)
    if mode == "quota-exhaustion":
        if not isinstance(quota_evidence, QuotaEvidence):
            raise DrillError("typed authoritative quota evidence is required")
        snapshot["classification"] = {
            "route_statuses": {
                "root": quota_evidence.root_status,
                "metadata": quota_evidence.metadata_status,
                "livez": quota_evidence.livez_status,
                "healthz": quota_evidence.healthz_status,
            },
            "quota_validator_success": quota_evidence.quota_validator_success,
        }
    return _validate_snapshot(
        mode,
        c,
        inventory(c.environment),
        snapshot,
        "live-authoritative",
    )


def _normalise_live(c: Coordinates, objects: list[dict]) -> dict:
    deployment, monitor, *probes = objects
    containers = (
        deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    )
    selected = [item for item in containers if item.get("name") == c.container]
    if len(selected) != 1:
        raise DrillError("live Deployment selected container is missing or ambiguous")
    container = selected[0]
    terminated = next(
        (
            s.get("lastState", {}).get("terminated", {})
            for s in deployment.get("status", {}).get("containerStatuses", [])
            if s.get("name") == c.container
        ),
        {},
    )
    env = {item.get("name"): item.get("value") for item in container.get("env", [])}
    metrics_mode = (
        {"normal": "normal", "degraded": "degraded"}
        if env.get("TOKENPLACE_METRICS_MODE") in {"normal", "degraded"}
        else None
    )
    return {
        "deployment": {
            "namespace": deployment.get("metadata", {}).get("namespace"),
            "name": deployment.get("metadata", {}).get("name"),
            "container": c.container,
            "replicas": deployment.get("spec", {}).get("replicas"),
            "image": container.get("image"),
            "memory_limit": container.get("resources", {}).get("limits", {}).get("memory"),
            "metrics_mode": metrics_mode,
        },
        "service_monitor": {
            "namespace": monitor.get("metadata", {}).get("namespace"),
            "name": monitor.get("metadata", {}).get("name"),
            "selector_labels": monitor.get("spec", {}).get("selector", {}).get("matchLabels"),
        },
        "probes": [
            {
                "namespace": p.get("metadata", {}).get("namespace"),
                "name": p.get("metadata", {}).get("name"),
                "route": urlsplit(
                    (
                        (
                            p.get("spec", {})
                            .get("targets", {})
                            .get("staticConfig", {})
                            .get("static")
                            or [""]
                        )[0]
                    )
                ).path
                or "/",
                # The Prometheus Operator Probe CRD performs GET requests; it
                # has no per-Probe HTTP-method field.
                "method": "GET",
            }
            for p in probes
        ],
        "classification": {
            "termination_reason": terminated.get("reason"),
            "exit_code": terminated.get("exitCode"),
        },
    }


def build_plan(preflight: Preflight) -> dict:
    if not isinstance(preflight, Preflight):
        raise DrillError("a typed validated preflight is required")
    c, probes, mode = preflight.coordinates, preflight.inventory.probe_map(), preflight.mode
    kubectl = ["kubectl", "--kubeconfig", "<supplied-kubeconfig>", "--context", c.context]
    prefix, probe_prefix = kubectl + ["--namespace", c.namespace], kubectl + [
        "--namespace",
        "monitoring",
    ]
    root, metadata = probes["root"]["probe"], probes["metadata"]["probe"]
    actions = []

    def add(stage, resource, command, rollback=None):
        actions.append(
            {"stage": stage, "resource": resource, "command": command, "rollback": rollback or []}
        )

    if mode == "metrics-oom" and preflight.degraded_metrics_supported:
        add(
            "pause",
            f"deployment/{c.deployment}",
            prefix
            + ["set", "env", f"deployment/{c.deployment}", "TOKENPLACE_METRICS_MODE=degraded"],
            prefix + ["set", "env", f"deployment/{c.deployment}", "TOKENPLACE_METRICS_MODE=normal"],
        )
        containment = "degraded-metrics"
    elif mode == "metrics-oom":
        target, base, kind = c.service_monitor, prefix, "servicemonitor"
        add(
            "pause",
            f"{kind}/{target}",
            base
            + [
                "label",
                f"{kind}/{target}",
                "release-",
                "sugarkube.dev/incident-paused=true",
                "--overwrite",
            ],
            base
            + [
                "label",
                f"{kind}/{target}",
                "release=kube-prometheus-stack",
                "sugarkube.dev/incident-paused-",
                "--overwrite",
            ],
        )
        containment = "servicemonitor-fallback"
    else:
        containment = "public-probe-pause"
        for target in (root, metadata):
            add(
                "pause",
                f"probe/{target}",
                probe_prefix
                + [
                    "label",
                    f"probe/{target}",
                    "release-",
                    "sugarkube.dev/incident-paused=true",
                    "--overwrite",
                ],
                probe_prefix
                + [
                    "label",
                    f"probe/{target}",
                    "release=kube-prometheus-stack",
                    "sugarkube.dev/incident-paused-",
                    "--overwrite",
                ],
            )
    add(
        "replace",
        f"deployment/{c.deployment}",
        prefix
        + ["set", "image", f"deployment/{c.deployment}", f"{c.container}={c.replacement_image}"],
        prefix
        + ["set", "image", f"deployment/{c.deployment}", f"{c.container}={c.rollback_image}"],
    )
    return {
        "schema_version": 2,
        "mode": mode,
        "run_id": c.run_id,
        "environment": "staging",
        "dry_run": True,
        "non_executing_preview": preflight.source != "live-authoritative",
        "preflight": {
            "authoritative_identity": preflight.source,
            "coordinates_compared": True,
            "classification": dict(preflight.classification),
            "containment": containment,
        },
        "expected_deployment": {
            "replicas": c.replicas,
            "container": c.container,
            "current_image": c.current_image,
            "replacement_image": c.replacement_image,
            "rollback_image": c.rollback_image,
            "memory_limit": c.memory_limit,
        },
        "inventory": {
            "namespace": c.namespace,
            "service_monitor": c.service_monitor,
            "probes": probes,
        },
        "state_changes": {
            "cluster": False,
            "production": False,
            "repository": False,
            "external": False,
        },
        "actions": actions,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        coordinates = validate(args)
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        plan = build_plan(preflight_snapshot(args.mode, coordinates, snapshot))
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(plan, indent=2))
        return 0
    except DrillError as exc:
        print(f"token.place incident drill refused: {exc}", file=sys.stderr)
        return 2
    except (OSError, KeyError, TypeError, json.JSONDecodeError, yaml.YAMLError):
        print("token.place incident drill refused: precondition validation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
