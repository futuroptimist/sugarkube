#!/usr/bin/env python3
"""Build a fail-closed, privacy-safe token.place staging incident drill plan."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
SAFE_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
IMAGE = re.compile(r"[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}")
MODES = ("metrics-oom", "quota-exhaustion")
LIFECYCLES = ("real-incident", "staging-rehearsal")
STAGING_HOST = "staging.token.place"
EXECUTION_OPERATIONS = ("--execute-stage", "--rollback-stage", "--cleanup")
GATE_EVIDENCE_MAX_BYTES = 64 * 1024
GATE_EVIDENCE_FRESHNESS_SECONDS = 5 * 60
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


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
    lifecycle: str = "real-incident"
    incident_image: str | None = None


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


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mode", choices=MODES, required=True)
    result.add_argument("--lifecycle", choices=LIFECYCLES, default="real-incident")
    result.add_argument("--incident-image")
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
    preflight = result.add_mutually_exclusive_group(required=True)
    preflight.add_argument("--snapshot", type=Path)
    preflight.add_argument("--live-preflight", action="store_true")
    result.add_argument("--evidence", required=True, type=Path)
    result.add_argument("--acknowledge-state-loss", action="store_true")
    result.add_argument("--acknowledge-staging-fault-injection", action="store_true")
    result.add_argument("--dry-run", action="store_true", required=True)
    return result


def execution_parser() -> argparse.ArgumentParser:
    """Parse the deliberately separate mutation/resume interface."""
    result = argparse.ArgumentParser(description="Execute one validated staging drill stage")
    operation = result.add_mutually_exclusive_group(required=True)
    operation.add_argument("--execute-stage")
    operation.add_argument("--rollback-stage")
    operation.add_argument("--cleanup", action="store_true")
    result.add_argument("--plan", required=True, type=Path)
    result.add_argument("--journal", required=True, type=Path)
    result.add_argument("--kubeconfig", required=True, type=Path)
    result.add_argument("--gate-evidence", type=Path)
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
    lifecycle = getattr(args, "lifecycle", "real-incident")
    incident_image = getattr(args, "incident_image", None)
    if lifecycle == "staging-rehearsal":
        if args.mode != "metrics-oom":
            raise DrillError("staging rehearsal is supported only for metrics-OOM")
        if not IMAGE.fullmatch(incident_image or ""):
            raise DrillError(
                "incident image must use a separately supplied immutable sha256 digest"
            )
        if not getattr(args, "acknowledge_staging_fault_injection", False):
            raise DrillError("explicit staging fault-injection authorization is required")
        if (
            len({args.current_image, incident_image, args.replacement_image, args.rollback_image})
            != 4
        ):
            raise DrillError("baseline, incident, recovery, and fallback images must be distinct")
    elif incident_image is not None or getattr(args, "acknowledge_staging_fault_injection", False):
        raise DrillError("rehearsal stimulus controls require staging-rehearsal lifecycle")
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
    _validate_evidence_target(args.evidence)
    values = {
        field: getattr(args, field)
        for field in Coordinates.__dataclass_fields__
        if hasattr(args, field)
    }
    values.update(lifecycle=lifecycle, incident_image=incident_image)
    return Coordinates(**values)


def _validate_evidence_target(target: Path) -> None:
    """Require a new private evidence file outside the repository."""
    if not target.is_absolute():
        raise DrillError("evidence target must be an absolute private path")
    if target.is_symlink() or target.exists():
        raise DrillError("evidence target must be a new regular file")
    try:
        parent = target.parent.resolve(strict=True)
        resolved_target = target.resolve(strict=False)
        root = ROOT.resolve(strict=True)
    except (OSError, RuntimeError):
        raise DrillError("evidence target cannot be safely resolved") from None
    if not parent.is_dir():
        raise DrillError("evidence parent must be an existing directory")
    if parent == root or parent.is_relative_to(root):
        raise DrillError("evidence target must be outside the repository")
    if resolved_target == root or resolved_target.is_relative_to(root):
        raise DrillError("evidence target must be outside the repository")


def _publish_evidence(target: Path, payload: str) -> None:
    """Durably publish payload with mode 0600 without replacing another record."""
    fd = -1
    temporary: Path | None = None
    published = False
    try:
        fd, name = tempfile.mkstemp(prefix=".tokenplace-evidence-", dir=target.parent)
        temporary = Path(name)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        published = True
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if published:
            try:
                target.unlink()
            except OSError:
                pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


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
    if mode == "metrics-oom" and c.lifecycle == "real-incident":
        if evidence.get("termination_reason") != "OOMKilled" or evidence.get("exit_code") != 137:
            raise DrillError("metrics-OOM classification requires OOMKilled with exit code 137")
        classification_items = [("termination_reason", "OOMKilled"), ("exit_code", 137)]
        if source == "live-authoritative":
            for key in ("restart_count", "termination_time", "event_aggregates"):
                classification_items.append((key, evidence[key]))
        classification = tuple(classification_items)
    elif mode == "quota-exhaustion":
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
    else:
        if evidence:
            raise DrillError("healthy rehearsal preflight must not assert synthetic OOM evidence")
        classification = (("oom_status", "not-yet-observed"),)
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
) -> Preflight:
    """Run authoritative identity first, then derive bounded live evidence."""
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
    deployment = objects[0]
    if mode == "metrics-oom" and c.lifecycle == "real-incident":
        snapshot["classification"] = _observe_live_oom(c, deployment, base, runner)
    if mode == "quota-exhaustion":
        snapshot["classification"] = _observe_live_quota(runner)
    if c.lifecycle == "staging-rehearsal":
        status = deployment.get("status", {})
        if (
            status.get("readyReplicas", 0) != c.replicas
            or status.get("availableReplicas", 0) != c.replicas
        ):
            raise DrillError("healthy rehearsal baseline is not ready")
    return _validate_snapshot(
        mode,
        c,
        inventory(c.environment),
        snapshot,
        "live-authoritative",
    )


def _runner_json(runner: Runner, command: list[str], error: str) -> dict:
    result = runner(command)
    if result.returncode:
        raise DrillError(error)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DrillError(error) from exc
    if not isinstance(value, dict):
        raise DrillError(error)
    return value


def _observe_live_oom(
    c: Coordinates,
    deployment: dict,
    base: list[str],
    runner: Runner,
    *,
    not_before: datetime | None = None,
) -> dict:
    metadata = deployment.get("metadata", {})
    deployment_uid = metadata.get("uid")
    selector_labels = deployment.get("spec", {}).get("selector", {}).get("matchLabels")
    if not deployment_uid or not isinstance(selector_labels, dict) or not selector_labels:
        raise DrillError("Deployment ownership selector is missing or malformed")
    if any(
        not re.fullmatch(r"[A-Za-z0-9./_-]+", str(k))
        or not re.fullmatch(r"[A-Za-z0-9._-]+", str(v))
        for k, v in selector_labels.items()
    ):
        raise DrillError("Deployment ownership selector is unsafe")
    selector = ",".join(f"{key}={selector_labels[key]}" for key in sorted(selector_labels))
    namespace = ["--namespace", c.namespace]
    replicasets = _runner_json(
        runner,
        base + namespace + ["get", "replicasets", "-l", selector, "-o", "json"],
        "Deployment-owned ReplicaSet observation failed",
    ).get("items")
    if not isinstance(replicasets, list):
        raise DrillError("ReplicaSet observation is malformed")
    replica_uids = set()
    for item in replicasets:
        if _controller_uid(item) != deployment_uid:
            continue
        containers = item.get("spec", {}).get("template", {}).get("spec", {}).get("containers")
        if not isinstance(containers, list):
            continue
        selected = [container for container in containers if container.get("name") == c.container]
        if len(selected) != 1:
            continue
        container = selected[0]
        if (
            container.get("image") == c.current_image
            and container.get("resources", {}).get("limits", {}).get("memory") == c.memory_limit
            and item.get("metadata", {}).get("uid")
        ):
            replica_uids.add(item["metadata"]["uid"])
    if not replica_uids:
        raise DrillError("current ReplicaSet observation is missing")
    pods = _runner_json(
        runner,
        base + namespace + ["get", "pods", "-l", selector, "-o", "json"],
        "Deployment-owned Pod observation failed",
    ).get("items")
    if not isinstance(pods, list):
        raise DrillError("Pod observation is malformed")
    if len(pods) != c.replicas:
        raise DrillError("current workload replica count is unconverged")
    candidates = []
    for pod in pods:
        if _controller_uid(pod) not in replica_uids:
            raise DrillError("Pod observation contains stale or wrong ownership")
        if pod.get("metadata", {}).get("deletionTimestamp") is not None:
            raise DrillError("Pod observation contains a terminating workload member")
        containers = pod.get("spec", {}).get("containers")
        if not isinstance(containers, list):
            raise DrillError("Pod container specification is malformed")
        selected_specs = [
            container for container in containers if container.get("name") == c.container
        ]
        if len(selected_specs) != 1:
            raise DrillError("selected Pod container specification is missing or ambiguous")
        selected_spec = selected_specs[0]
        if (
            selected_spec.get("image") != c.current_image
            or selected_spec.get("resources", {}).get("limits", {}).get("memory") != c.memory_limit
        ):
            raise DrillError("Pod container coordinates do not match reviewed coordinates")
        statuses = pod.get("status", {}).get("containerStatuses")
        if not isinstance(statuses, list):
            raise DrillError("Pod container status observation is malformed")
        selected = [status for status in statuses if status.get("name") == c.container]
        if len(selected) != 1:
            raise DrillError("selected Pod container status is missing or ambiguous")
        status = selected[0]
        terminated = status.get("lastState", {}).get("terminated")
        if not isinstance(terminated, dict):
            continue
        if terminated.get("reason") != "OOMKilled" or terminated.get("exitCode") != 137:
            continue
        if not isinstance(status.get("restartCount"), int) or status["restartCount"] <= 0:
            raise DrillError("OOM termination restart evidence is malformed")
        finished = terminated.get("finishedAt")
        try:
            parsed = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise DrillError("OOM termination timestamp is malformed") from exc
        if parsed.tzinfo is None:
            raise DrillError("OOM termination timestamp is malformed")
        if not_before is not None and parsed < not_before:
            raise DrillError("OOM termination predates the controlled stimulus")
        candidates.append((pod, finished, status["restartCount"]))
    if len(candidates) != 1:
        raise DrillError("metrics-OOM evidence is missing or ambiguous")
    pod, finished, restart_count = candidates[0]
    pod_uid = pod.get("metadata", {}).get("uid")
    if not pod_uid:
        raise DrillError("affected Pod identity is malformed")
    events = _runner_json(
        runner,
        base
        + namespace
        + ["get", "events", "--field-selector", f"involvedObject.uid={pod_uid}", "-o", "json"],
        "affected Pod event observation failed",
    ).get("items")
    if not isinstance(events, list):
        raise DrillError("affected Pod event observation is malformed")
    aggregates = []
    for event in events:
        reason = event.get("reason")
        count = event.get("count", 1)
        first = event.get("firstTimestamp") or event.get("eventTime")
        last = event.get("lastTimestamp") or event.get("eventTime")
        if reason and SAFE_NAME.fullmatch(reason.lower()) and isinstance(count, int):
            aggregates.append({"reason": reason, "count": count, "first": first, "last": last})
    return {
        "termination_reason": "OOMKilled",
        "exit_code": 137,
        "restart_count": restart_count,
        "termination_time": finished,
        "event_aggregates": aggregates,
    }


def _controller_uid(obj: dict) -> object:
    owners = obj.get("metadata", {}).get("ownerReferences")
    if not isinstance(owners, list):
        return None
    controllers = [owner.get("uid") for owner in owners if owner.get("controller") is True]
    return controllers[0] if len(controllers) == 1 else None


def _observe_live_quota(runner: Runner) -> dict:
    validator = [
        sys.executable,
        str(ROOT / "scripts/validate_probe_quotas.py"),
        "--env",
        "staging",
        "--probes",
        str(ROOT / "clusters/staging/observability/probes/public-apps.yaml"),
    ]
    if runner(validator).returncode:
        raise DrillError("staging quota validation failed")
    statuses = {}
    for route, path in (
        ("root", "/"),
        ("metadata", "/api/v1/meta"),
        ("livez", "/livez"),
        ("healthz", "/healthz"),
    ):
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--max-time",
            "10",
            f"https://{STAGING_HOST}{path}",
        ]
        result = runner(command)
        try:
            statuses[route] = int(result.stdout.strip()) if result.returncode == 0 else 0
        except ValueError as exc:
            raise DrillError("status-only route observation failed") from exc
    return {"route_statuses": statuses, "quota_validator_success": True}


def _normalise_live(c: Coordinates, objects: list[dict]) -> dict:
    deployment, monitor, *probes = objects
    containers = (
        deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    )
    selected = [item for item in containers if item.get("name") == c.container]
    if len(selected) != 1:
        raise DrillError("live Deployment selected container is missing or ambiguous")
    container = selected[0]
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
        "classification": {},
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

    if c.lifecycle == "staging-rehearsal":
        baseline_inverse = prefix + [
            "set",
            "image",
            f"deployment/{c.deployment}",
            f"{c.container}={c.current_image}",
        ]
        mutation(
            "inject-oom-stimulus",
            f"deployment/{c.deployment}",
            prefix
            + ["set", "image", f"deployment/{c.deployment}", f"{c.container}={c.incident_image}"],
            baseline_inverse,
            {"image": c.current_image},
        )["baseline_idempotent_inverse"] = True
        gate(
            "observe-authentic-oom",
            [
                {
                    "metric": "authoritative_live_oomkilled_137",
                    "operator": "eq",
                    "value": True,
                    "unit": "boolean",
                }
            ],
            baseline_inverse,
        )

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
        {"image": c.incident_image if c.lifecycle == "staging-rehearsal" else c.current_image},
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
    plan = {
        "schema_version": 2,
        "mode": mode,
        "lifecycle": c.lifecycle,
        "run_id": c.run_id,
        "environment": "staging",
        "dry_run": True,
        "non_executing_preview": preflight.source != "live-authoritative",
        "preflight": {
            "authoritative_identity": preflight.source,
            "coordinates_compared": True,
            "classification": dict(preflight.classification),
            "offline_fixture_authoritative": False,
            "containment": containment,
        },
        "expected_deployment": {
            "replicas": c.replicas,
            "container": c.container,
            "current_image": c.current_image,
            "incident_image": c.incident_image,
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
    plan["plan_digest"] = _plan_digest(plan)
    return plan


def _plan_digest(plan: dict) -> str:
    unsigned = {key: value for key, value in plan.items() if key != "plan_digest"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_execution_plan(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrillError("immutable plan cannot be read") from exc
    if not isinstance(plan, dict) or plan.get("schema_version") != 2:
        raise DrillError("unsupported plan schema")
    if plan.get("environment") != "staging" or plan.get("run_id") is None:
        raise DrillError("execution is restricted to a named staging run")
    if plan.get("lifecycle", "real-incident") not in LIFECYCLES:
        raise DrillError("plan lifecycle is unsupported")
    if (
        plan.get("lifecycle") == "staging-rehearsal"
        and plan.get("non_executing_preview") is not False
    ):
        raise DrillError("offline rehearsal previews cannot be executed")
    if not SAFE_NAME.fullmatch(str(plan["run_id"])):
        raise DrillError("plan run ID is unsafe")
    digest = plan.get("plan_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise DrillError("plan digest is missing or malformed")
    if digest != _plan_digest(plan):
        raise DrillError("immutable plan digest does not match")
    actions = plan.get("actions")
    if not isinstance(actions, list) or not actions:
        raise DrillError("plan has no ordered stages")
    identifiers = [action.get("id") for action in actions if isinstance(action, dict)]
    if len(identifiers) != len(actions) or len(set(identifiers)) != len(actions):
        raise DrillError("plan stages are missing or ambiguous")
    for action in actions:
        for field in ("command", "inverse", "rollback"):
            value = action.get(field)
            if value is not None and (
                not isinstance(value, list)
                or not value
                or not all(isinstance(token, str) and token for token in value)
            ):
                raise DrillError("plan contains a shell-string or malformed command")
    return plan


def _private_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise DrillError(f"{label} must be an absolute private directory")
    try:
        resolved = path.resolve(strict=True)
        root = ROOT.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DrillError(f"{label} cannot be safely resolved") from exc
    if not resolved.is_dir() or resolved == root or resolved.is_relative_to(root):
        raise DrillError(f"{label} must be an existing directory outside the repository")
    return resolved


def _journal_records(directory: Path, plan: dict) -> list[dict]:
    paths = sorted(directory.glob("record-*.json"))
    records = []
    for sequence, path in enumerate(paths):
        if path.name != f"record-{sequence:04d}.json":
            raise DrillError("durable journal sequence has a gap")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DrillError("durable journal is malformed") from exc
        if (
            not isinstance(record, dict)
            or record.get("plan_digest") != plan["plan_digest"]
            or record.get("run_id") != plan["run_id"]
            or record.get("sequence") != sequence
        ):
            raise DrillError("journal ownership does not match the immutable plan")
        records.append(record)
    pending = None
    completed = set()
    aborting = False
    ordered = ["marker"] + [action["id"] for action in plan["actions"]]
    mutations = {action["id"] for action in plan["actions"] if action["type"] == "mutation"}
    gates = {action["id"] for action in plan["actions"] if action["type"] == "gate"}
    executed = []
    active = []
    for record in records:
        phase = record.get("phase")
        operation = record.get("operation")
        stage = record.get("stage")
        key = (operation, stage)
        if phase == "intent":
            if pending is not None or key in completed:
                raise DrillError("journal contains duplicate or conflicting records")
            if operation == "execute":
                if aborting or stage not in ordered or stage != ordered[len(executed)]:
                    raise DrillError("journal contains an invalid forward transition")
            if operation == "rollback":
                if stage not in mutations or not active or active[-1] != stage:
                    raise DrillError("journal contains an invalid rollback transition")
                aborting = True
            if operation == "cleanup" and (stage != "cleanup" or active):
                raise DrillError("journal contains an invalid cleanup transition")
            if operation not in {"execute", "rollback", "cleanup"}:
                raise DrillError("journal operation is invalid")
            pending = key
        elif phase == "completed":
            direct_gate = (
                pending is None
                and operation == "execute"
                and stage in gates
                and not aborting
                and len(executed) < len(ordered)
                and stage == ordered[len(executed)]
            )
            if pending != key and not direct_gate:
                raise DrillError("journal transition is invalid")
            completed.add(key)
            pending = None
            if operation == "execute":
                executed.append(stage)
                if stage in mutations:
                    active.append(stage)
            elif operation == "rollback":
                active.pop()
        elif phase == "expired":
            if pending != key or operation != "execute" or stage not in gates:
                raise DrillError("journal transition is invalid")
            pending = None
        else:
            raise DrillError("journal record transition is invalid")
    return records


def _append_journal(directory: Path, plan: dict, record: dict) -> None:
    sequence = len(_journal_records(directory, plan))
    payload = {
        "schema_version": 1,
        "run_id": plan["run_id"],
        "plan_digest": plan["plan_digest"],
        "sequence": sequence,
        **record,
    }
    target = directory / f"record-{sequence:04d}.json"
    _publish_evidence(target, json.dumps(payload, sort_keys=True) + "\n")


def _marker_name(plan: dict) -> str:
    suffix = plan["plan_digest"][:12]
    return f"tokenplace-drill-{plan['run_id']}-{suffix}"[:63].rstrip("-")


def _bind_command(command: list[str], kubeconfig: Path) -> list[str]:
    bound = [
        str(kubeconfig) if argument == "<supplied-kubeconfig>" else argument for argument in command
    ]
    if bound[0] == "kubectl" and "--kubeconfig" not in bound:
        raise DrillError("kubectl command is not bound to a kubeconfig")
    return bound


def _run_checked(
    runner: Runner, command: list[str], message: str
) -> subprocess.CompletedProcess[str]:
    if not isinstance(command, list) or not all(isinstance(token, str) for token in command):
        raise DrillError("refusing a shell-string command")
    result = runner(command)
    if result.returncode:
        raise DrillError(message)
    return result


def _assert_stage_preflight(
    plan: dict,
    kubeconfig: Path,
    runner: Runner,
    expected_image: str | set[str] | None = None,
) -> None:
    """Reassert authoritative identity and the immutable deployment coordinates."""
    _run_checked(
        runner,
        [
            sys.executable,
            str(ROOT / "scripts/cluster_identity.py"),
            "assert",
            "--kubeconfig",
            str(kubeconfig),
            "--env",
            "staging",
        ],
        "authoritative staging identity assertion failed",
    )
    expected = plan["expected_deployment"]
    namespace = plan["inventory"]["namespace"]
    resource = next(
        (a.get("resource", "") for a in plan["actions"] if a.get("id") == "replace"), ""
    )
    deployment = resource.split("/", 1)[-1]
    result = _run_checked(
        runner,
        [
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "sugar-staging",
            "--namespace",
            namespace,
            "get",
            "deployment",
            deployment,
            "-o",
            "json",
        ],
        "exact deployment preflight failed",
    )
    try:
        value = json.loads(result.stdout)
        spec = value["spec"]
        containers = spec["template"]["spec"]["containers"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DrillError("exact deployment preflight is malformed") from exc
    selected = [item for item in containers if item.get("name") == expected["container"]]
    allowed_images = (
        expected_image
        if isinstance(expected_image, set)
        else (
            {expected_image}
            if expected_image
            else {expected["current_image"], expected["replacement_image"]}
        )
    )
    if (
        spec.get("replicas") != expected["replicas"]
        or len(selected) != 1
        or selected[0].get("resources", {}).get("limits", {}).get("memory")
        != expected["memory_limit"]
        or selected[0].get("image") not in allowed_images
    ):
        raise DrillError("exact deployment coordinates drifted")


def _marker_command(plan: dict, kubeconfig: Path, verb: str) -> list[str]:
    base = [
        "kubectl",
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        "sugar-staging",
        "--namespace",
        plan["inventory"]["namespace"],
    ]
    name = _marker_name(plan)
    if verb == "create":
        return base + [
            "create",
            "configmap",
            name,
            f"--from-literal=run-id={plan['run_id']}",
            f"--from-literal=plan-digest={plan['plan_digest']}",
        ]
    if verb == "get":
        return base + [verb, "configmap", name, "--ignore-not-found", "-o", "json"]
    return base + [verb, "configmap", name]


def _assert_action_prestate(
    plan: dict, action: dict, kubeconfig: Path, runner: Runner, *, inverse: bool = False
) -> None:
    """Compare the exact resource state immediately before a planned mutation."""
    kind, name = action["resource"].split("/", 1)
    namespace = "monitoring" if kind == "probe" else plan["inventory"]["namespace"]
    command = [
        "kubectl",
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        "sugar-staging",
        "--namespace",
        namespace,
        "get",
        kind,
        name,
        "-o",
        "json",
    ]
    observed = _runner_json(runner, command, "stage pre-state lookup failed")
    old = action.get("old_state", {})
    if inverse:
        # An inverse is valid only after the forward command established its
        # known state; labels and image/environment values are tokenized.
        command_tokens = action["command"]
        if "release-" in command_tokens:
            old = {"release": None, "sugarkube.dev/incident-paused": "true"}
        elif "TOKENPLACE_METRICS_MODE=degraded" in command_tokens:
            old = {"TOKENPLACE_METRICS_MODE": "degraded"}
        elif "set" in command_tokens and "image" in command_tokens:
            old = {"image": plan["expected_deployment"]["replacement_image"]}
    if kind in {"probe", "servicemonitor"}:
        labels = observed.get("metadata", {}).get("labels", {})
        if labels.get("release") != old.get("release") or labels.get(
            "sugarkube.dev/incident-paused"
        ) != old.get("sugarkube.dev/incident-paused"):
            raise DrillError("stage monitoring pre-state drifted")
        return
    containers = observed.get("spec", {}).get("template", {}).get("spec", {}).get("containers")
    if not isinstance(containers, list):
        raise DrillError("stage Deployment pre-state is malformed")
    selected = [
        container
        for container in containers
        if container.get("name") == plan["expected_deployment"]["container"]
    ]
    if len(selected) != 1:
        raise DrillError("stage Deployment container is missing or ambiguous")
    container = selected[0]
    if "image" in old and container.get("image") != old["image"]:
        raise DrillError("stage image pre-state drifted")
    if "TOKENPLACE_METRICS_MODE" in old:
        env = {item.get("name"): item.get("value") for item in container.get("env", [])}
        if env.get("TOKENPLACE_METRICS_MODE") != old["TOKENPLACE_METRICS_MODE"]:
            raise DrillError("stage metrics-mode pre-state drifted")


def _validate_marker(plan: dict, kubeconfig: Path, runner: Runner, *, absent_ok=False) -> bool:
    result = runner(_marker_command(plan, kubeconfig, "get"))
    if result.returncode:
        raise DrillError("exact drill marker lookup failed")
    if not result.stdout.strip():
        if absent_ok:
            return False
        raise DrillError("exact drill marker is missing")
    try:
        marker = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DrillError("drill marker is malformed") from exc
    data = marker.get("data", {})
    if data.get("run-id") != plan["run_id"] or data.get("plan-digest") != plan["plan_digest"]:
        raise DrillError("drill marker ownership does not match")
    return True


@contextlib.contextmanager
def _execution_lock(directory: Path):
    """Refuse concurrent writers for one private journal."""
    lock = directory / ".execution.lock"
    with lock.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DrillError("another invocation is active for this run") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _completed_operations(records: list[dict]) -> set[tuple[str, str]]:
    return {
        (record["operation"], record["stage"])
        for record in records
        if record["phase"] == "completed"
    }


def _pending_operation(records: list[dict]) -> tuple[str, str] | None:
    if records and records[-1]["phase"] == "intent":
        return records[-1]["operation"], records[-1]["stage"]
    return None


def _action_matches(plan: dict, action: dict, observed: dict, post: bool) -> bool:
    """Return whether an exact resource is in the action's pre- or post-state."""
    kind, _ = action["resource"].split("/", 1)
    old = action.get("old_state", {})
    if kind in {"probe", "servicemonitor"}:
        labels = observed.get("metadata", {}).get("labels", {})
        expected = old
        if post:
            expected = {"release": None, "sugarkube.dev/incident-paused": "true"}
            for token in action["command"]:
                if token.startswith("release="):
                    expected = {
                        "release": token.split("=", 1)[1],
                        "sugarkube.dev/incident-paused": None,
                    }
        return all(labels.get(key) == value for key, value in expected.items())
    containers = observed.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    selected = [
        item for item in containers if item.get("name") == plan["expected_deployment"]["container"]
    ]
    if len(selected) != 1:
        return False
    container = selected[0]
    if "image" in old:
        expected = old["image"]
        if post:
            expected = action["command"][-1].split("=", 1)[1]
        return container.get("image") == expected
    if "TOKENPLACE_METRICS_MODE" in old:
        env = {item.get("name"): item.get("value") for item in container.get("env", [])}
        expected = (
            action["command"][-1].split("=", 1)[1] if post else old["TOKENPLACE_METRICS_MODE"]
        )
        return env.get("TOKENPLACE_METRICS_MODE") == expected
    return False


def _action_observed(plan: dict, action: dict, kubeconfig: Path, runner: Runner) -> dict:
    kind, name = action["resource"].split("/", 1)
    namespace = "monitoring" if kind == "probe" else plan["inventory"]["namespace"]
    return _runner_json(
        runner,
        [
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "sugar-staging",
            "--namespace",
            namespace,
            "get",
            kind,
            name,
            "-o",
            "json",
        ],
        "stage state lookup failed",
    )


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not RFC3339_UTC.fullmatch(value):
        raise DrillError("gate evidence timestamp must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DrillError("gate evidence timestamp is malformed") from exc


def _minutes(spec: object, label: str) -> float:
    if not isinstance(spec, dict) or set(spec) != {"value", "unit"}:
        raise DrillError(f"planned {label} is malformed")
    value = spec["value"]
    if spec["unit"] != "minutes" or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DrillError(f"planned {label} is unsupported")
    return float(value)


def _typed_comparison(observed: object, expected: object, operator: object) -> bool:
    if operator not in {"eq", "lte", "lt"}:
        raise DrillError("planned gate operator is unsupported")
    if isinstance(expected, bool):
        if operator != "eq" or not isinstance(observed, bool):
            raise DrillError("gate evidence value has the wrong type")
    elif isinstance(expected, str):
        if operator != "eq" or not isinstance(observed, str):
            raise DrillError("gate evidence value has the wrong type")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(observed, bool) or not isinstance(observed, (int, float)):
            raise DrillError("gate evidence value has the wrong type")
        if not all(
            map(
                lambda number: number == number and abs(number) != float("inf"),
                (observed, expected),
            )
        ):
            raise DrillError("gate evidence number must be finite")
    else:
        raise DrillError("planned gate value type is unsupported")
    if operator == "eq":
        return observed == expected
    if operator == "lte":
        return observed <= expected
    return observed < expected


def _evidence_passes(
    plan: dict, action: dict, evidence: dict, now: datetime | None = None
) -> tuple[bool, dict]:
    top_fields = {
        "schema_version",
        "run_id",
        "plan_digest",
        "stage",
        "observed_from",
        "observed_until",
        "checks",
    }
    if not isinstance(evidence, dict) or set(evidence) != top_fields:
        raise DrillError("gate evidence object is malformed")
    if evidence["schema_version"] != 1:
        raise DrillError("gate evidence schema is unsupported")
    for field in ("run_id", "stage"):
        if not isinstance(evidence[field], str) or not SAFE_NAME.fullmatch(evidence[field]):
            raise DrillError("gate evidence identifier is unsafe")
    if not isinstance(evidence["plan_digest"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", evidence["plan_digest"]
    ):
        raise DrillError("gate evidence identifier is unsafe")
    if (evidence["run_id"], evidence["plan_digest"], evidence["stage"]) != (
        plan["run_id"],
        plan["plan_digest"],
        action["id"],
    ):
        raise DrillError("gate evidence does not belong to this plan stage")
    start, end = _utc_timestamp(evidence["observed_from"]), _utc_timestamp(
        evidence["observed_until"]
    )
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise DrillError("gate evidence clock must be timezone-aware")
    clock = clock.astimezone(timezone.utc)
    if start > end or end > clock:
        raise DrillError("gate evidence interval is invalid")
    if (clock - end).total_seconds() > GATE_EVIDENCE_FRESHNESS_SECONDS:
        raise DrillError("gate evidence is stale")
    duration = _minutes(action["duration"], "duration") if "duration" in action else 0
    if (end - start).total_seconds() < duration * 60:
        raise DrillError("gate evidence does not cover the required duration")
    checks = evidence["checks"]
    planned = {check["metric"]: check for check in action["checks"]}
    if not isinstance(checks, dict) or set(checks) != set(planned):
        raise DrillError("gate evidence metric set is not exact")
    passed = True
    sources = {}
    for metric, check in planned.items():
        item = checks[metric]
        fields = {"value", "observed_from", "observed_until"}
        if "source" in check:
            fields.add("source")
        if not isinstance(item, dict) or set(item) != fields:
            raise DrillError("gate evidence check is malformed")
        check_start, check_end = _utc_timestamp(item["observed_from"]), _utc_timestamp(
            item["observed_until"]
        )
        if check_start > check_end or check_start < start or check_end > end or check_end > clock:
            raise DrillError("gate evidence check interval is invalid")
        if (clock - check_end).total_seconds() > GATE_EVIDENCE_FRESHNESS_SECONDS:
            raise DrillError("gate evidence check is stale")
        window = _minutes(check["window"], "window") if "window" in check else 0
        if (check_end - check_start).total_seconds() < window * 60:
            raise DrillError("gate evidence check does not cover its window")
        if "source" in check:
            if item["source"] != check["source"]:
                raise DrillError("gate evidence source does not match")
            sources[metric] = item["source"]
        passed = _typed_comparison(item["value"], check["value"], check["operator"]) and passed
    return passed, {
        "observed_from": evidence["observed_from"],
        "observed_until": evidence["observed_until"],
        "sources": sources,
    }


def _read_gate_evidence(path: Path) -> tuple[dict, str]:
    if not path.is_absolute():
        raise DrillError("gate evidence must be an absolute private file")
    try:
        resolved = path.resolve(strict=True)
        root = ROOT.resolve(strict=True)
        stat = resolved.stat()
        if (
            resolved == root
            or resolved.is_relative_to(root)
            or not resolved.is_file()
            or path.is_symlink()
        ):
            raise DrillError("gate evidence must be a regular file outside the repository")
        if stat.st_size > GATE_EVIDENCE_MAX_BYTES:
            raise DrillError("gate evidence exceeds the size limit")
        payload = resolved.read_bytes()
        evidence = json.loads(payload)
    except DrillError:
        raise
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        raise DrillError("gate evidence cannot be read") from exc
    return evidence, hashlib.sha256(payload).hexdigest()


def execute_operation(
    args: argparse.Namespace, runner: Runner = subprocess.run, now: datetime | None = None
) -> dict:
    plan = _load_execution_plan(args.plan)
    journal = _private_directory(args.journal, "journal")
    if not args.kubeconfig.is_file():
        raise DrillError("kubeconfig is missing or is not a regular file")
    with _execution_lock(journal):
        return _execute_locked(args, runner, plan, journal, now)


def _record_phase(journal, plan, operation, stage, phase, **metadata):
    metadata.setdefault(
        "recorded_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    _append_journal(
        journal, plan, {"operation": operation, "stage": stage, "phase": phase, **metadata}
    )


def _verify_cleanup_baseline(plan, kubeconfig, runner):
    _assert_stage_preflight(plan, kubeconfig, runner, plan["expected_deployment"]["current_image"])
    checked_resources = set()
    for action in plan["actions"]:
        resource = action.get("resource")
        if action.get("type") == "mutation" and resource not in checked_resources:
            observed = _action_observed(plan, action, kubeconfig, runner)
            if not _action_matches(plan, action, observed, False):
                raise DrillError("cleanup requires the exact baseline")
            checked_resources.add(resource)
    for path in ("/livez", "/healthz"):
        result = runner(
            [
                "curl",
                "--silent",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                "--max-time",
                "10",
                f"https://{STAGING_HOST}{path}",
            ]
        )
        if result.returncode or not result.stdout.strip().startswith("2"):
            raise DrillError("cleanup health preservation check failed")


def _execute_locked(args, runner, plan, journal, now=None):
    records = _journal_records(journal, plan)
    completed = _completed_operations(records)
    pending = _pending_operation(records)
    stage = "cleanup" if args.cleanup else args.execute_stage or args.rollback_stage
    operation = "cleanup" if args.cleanup else "rollback" if args.rollback_stage else "execute"
    if pending and pending != (operation, stage):
        raise DrillError("a different interrupted operation must be reconciled first")
    aborting = any(record["operation"] == "rollback" for record in records)
    if operation == "execute" and aborting:
        raise DrillError("forward execution is refused after rollback begins")

    actions = plan["actions"]
    action = next((item for item in actions if item["id"] == stage), None)
    active = [
        item
        for item in actions
        if ("execute", item["id"]) in completed
        and item["type"] == "mutation"
        and ("rollback", item["id"]) not in completed
    ]
    active_images = [item for item in active if item["id"] in {"inject-oom-stimulus", "replace"}]
    expected_image = plan["expected_deployment"]["current_image"]
    if active_images:
        expected_image = (
            plan["expected_deployment"]["incident_image"]
            if active_images[-1]["id"] == "inject-oom-stimulus"
            else plan["expected_deployment"]["replacement_image"]
        )
    if aborting:
        # Recovery replacement and all subsequent inverses converge directly to
        # the original healthy baseline; never require revisiting the stimulus.
        expected_image = plan["expected_deployment"]["current_image"]
    if pending and stage == "replace" and operation in {"execute", "rollback"}:
        expected_image = {
            plan["expected_deployment"]["current_image"],
            plan["expected_deployment"]["replacement_image"],
        }
    _assert_stage_preflight(plan, args.kubeconfig, runner, expected_image)

    if operation == "cleanup":
        if active:
            raise DrillError("cleanup requires all active mutations to be rolled back")
        _verify_cleanup_baseline(plan, args.kubeconfig, runner)
        marker_present = _validate_marker(plan, args.kubeconfig, runner, absent_ok=True)
        if pending:
            if marker_present:
                _run_checked(
                    runner,
                    _marker_command(plan, args.kubeconfig, "delete"),
                    "exact marker cleanup failed",
                )
                if _validate_marker(plan, args.kubeconfig, runner, absent_ok=True):
                    raise DrillError("exact marker cleanup post-state failed")
            _record_phase(journal, plan, operation, stage, "completed")
            return {"status": "clean", "run_id": plan["run_id"]}
        if (operation, stage) in completed or not marker_present:
            return {"status": "already-clean", "run_id": plan["run_id"]}
        _record_phase(journal, plan, operation, stage, "intent")
        _run_checked(
            runner, _marker_command(plan, args.kubeconfig, "delete"), "exact marker cleanup failed"
        )
        if _validate_marker(plan, args.kubeconfig, runner, absent_ok=True):
            raise DrillError("exact marker cleanup post-state failed")
        _record_phase(journal, plan, operation, stage, "completed")
        return {"status": "clean", "run_id": plan["run_id"]}

    if stage == "marker" and operation == "execute":
        present = _validate_marker(plan, args.kubeconfig, runner, absent_ok=True)
        if pending:
            if not present:
                _run_checked(
                    runner,
                    _marker_command(plan, args.kubeconfig, "create"),
                    "marker creation failed",
                )
                _validate_marker(plan, args.kubeconfig, runner)
            _record_phase(journal, plan, operation, stage, "completed")
            return {"status": "completed", "stage": stage}
        if (operation, stage) in completed:
            if not present:
                raise DrillError("completed marker is missing")
            return {"status": "already-completed", "stage": stage}
        if present:
            raise DrillError("matching marker exists without a durable intent")
        _record_phase(journal, plan, operation, stage, "intent")
        _run_checked(
            runner, _marker_command(plan, args.kubeconfig, "create"), "marker creation failed"
        )
        _validate_marker(plan, args.kubeconfig, runner)
        _record_phase(journal, plan, operation, stage, "completed")
        return {"status": "completed", "stage": stage}

    if action is None:
        raise DrillError("requested stage is not in the immutable plan")
    _validate_marker(plan, args.kubeconfig, runner)
    if operation == "rollback":
        if action.get("type") != "mutation" or ("execute", stage) not in completed:
            raise DrillError("only a completed mutation can be rolled back")
        if (operation, stage) in completed:
            return {"status": "already-rolled-back", "stage": stage}
        if not active or active[-1]["id"] != stage:
            raise DrillError("rollback must follow reverse mutation order")
        observed = _action_observed(plan, action, args.kubeconfig, runner)
        post, pre = _action_matches(plan, action, observed, True), _action_matches(
            plan, action, observed, False
        )
        if pre and action.get("baseline_idempotent_inverse"):
            _record_phase(journal, plan, operation, stage, "completed")
            return {"status": "already-at-safe-baseline", "stage": stage}
        if pending and pre:
            _record_phase(journal, plan, operation, stage, "completed")
            return {"status": "rolled-back", "stage": stage}
        if not post:
            raise DrillError("rollback state is ambiguous")
        if not pending:
            _record_phase(journal, plan, operation, stage, "intent")
        _run_checked(
            runner, _bind_command(action["inverse"], args.kubeconfig), "exact stage rollback failed"
        )
        observed = _action_observed(plan, action, args.kubeconfig, runner)
        if not _action_matches(plan, action, observed, False):
            raise DrillError("exact stage rollback post-state failed")
        _record_phase(journal, plan, operation, stage, "completed")
        return {"status": "rolled-back", "stage": stage}

    executed = [item["id"] for item in actions if ("execute", item["id"]) in completed]
    expected = ["marker"] + [item["id"] for item in actions]
    done = ["marker"] + executed if ("execute", "marker") in completed else executed
    if (operation, stage) in completed:
        if action["type"] == "mutation":
            observed = _action_observed(plan, action, args.kubeconfig, runner)
            if not _action_matches(plan, action, observed, True):
                raise DrillError("completed stage post-state drifted")
        return {"status": "already-completed", "stage": stage}
    if done != expected[: len(done)] or expected[len(done)] != stage:
        raise DrillError("stage is out of order")
    if action["type"] == "gate":
        if action["id"] == "observe-authentic-oom":
            if args.gate_evidence is not None:
                raise DrillError("authoritative OOM gate refuses operator-authored evidence")
            expected = plan["expected_deployment"]
            deployment = _runner_json(
                runner,
                [
                    "kubectl",
                    "--kubeconfig",
                    str(args.kubeconfig),
                    "--context",
                    "sugar-staging",
                    "--namespace",
                    plan["inventory"]["namespace"],
                    "get",
                    "deployment",
                    next(a["resource"].split("/", 1)[1] for a in actions if a["id"] == "replace"),
                    "-o",
                    "json",
                ],
                "authoritative OOM Deployment lookup failed",
            )
            coordinates = Coordinates(
                STAGING_HOST,
                args.kubeconfig,
                "sugar-staging",
                "staging",
                plan["inventory"]["namespace"],
                deployment["metadata"]["name"],
                expected["container"],
                expected["incident_image"],
                expected["replacement_image"],
                expected["rollback_image"],
                expected["replicas"],
                expected["memory_limit"],
                plan["inventory"]["service_monitor"],
                plan["run_id"],
                "staging-rehearsal",
                expected["incident_image"],
            )
            observation = _observe_live_oom(
                coordinates,
                deployment,
                ["kubectl", "--kubeconfig", str(args.kubeconfig), "--context", "sugar-staging"],
                runner,
                not_before=_utc_timestamp(
                    next(
                        record["recorded_at"]
                        for record in reversed(records)
                        if record["operation"] == "execute"
                        and record["stage"] == "inject-oom-stimulus"
                        and record["phase"] == "completed"
                    )
                ),
            )
            _record_phase(
                journal,
                plan,
                operation,
                stage,
                "completed",
                evidence_summary={
                    "termination_time": observation["termination_time"],
                    "restart_count": observation["restart_count"],
                    "event_aggregates": observation["event_aggregates"],
                },
            )
            return {"status": "completed", "stage": stage}
        if args.gate_evidence is None:
            raise DrillError("gate stage requires private evidence")
        evidence, evidence_digest = _read_gate_evidence(args.gate_evidence)
        passes, summary = _evidence_passes(plan, action, evidence, now)
        if pending:
            intent = next(
                record
                for record in reversed(records)
                if record["operation"] == operation and record["stage"] == stage
            )
            if intent.get("evidence_digest") != evidence_digest:
                prior_summary = intent.get("evidence_summary")
                if not isinstance(prior_summary, dict) or set(prior_summary) != {
                    "observed_from",
                    "observed_until",
                    "sources",
                }:
                    raise DrillError("pending gate evidence metadata is malformed")
                prior_end = _utc_timestamp(prior_summary["observed_until"])
                clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
                if (clock - prior_end).total_seconds() <= GATE_EVIDENCE_FRESHNESS_SECONDS:
                    raise DrillError("pending gate evidence digest changed while still fresh")
                _record_phase(
                    journal,
                    plan,
                    operation,
                    stage,
                    "expired",
                    evidence_digest=intent["evidence_digest"],
                    evidence_summary=prior_summary,
                )
                pending = None
        if not passes:
            return {"status": "gate-failed", "stage": stage, "on_failure": action["on_failure"]}
        metadata = {"evidence_digest": evidence_digest, "evidence_summary": summary}
        _record_phase(journal, plan, operation, stage, "completed", **metadata)
        return {"status": "completed", "stage": stage}
    observed = _action_observed(plan, action, args.kubeconfig, runner)
    post, pre = _action_matches(plan, action, observed, True), _action_matches(
        plan, action, observed, False
    )
    if pending and post:
        _record_phase(journal, plan, operation, stage, "completed")
        return {"status": "completed", "stage": stage}
    if not pre:
        raise DrillError("stage state is ambiguous")
    if not pending:
        _record_phase(journal, plan, operation, stage, "intent")
    _run_checked(runner, _bind_command(action["command"], args.kubeconfig), "stage mutation failed")
    observed = _action_observed(plan, action, args.kubeconfig, runner)
    if not _action_matches(plan, action, observed, True):
        raise DrillError("stage mutation post-state failed")
    _record_phase(journal, plan, operation, stage, "completed")
    return {"status": "completed", "stage": stage}


def main(argv: list[str] | None = None) -> int:
    actual = list(sys.argv[1:] if argv is None else argv)
    executing = any(flag in actual for flag in EXECUTION_OPERATIONS)
    args = (execution_parser() if executing else parser()).parse_args(actual)
    try:
        if executing:
            result = execute_operation(
                args,
                lambda command: subprocess.run(
                    command, capture_output=True, text=True, check=False
                ),
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        coordinates = validate(args)
        if args.live_preflight:
            checked = preflight_live(
                args.mode,
                coordinates,
                lambda command: subprocess.run(
                    command, capture_output=True, text=True, check=False
                ),
            )
        else:
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
            checked = preflight_snapshot(args.mode, coordinates, snapshot)
        plan = build_plan(checked)
        rendered = json.dumps(plan, indent=2) + "\n"
        _publish_evidence(args.evidence, rendered)
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
