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
    metrics_mode_state: str
    discovery_labels: tuple[tuple[str, str], ...]


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
    if args.current_image == args.replacement_image:
        raise DrillError("current and replacement images must be distinct")
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
        or monitor.get("discovery_label") != "kube-prometheus-stack"
        or monitor.get("incident_pause_label") is not None
    ):
        raise DrillError("live ServiceMonitor coordinates do not match inventory")
    live_probes = snapshot.get("probes")
    expected_probes = [
        {
            "namespace": "monitoring",
            "name": name,
            "route": route,
            "method": method,
            "discovery_label": "kube-prometheus-stack",
            "incident_pause_label": None,
        }
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
    metrics_mode_state = deployment.get("metrics_mode_value", "normal" if capability else "absent")
    if metrics_mode_state not in ({"normal", "degraded"} if capability else {"absent"}):
        raise DrillError("current metrics mode cannot be inverted exactly")
    discovery_labels = [("servicemonitor", monitor["discovery_label"])] + [
        (probe["name"], probe["discovery_label"]) for probe in live_probes
    ]
    return Preflight(
        c, inv, mode, source, classification, metrics_mode_state, tuple(discovery_labels)
    )


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
            "metrics_mode_value": env.get("TOKENPLACE_METRICS_MODE", "absent"),
        },
        "service_monitor": {
            "namespace": monitor.get("metadata", {}).get("namespace"),
            "name": monitor.get("metadata", {}).get("name"),
            "selector_labels": monitor.get("spec", {}).get("selector", {}).get("matchLabels"),
            "discovery_label": monitor.get("metadata", {}).get("labels", {}).get("release"),
            "incident_pause_label": monitor.get("metadata", {})
            .get("labels", {})
            .get("sugarkube.dev/incident-paused"),
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
                "discovery_label": p.get("metadata", {}).get("labels", {}).get("release"),
                "incident_pause_label": p.get("metadata", {})
                .get("labels", {})
                .get("sugarkube.dev/incident-paused"),
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
    actions: list[dict] = []
    previous: str | None = None

    def mutation(stage, resource, command, inverse, old_state, recovery_fallback=None):
        nonlocal previous
        record = {
            "id": stage,
            "stage": stage,
            "type": "mutation",
            "depends_on": [previous] if previous else [],
            "resource": resource,
            "old_state": old_state,
            "command": command,
            "inverse": inverse,
            "rollback": inverse,
        }
        if recovery_fallback:
            record["recovery_fallback"] = recovery_fallback
        actions.append(record)
        previous = stage
        return record

    def gate(stage, checks, on_failure, duration=0, preserves=()):
        nonlocal previous
        actions.append(
            {
                "id": stage,
                "stage": stage,
                "type": "gate",
                "depends_on": [previous] if previous else [],
                "duration": {"value": duration, "unit": "minutes"},
                "checks": checks,
                "preserves": list(preserves),
                "on_failure": on_failure,
            }
        )
        previous = stage

    discovery = dict(preflight.discovery_labels)
    paused: dict[str, dict] = {}

    def pause_label(stage, kind, target, base):
        old = discovery["servicemonitor" if kind == "servicemonitor" else target]
        pause = base + [
            "label",
            f"{kind}/{target}",
            "release-",
            "sugarkube.dev/incident-paused=true",
            "--overwrite",
        ]
        restore = base + [
            "label",
            f"{kind}/{target}",
            f"release={old}",
            "sugarkube.dev/incident-paused-",
            "--overwrite",
        ]
        paused[target] = mutation(
            stage,
            f"{kind}/{target}",
            pause,
            restore,
            {"release": old, "sugarkube.dev/incident-paused": None},
        )

    if mode == "metrics-oom" and preflight.metrics_mode_state in {"normal", "degraded"}:
        old = preflight.metrics_mode_state
        if old == "normal":
            paused["metrics"] = mutation(
                "pause-metrics",
                f"deployment/{c.deployment}",
                prefix
                + ["set", "env", f"deployment/{c.deployment}", "TOKENPLACE_METRICS_MODE=degraded"],
                prefix
                + ["set", "env", f"deployment/{c.deployment}", f"TOKENPLACE_METRICS_MODE={old}"],
                {"TOKENPLACE_METRICS_MODE": old},
            )
        containment = "degraded-metrics"
    elif mode == "metrics-oom":
        pause_label("pause-metrics", "servicemonitor", c.service_monitor, prefix)
        containment = "servicemonitor-fallback"
    else:
        containment = "public-probe-pause"
        pause_label("pause-root", "probe", root, probe_prefix)
        pause_label("pause-metadata", "probe", metadata, probe_prefix)
    replace_inverse = prefix + [
        "set",
        "image",
        f"deployment/{c.deployment}",
        f"{c.container}={c.current_image}",
    ]
    mutation(
        "replace",
        f"deployment/{c.deployment}",
        prefix
        + ["set", "image", f"deployment/{c.deployment}", f"{c.container}={c.replacement_image}"],
        replace_inverse,
        {"image": c.current_image},
        {
            "kind": "reviewed-recovery-fallback",
            "not_an_inverse": True,
            "requires_capability_revalidation": True,
            "command": prefix
            + [
                "set",
                "image",
                f"deployment/{c.deployment}",
                f"{c.container}={c.rollback_image}",
            ],
        },
    )
    gate(
        "workload-readiness",
        [
            {"metric": "ready_replicas", "operator": "eq", "value": c.replicas, "unit": "replicas"},
            {
                "metric": "image_digest",
                "operator": "eq",
                "value": c.replacement_image,
                "unit": "digest",
            },
            {
                "metric": "memory_limit",
                "operator": "eq",
                "value": c.memory_limit,
                "unit": "quantity",
            },
            {"metric": "readiness_failures", "operator": "eq", "value": 0, "unit": "events"},
            {"metric": "restart_increase", "operator": "eq", "value": 0, "unit": "restarts"},
            {"metric": "new_oomkilled_137", "operator": "eq", "value": 0, "unit": "terminations"},
        ],
        replace_inverse,
        duration=5,
    )
    gate(
        "compute-registration",
        [{"metric": "registered", "operator": "eq", "value": True, "unit": "boolean"}],
        replace_inverse,
    )
    gate(
        "compute-polling",
        [{"metric": "polling_resumed", "operator": "eq", "value": True, "unit": "boolean"}],
        replace_inverse,
    )
    gate(
        "encrypted-e2ee",
        [
            {"metric": step, "operator": "eq", "value": True, "unit": "boolean"}
            for step in (
                "encrypted_request",
                "encrypted_response",
                "retrieval",
                "client_decryption",
            )
        ],
        replace_inverse,
    )

    common = [
        {"metric": "readiness_failures", "operator": "eq", "value": 0, "unit": "events"},
        {"metric": "restart_increase", "operator": "eq", "value": 0, "unit": "restarts"},
        {"metric": "new_oomkilled_137", "operator": "eq", "value": 0, "unit": "terminations"},
        {
            "metric": "route_429_rate",
            "operator": "lte",
            "value": 1,
            "unit": "percent",
            "window": {"value": 5, "unit": "minutes"},
        },
        {
            "metric": "route_5xx_rate",
            "operator": "lte",
            "value": 1,
            "unit": "percent",
            "window": {"value": 5, "unit": "minutes"},
        },
        {"metric": "scrape_health", "operator": "eq", "value": 100, "unit": "percent"},
        {
            "metric": "active_series_vs_baseline",
            "operator": "lte",
            "value": 10,
            "unit": "percent_above_baseline",
        },
        {
            "metric": "scrape_samples_vs_baseline",
            "operator": "lte",
            "value": 10,
            "unit": "percent_above_baseline",
        },
        {
            "metric": "memory_working_set",
            "operator": "lt",
            "value": 85,
            "unit": "percent_of_limit",
            "window": {"value": 5, "unit": "minutes"},
        },
    ]
    if mode == "quota-exhaustion":
        gate(
            "quota-validator",
            [
                {
                    "metric": "quota_contract_valid",
                    "operator": "eq",
                    "value": True,
                    "unit": "boolean",
                    "argv": [
                        "python3",
                        "scripts/validate_probe_quotas.py",
                        "--env",
                        "staging",
                        "--probes",
                        "clusters/staging/observability/probes/public-apps.yaml",
                    ],
                }
            ],
            {
                "outcome": "hold-current-containment",
                "root": "paused",
                "metadata": "paused",
                "mutation": None,
            },
        )
        for label, target in (("root", root), ("metadata", metadata)):
            paused_action = paused[target]
            restore = mutation(
                f"restore-{label}",
                paused_action["resource"],
                paused_action["inverse"],
                paused_action["command"],
                {"release": None, "sugarkube.dev/incident-paused": "true"},
            )
            gate(
                f"observe-{label}",
                common,
                restore["inverse"],
                duration=15,
                preserves=("probe/livez", "probe/healthz"),
            )
    else:
        gate(
            "preserve-root",
            [{"metric": "discovery_unchanged", "operator": "eq", "value": True, "unit": "boolean"}],
            replace_inverse,
            duration=15,
            preserves=(f"probe/{root}", "probe/livez", "probe/healthz"),
        )
        gate(
            "preserve-metadata",
            [{"metric": "discovery_unchanged", "operator": "eq", "value": True, "unit": "boolean"}],
            replace_inverse,
            duration=15,
            preserves=(f"probe/{metadata}", "probe/livez", "probe/healthz"),
        )
    metrics_rollback = replace_inverse
    metrics_was_paused = "metrics" in paused or c.service_monitor in paused
    if mode == "metrics-oom" and metrics_was_paused:
        metrics_exit_checks = common
        if c.service_monitor in paused:
            # Prometheus cannot observe a target while its ServiceMonitor discovery
            # label is paused.  Direct authenticated evidence is available before
            # restoration; discovered scrape health is verified afterwards.
            metrics_exit_checks = [check for check in common if check["metric"] != "scrape_health"]
        gate(
            "metrics-exit",
            metrics_exit_checks
            + [
                {
                    "metric": "authenticated_scrape",
                    "operator": "eq",
                    "value": True,
                    "unit": "boolean",
                    "source": "direct-authenticated-target",
                },
                {
                    "metric": "memory_working_set",
                    "operator": "lt",
                    "value": 70,
                    "unit": "percent_of_limit",
                    "window": {"value": 15, "unit": "minutes"},
                },
            ],
            {
                "outcome": "hold-current-containment",
                "metrics": "paused",
                "mutation": None,
            },
            duration=15,
        )
    if "metrics" in paused:
        restore = mutation(
            "restore-metrics",
            paused["metrics"]["resource"],
            paused["metrics"]["inverse"],
            paused["metrics"]["command"],
            {"TOKENPLACE_METRICS_MODE": "degraded"},
        )
        metrics_rollback = restore["inverse"]
    elif c.service_monitor in paused:
        restore = mutation(
            "restore-metrics",
            paused[c.service_monitor]["resource"],
            paused[c.service_monitor]["inverse"],
            paused[c.service_monitor]["command"],
            {"release": None, "sugarkube.dev/incident-paused": "true"},
        )
        metrics_rollback = restore["inverse"]
    else:
        gate(
            "preserve-metrics-last",
            [{"metric": "discovery_unchanged", "operator": "eq", "value": True, "unit": "boolean"}],
            replace_inverse,
            preserves=(f"servicemonitor/{c.service_monitor}",),
        )
    exit_checks = common + [
        {
            "metric": "memory_working_set",
            "operator": "lt",
            "value": 70,
            "unit": "percent_of_limit",
            "window": {"value": 15, "unit": "minutes"},
        }
    ]
    gate(
        "observe-metrics",
        exit_checks,
        metrics_rollback,
        duration=30,
        preserves=("probe/livez", "probe/healthz"),
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
