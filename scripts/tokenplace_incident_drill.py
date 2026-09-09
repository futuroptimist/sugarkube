#!/usr/bin/env python3
"""Build or execute the fail-closed token.place incident drill plan.

Dry-run is the default.  The program deliberately accepts a privacy-safe snapshot
instead of discovering a cluster: operators must classify and review the target
before a separately authorised mutation run.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class GuardError(ValueError):
    """A precondition failed before mutation."""


IMMUTABLE = re.compile(r"^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$")
INCIDENTS = {"metrics-oom", "quota-exhaustion"}


@dataclass(frozen=True)
class Coordinates:
    kubeconfig: str
    context: str
    environment: str
    namespace: str
    deployment: str
    container: str
    image: str
    rollback_image: str
    replicas: int
    memory_limit: str
    service_monitor: str
    root_probe: str
    metadata_probe: str
    livez_probe: str
    healthz_probe: str


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--incident", choices=sorted(INCIDENTS), required=True)
    p.add_argument("--host", required=True, help="expected host (validated but never printed)")
    for name in (
        "kubeconfig",
        "context",
        "environment",
        "namespace",
        "deployment",
        "container",
        "image",
        "rollback-image",
        "memory-limit",
        "service-monitor",
        "root-probe",
        "metadata-probe",
        "livez-probe",
        "healthz-probe",
    ):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--replicas", required=True, type=int)
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--evidence-summary", type=Path)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--authorize-state-loss", action="store_true")
    p.add_argument("--confirm-compute-registration", action="store_true")
    p.add_argument("--confirm-compute-polling", action="store_true")
    p.add_argument("--confirm-encrypted-e2e", action="store_true")
    p.add_argument("--confirm-observation-gates", action="store_true")
    return p


def coordinates(args: argparse.Namespace) -> Coordinates:
    return Coordinates(
        **{field: getattr(args, field) for field in Coordinates.__dataclass_fields__}
    )


def _load_snapshot(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError("snapshot is missing or invalid") from exc
    if not isinstance(data, dict):
        raise GuardError("snapshot is missing or invalid")
    return data


def validate(args: argparse.Namespace, c: Coordinates, snapshot: dict) -> None:
    if args.host.strip() == "" or any(
        not str(getattr(c, f)).strip() for f in c.__dataclass_fields__
    ):
        raise GuardError("all coordinates must be explicit and non-empty")
    if c.environment != "staging" or "prod" in c.context.lower() or args.host == "token.place":
        raise GuardError("the drill requires an explicit non-production staging target")
    if (
        c.replicas < 1
        or not IMMUTABLE.fullmatch(c.image)
        or not IMMUTABLE.fullmatch(c.rollback_image)
    ):
        raise GuardError("replicas and both immutable image coordinates are required")
    expected = {
        "host": args.host,
        "context": c.context,
        "environment": c.environment,
        "namespace": c.namespace,
        "deployment": c.deployment,
        "container": c.container,
        "image": c.rollback_image,
        "replicas": c.replicas,
        "memory_limit": c.memory_limit,
        "service_monitor": c.service_monitor,
        "probes": [c.root_probe, c.metadata_probe, c.livez_probe, c.healthz_probe],
    }
    if snapshot.get("matches") != expected or snapshot.get("target_counts") != {
        "deployment": 1,
        "container": 1,
        "service_monitor": 1,
        "root_probe": 1,
        "metadata_probe": 1,
        "livez_probe": 1,
        "healthz_probe": 1,
    }:
        raise GuardError("snapshot identity is missing, ambiguous, or mismatched")
    if snapshot.get("health_probe_labels") != {c.livez_probe: True, c.healthz_probe: True}:
        raise GuardError("health probe preservation is not proven")
    if args.incident == "metrics-oom" and snapshot.get("oom") != {
        "reason": "OOMKilled",
        "exit_code": 137,
    }:
        raise GuardError("authoritative OOMKilled/137 evidence is required")
    if args.incident == "quota-exhaustion" and not snapshot.get("quota_contract_valid"):
        raise GuardError("the declarative quota schedule must validate")


def kubectl(c: Coordinates, *parts: str) -> list[str]:
    return ["kubectl", "--kubeconfig", c.kubeconfig, "--context", c.context, *parts]


def build_plan(args: argparse.Namespace, c: Coordinates, snapshot: dict) -> list[dict]:
    sm_pause = kubectl(
        c,
        "-n",
        c.namespace,
        "label",
        "servicemonitor",
        c.service_monitor,
        "release-",
        "--overwrite",
    )
    sm_restore = kubectl(
        c,
        "-n",
        c.namespace,
        "label",
        "servicemonitor",
        c.service_monitor,
        "release=kube-prometheus-stack",
        "--overwrite",
    )
    probe = lambda name, value: kubectl(
        c, "-n", "monitoring", "label", "probe", name, value, "--overwrite"
    )
    replace = kubectl(
        c,
        "-n",
        c.namespace,
        "set",
        "image",
        f"deployment/{c.deployment}",
        f"{c.container}={c.image}",
    )
    rollback = kubectl(
        c,
        "-n",
        c.namespace,
        "set",
        "image",
        f"deployment/{c.deployment}",
        f"{c.container}={c.rollback_image}",
    )
    plan: list[dict] = []
    if args.incident == "metrics-oom":
        plan.append({"stage": "pause-metrics", "command": sm_pause, "rollback": sm_restore})
        if snapshot.get("degraded_metrics_supported"):
            degraded = kubectl(
                c,
                "-n",
                c.namespace,
                "set",
                "env",
                f"deployment/{c.deployment}",
                "TOKENPLACE_METRICS_MODE=degraded",
            )
            plan.append(
                {
                    "stage": "enable-degraded-metrics",
                    "command": degraded,
                    "rollback": kubectl(
                        c,
                        "-n",
                        c.namespace,
                        "set",
                        "env",
                        f"deployment/{c.deployment}",
                        "TOKENPLACE_METRICS_MODE-",
                    ),
                }
            )
    else:
        for name, stage in ((c.root_probe, "pause-root"), (c.metadata_probe, "pause-metadata")):
            plan.append(
                {
                    "stage": stage,
                    "command": probe(name, "release-"),
                    "rollback": probe(name, "release=kube-prometheus-stack"),
                }
            )
    plan.extend(
        [
            {"stage": "replace", "command": replace, "rollback": rollback},
            {
                "stage": "workload-ready-and-image",
                "gate": "ready replicas; exact digest; no restarts/OOM",
            },
            {"stage": "compute-registration", "gate": "compute re-registered"},
            {"stage": "compute-polling", "gate": "compute polling succeeds"},
            {
                "stage": "encrypted-e2e",
                "gate": "encrypted request/response/retrieval/decryption succeeds",
            },
        ]
    )
    if args.incident == "quota-exhaustion":
        plan.extend(
            [
                {
                    "stage": "restore-root",
                    "command": probe(c.root_probe, "release=kube-prometheus-stack"),
                    "rollback": probe(c.root_probe, "release-"),
                },
                {"stage": "observe-root-10m", "gate": "thresholds pass"},
                {
                    "stage": "restore-metadata",
                    "command": probe(c.metadata_probe, "release=kube-prometheus-stack"),
                    "rollback": probe(c.metadata_probe, "release-"),
                },
                {"stage": "observe-metadata-10m", "gate": "thresholds and quota validator pass"},
            ]
        )
    if args.incident == "metrics-oom":
        plan.append({"stage": "restore-metrics-last", "command": sm_restore, "rollback": sm_pause})
    else:
        plan.append({"stage": "metrics-confirmed-active-last", "gate": "metrics stayed selected"})
    plan.append({"stage": "extended-observation-30m", "gate": "all thresholds pass"})
    return plan


def execute(plan: list[dict], runner=subprocess.run) -> None:
    for item in plan:
        if "command" not in item:
            continue
        print("ROLLBACK " + shlex.join(item["rollback"]), flush=True)
        runner(item["command"], check=True)


def safe_summary(args: argparse.Namespace, plan: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "incident_class": args.incident,
        "live_drill_passed": False,
        "privacy": "aggregate-only",
        "planned_stages": [x["stage"] for x in plan],
        "state": {
            "cluster_changed": bool(args.execute),
            "production_changed": False,
            "repository_changed": False,
            "external_changed": False,
        },
        "required_evidence": [
            "deployment",
            "termination",
            "events",
            "probes",
            "service_monitor",
            "endpoints",
            "public_routes",
            "compute",
            "encrypted_e2e",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        c = coordinates(args)
        snapshot = _load_snapshot(args.snapshot)
        validate(args, c, snapshot)
        plan = build_plan(args, c, snapshot)
        if args.execute:
            confirmations = (
                args.authorize_state_loss,
                args.confirm_compute_registration,
                args.confirm_compute_polling,
                args.confirm_encrypted_e2e,
                args.confirm_observation_gates,
            )
            if not all(confirmations):
                raise GuardError(
                    "execution requires state-loss authorization and all recovery gates"
                )
            execute(plan)
        else:
            print(json.dumps(safe_summary(args, plan), indent=2))
        if args.evidence_summary:
            args.evidence_summary.write_text(
                json.dumps(safe_summary(args, plan), indent=2) + "\n", encoding="utf-8"
            )
    except GuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
