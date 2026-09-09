#!/usr/bin/env python3
"""Fail-closed planner/executor for token.place incident drills.

The JSON snapshot path is deliberately the only dry-run input.  Live execution
reads the same bounded fields with kubectl and never prints host, kubeconfig, or
application data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RELEASE_LABEL = "release"
RELEASE_VALUE = "kube-prometheus-stack"
RESTORE_ORDER = ("root", "metadata", "metrics")


class GuardError(ValueError):
    """A precondition failed before mutation."""


@dataclass(frozen=True)
class Coordinates:
    context: str
    namespace: str
    deployment: str
    container: str
    monitor_namespace: str
    service_monitor: str
    probes: dict[str, str]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--incident", required=True, choices=("metrics-oom", "quota-exhaustion"))
    p.add_argument("--host", required=True)
    p.add_argument("--kubeconfig", required=True)
    p.add_argument("--context", required=True)
    p.add_argument("--environment", required=True, choices=("staging", "prod"))
    p.add_argument("--namespace", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--container", required=True)
    p.add_argument("--image", required=True, help="expected immutable current image digest")
    p.add_argument("--replacement-image", required=True, help="immutable replacement digest")
    p.add_argument("--rollback-image", required=True, help="immutable rollback digest")
    p.add_argument("--replicas", required=True, type=int)
    p.add_argument("--memory-limit", required=True)
    p.add_argument("--monitor-namespace", required=True)
    p.add_argument("--service-monitor", required=True)
    p.add_argument("--root-probe", required=True)
    p.add_argument("--metadata-probe", required=True)
    p.add_argument("--livez-probe", required=True)
    p.add_argument("--healthz-probe", required=True)
    p.add_argument(
        "--snapshot", type=Path, help="bounded mock snapshot; required without --execute"
    )
    p.add_argument("--evidence-dir", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--authorize-state-loss", action="store_true")
    p.add_argument("--confirm-encrypted-e2e", action="store_true")
    p.add_argument(
        "--completed-gate",
        action="append",
        default=[],
        help="approved gate stage backed by evidence",
    )
    return p


def _digest(value: str, field: str) -> None:
    if "@sha256:" not in value or len(value.rsplit("@sha256:", 1)[1]) != 64:
        raise GuardError(f"{field} must be an immutable sha256 image identity")


def coordinates(args: argparse.Namespace) -> Coordinates:
    expected = {
        "namespace": "tokenplace",
        "deployment": "tokenplace",
        "container": "relay",
        "monitor_namespace": "monitoring",
        "service_monitor": "tokenplace",
        "root_probe": f"blackbox-tokenplace-{args.environment}-root",
        "metadata_probe": f"blackbox-tokenplace-{args.environment}-metadata",
        "livez_probe": f"blackbox-tokenplace-{args.environment}-livez",
        "healthz_probe": f"blackbox-tokenplace-{args.environment}-healthz",
    }
    for key, value in expected.items():
        if getattr(args, key) != value:
            raise GuardError(f"{key.replace('_', '-')} does not match the exact inventory")
    if args.replicas < 1 or not args.memory_limit.strip():
        raise GuardError("replicas and memory-limit must be explicit positive values")
    for field in ("image", "replacement_image", "rollback_image"):
        _digest(getattr(args, field), field.replace("_", "-"))
    if args.environment != "staging" or "prod" in args.context.lower():
        raise GuardError("the drill requires an explicit non-production staging context")
    return Coordinates(
        args.context,
        args.namespace,
        args.deployment,
        args.container,
        args.monitor_namespace,
        args.service_monitor,
        {
            route: getattr(args, f"{route}_probe")
            for route in ("root", "metadata", "livez", "healthz")
        },
    )


def load_snapshot(args: argparse.Namespace, run=subprocess.run) -> dict:
    if args.snapshot:
        return json.loads(args.snapshot.read_text(encoding="utf-8"))
    if not args.execute:
        raise GuardError("--snapshot is required for a cluster-free dry run")
    cmd = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context]
    # The executor intentionally requests only typed objects; it never reads Secrets or logs.
    deployment = run(
        cmd + ["-n", args.namespace, "get", "deployment", args.deployment, "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    monitors = run(
        cmd + ["-n", args.monitor_namespace, "get", "servicemonitor,probe", "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return {"deployment": json.loads(deployment.stdout), "monitoring": json.loads(monitors.stdout)}


def validate_snapshot(args: argparse.Namespace, c: Coordinates, snap: dict) -> None:
    dep = snap.get("deployment", {})
    meta, spec = dep.get("metadata", {}), dep.get("spec", {})
    if meta.get("name") != c.deployment or meta.get("namespace") != c.namespace:
        raise GuardError("deployment identity is missing or mismatched")
    if spec.get("replicas") != args.replicas:
        raise GuardError("replica count mismatches the approved coordinate")
    containers = spec.get("template", {}).get("spec", {}).get("containers", [])
    selected = [x for x in containers if x.get("name") == c.container]
    if len(selected) != 1 or selected[0].get("image") != args.image:
        raise GuardError(
            "container or immutable image identity is missing, ambiguous, or mismatched"
        )
    if selected[0].get("resources", {}).get("limits", {}).get("memory") != args.memory_limit:
        raise GuardError("memory limit mismatches the approved coordinate")
    items = snap.get("monitoring", {}).get("items", [])
    identities = [(x.get("kind"), x.get("metadata", {}).get("name")) for x in items]
    required = [("ServiceMonitor", c.service_monitor)] + [("Probe", x) for x in c.probes.values()]
    if any(identities.count(identity) != 1 for identity in required):
        raise GuardError("monitoring targets are missing or ambiguous")
    if args.incident == "metrics-oom":
        states = snap.get("terminations", [])
        if not any(
            x.get("container") == c.container
            and x.get("reason") == "OOMKilled"
            and x.get("exitCode") == 137
            for x in states
        ):
            raise GuardError("authoritative OOMKilled exit-code 137 evidence is required")


def plan(args: argparse.Namespace, c: Coordinates) -> list[dict]:
    k = ["kubectl", "--context", c.context]
    patch_off = '{"metadata":{"labels":{"release":null}}}'
    patch_on = '{"metadata":{"labels":{"release":"kube-prometheus-stack"}}}'
    actions: list[dict] = []
    if args.incident == "metrics-oom":
        actions.append(
            {
                "stage": "pause-metrics",
                "do": k
                + [
                    "-n",
                    c.monitor_namespace,
                    "patch",
                    "servicemonitor",
                    c.service_monitor,
                    "--type=merge",
                    "-p",
                    patch_off,
                ],
                "rollback": k
                + [
                    "-n",
                    c.monitor_namespace,
                    "patch",
                    "servicemonitor",
                    c.service_monitor,
                    "--type=merge",
                    "-p",
                    patch_on,
                ],
            }
        )
    else:
        for route in ("root", "metadata"):
            actions.append(
                {
                    "stage": f"pause-{route}",
                    "do": k
                    + [
                        "-n",
                        c.monitor_namespace,
                        "patch",
                        "probe",
                        c.probes[route],
                        "--type=merge",
                        "-p",
                        patch_off,
                    ],
                    "rollback": k
                    + [
                        "-n",
                        c.monitor_namespace,
                        "patch",
                        "probe",
                        c.probes[route],
                        "--type=merge",
                        "-p",
                        patch_on,
                    ],
                }
            )
    actions += [
        {
            "stage": "replace",
            "do": k
            + [
                "-n",
                c.namespace,
                "set",
                "image",
                f"deployment/{c.deployment}",
                f"{c.container}={args.replacement_image}",
            ],
            "rollback": k
            + [
                "-n",
                c.namespace,
                "set",
                "image",
                f"deployment/{c.deployment}",
                f"{c.container}={args.rollback_image}",
            ],
        },
        {"stage": "readiness-and-identity", "gate": True},
        {"stage": "compute-register-and-poll", "gate": True},
        {"stage": "encrypted-request-response-retrieval-decryption", "gate": True},
    ]
    for route in RESTORE_ORDER:
        if route == "metrics" and args.incident != "metrics-oom":
            continue
        if route != "metrics" and args.incident != "quota-exhaustion":
            continue
        kind, name = (
            ("servicemonitor", c.service_monitor)
            if route == "metrics"
            else ("probe", c.probes[route])
        )
        actions.append(
            {
                "stage": f"restore-{route}",
                "do": k
                + ["-n", c.monitor_namespace, "patch", kind, name, "--type=merge", "-p", patch_on],
                "rollback": k
                + ["-n", c.monitor_namespace, "patch", kind, name, "--type=merge", "-p", patch_off],
            }
        )
        actions.append(
            {
                "stage": "extended-observation" if route == "metrics" else f"observe-{route}",
                "gate": True,
            }
        )
    return actions


def safe_summary(args: argparse.Namespace, actions: list[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "incidentClass": args.incident,
        "environment": args.environment,
        "liveDrillPassed": False,
        "state": {
            "clusterChanged": False,
            "productionChanged": False,
            "repositoryChanged": False,
            "externalChanged": False,
        },
        "preservedCoverage": ["livez", "healthz"],
        "stateLoss": "replacement loses process-local relay state; explicitly authorized",
        "stages": [x["stage"] for x in actions],
        "acceptance": {
            "readinessSeconds": 180,
            "observationSeconds": 300,
            "extendedObservationSeconds": 900,
            "maxRestarts": 0,
            "maxOOMKilled": 0,
            "max429": 0,
            "max5xx": 0,
            "scrapeUp": 1,
            "maxMemoryPercent": 80,
            "cardinalityAndCostWithinReviewedBounds": True,
        },
    }


def main(argv=None, run=subprocess.run) -> int:
    args = parser().parse_args(argv)
    try:
        c = coordinates(args)
        snap = load_snapshot(args, run)
        validate_snapshot(args, c, snap)
        actions = plan(args, c)
        summary = safe_summary(args, actions)
        if args.execute:
            if not args.authorize_state_loss or not args.confirm_encrypted_e2e:
                raise GuardError(
                    "state-loss authorization and encrypted E2E confirmation are mandatory"
                )
            args.evidence_dir.mkdir(parents=True, exist_ok=True)
            for action in actions:
                if action.get("gate"):
                    if action["stage"] not in args.completed_gate:
                        raise GuardError(
                            f"operator evidence gate required before {action['stage']}"
                        )
                    continue
                print("ROLLBACK " + " ".join(action["rollback"]))
                run(action["do"], check=True)
            summary["state"]["clusterChanged"] = True
        else:
            print(json.dumps({"summary": summary, "actions": actions}, indent=2))
        if args.execute:
            (args.evidence_dir / "summary.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
        return 0
    except (GuardError, OSError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
