#!/usr/bin/env python3
"""Build a fail-closed, privacy-safe token.place staging incident drill plan."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SAFE_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
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
    image: str
    previous_image: str
    replicas: int
    memory_limit: str
    service_monitor: str
    run_id: str


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
        "image",
        "previous-image",
        "memory-limit",
        "service-monitor",
        "run-id",
    ):
        result.add_argument(f"--{name}", required=True)
    result.add_argument("--kubeconfig", required=True, type=Path)
    result.add_argument("--replicas", required=True, type=int)
    result.add_argument("--evidence", required=True, type=Path)
    result.add_argument("--acknowledge-state-loss", action="store_true")
    result.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Required in Step 14a; emits a plan and never invokes kubectl",
    )
    return result


def validate(args: argparse.Namespace) -> Coordinates:
    """Validate every static coordinate before constructing a mutation plan."""
    if args.environment != "staging" or args.context != "sugar-staging":
        raise DrillError("an explicit staging environment and sugar-staging context are required")
    if "prod" in args.context.lower() or "prod" in args.environment.lower():
        raise DrillError("production is forbidden")
    if not args.kubeconfig.is_file():
        raise DrillError("kubeconfig is missing or is not a regular file")
    if not isinstance(args.host, str) or args.host.strip().lower().rstrip(".") != STAGING_HOST:
        raise DrillError("host must be the canonical token.place staging host")
    if args.replicas < 1:
        raise DrillError("replica count must be positive")
    for field in ("image", "previous_image"):
        if not re.fullmatch(r"[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}", getattr(args, field)):
            raise DrillError(f"{field.replace('_', ' ')} must use an immutable sha256 digest")
    if args.image == args.previous_image:
        raise DrillError("replacement and previous images must differ")
    if not re.fullmatch(r"[1-9][0-9]*(Mi|Gi)", args.memory_limit):
        raise DrillError("memory limit must be an explicit positive Mi or Gi quantity")
    for field in ("namespace", "deployment", "container", "service_monitor", "run_id"):
        if not SAFE_NAME.fullmatch(str(getattr(args, field))):
            raise DrillError(f"{field.replace('_', ' ')} is not an exact safe Kubernetes name")
    if not args.acknowledge_state_loss:
        raise DrillError("explicit authorization for process-local relay-state loss is required")
    supplied_evidence = args.evidence.expanduser()
    evidence = (
        supplied_evidence if supplied_evidence.is_absolute() else ROOT / supplied_evidence
    ).resolve()
    evidence_root = (ROOT / "evidence").resolve()
    if evidence.exists() or evidence.parent != evidence_root:
        raise DrillError(
            "evidence must be a new file directly beneath the repository evidence directory"
        )
    args.evidence = evidence
    return Coordinates(
        **{field: getattr(args, field) for field in Coordinates.__dataclass_fields__}
    )


def inventory(environment: str) -> dict[str, dict]:
    contract = yaml.safe_load((ROOT / "config/observability/probe-quotas.yaml").read_text())
    matches = [
        item
        for item in contract["probes"]
        if item["application"] == "tokenplace" and item["environment"] == environment
    ]
    route_classes = [item["route_class"] for item in matches]
    if len(route_classes) != len(set(route_classes)):
        raise DrillError("token.place quota inventory contains duplicate route classes")
    selected = {item["route_class"]: item for item in matches}
    if set(selected) != {"root", "metadata", "livez", "healthz"}:
        raise DrillError("token.place quota inventory is missing or ambiguous")
    expected = {
        "root": ("/", "GET"),
        "metadata": ("/api/v1/meta", "GET"),
        "livez": ("/livez", "GET"),
        "healthz": ("/healthz", "GET"),
    }
    if any(
        (selected[key]["route"], selected[key]["method"]) != value
        for key, value in expected.items()
    ):
        raise DrillError("token.place quota inventory route or method does not match")
    return selected


def build_plan(mode: str, c: Coordinates, probes: dict[str, dict]) -> dict:
    """Return ordered actions bound to the validated kubeconfig; omit the host."""
    kubectl = ["kubectl", "--kubeconfig", str(c.kubeconfig.resolve()), "--context", c.context]
    prefix = kubectl + ["--namespace", c.namespace]
    probe_prefix = kubectl + ["--namespace", "monitoring"]
    root, metadata = probes["root"]["probe"], probes["metadata"]["probe"]
    pause = [c.service_monitor] if mode == "metrics-oom" else [root, metadata]
    actions = []

    def add(stage: str, resource: str, command: list[str], rollback: list[str] | None = None):
        actions.append(
            {"stage": stage, "resource": resource, "command": command, "rollback": rollback or []}
        )

    for target in pause:
        kind = "servicemonitor" if mode == "metrics-oom" else "probe"
        base = prefix if kind == "servicemonitor" else probe_prefix
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
    add(
        "replace",
        f"deployment/{c.deployment}",
        prefix + ["set", "image", f"deployment/{c.deployment}", f"{c.container}={c.image}"],
        prefix
        + [
            "set",
            "image",
            f"deployment/{c.deployment}",
            f"{c.container}={c.previous_image}",
        ],
    )
    add(
        "verify-deployment-identity",
        f"deployment/{c.deployment}",
        prefix
        + [
            "get",
            f"deployment/{c.deployment}",
            "-o",
            "jsonpath={.spec.replicas} {.spec.template.spec.containers[?(@.name=='"
            + c.container
            + "')].image} {.spec.template.spec.containers[?(@.name=='"
            + c.container
            + "')].resources.limits.memory}",
        ],
    )
    add(
        "readiness-and-identity",
        f"deployment/{c.deployment}",
        prefix + ["rollout", "status", f"deployment/{c.deployment}", "--timeout=5m"],
    )
    for stage in (
        "compute-registration",
        "compute-polling",
        "encrypted-e2e-request-response-retrieval-decryption",
    ):
        add(stage, "operator-check", ["operator-check", stage, "--required"])
    for stage, target in (("restore-root", root), ("restore-metadata", metadata)):
        if mode == "quota-exhaustion":
            add(
                stage,
                f"probe/{target}",
                probe_prefix
                + [
                    "label",
                    f"probe/{target}",
                    "release=kube-prometheus-stack",
                    "sugarkube.dev/incident-paused-",
                    "--overwrite",
                ],
                probe_prefix
                + [
                    "label",
                    f"probe/{target}",
                    "release-",
                    "sugarkube.dev/incident-paused=true",
                    "--overwrite",
                ],
            )
        else:
            add(stage, f"probe/{target}", ["verify-preserved", f"probe/{target}"])
        add(
            f"observe-after-{stage}",
            "observation-gate",
            [
                "observe",
                "--window=15m",
                "--rollback-on=readiness,restart,oom,429,5xx,scrape,memory",
            ],
        )
    if mode == "metrics-oom":
        add(
            "restore-metrics-last",
            f"servicemonitor/{c.service_monitor}",
            prefix
            + [
                "label",
                f"servicemonitor/{c.service_monitor}",
                "release=kube-prometheus-stack",
                "sugarkube.dev/incident-paused-",
                "--overwrite",
            ],
            prefix
            + [
                "label",
                f"servicemonitor/{c.service_monitor}",
                "release-",
                "sugarkube.dev/incident-paused=true",
                "--overwrite",
            ],
        )
    else:
        add(
            "restore-metrics-last",
            f"servicemonitor/{c.service_monitor}",
            ["verify-preserved", f"servicemonitor/{c.service_monitor}"],
        )
    add(
        "extended-observation",
        "observation-gate",
        [
            "observe",
            "--window=30m",
            "--rollback-on=readiness,restart,oom,429,5xx,scrape-cardinality-cost,memory",
        ],
    )
    add("cleanup", f"drill/{c.run_id}", ["cleanup", "--exact-run-id", c.run_id])
    return {
        "schema_version": 1,
        "mode": mode,
        "run_id": c.run_id,
        "environment": "staging",
        "dry_run": True,
        "state_changes": {
            "cluster": False,
            "production": False,
            "repository": True,
            "external": False,
        },
        "preserved": [f"probe/{probes['livez']['probe']}", f"probe/{probes['healthz']['probe']}"],
        "expected_deployment": {
            "replicas": c.replicas,
            "container": c.container,
            "image": c.image,
            "memory_limit": c.memory_limit,
        },
        "required_preconditions": [
            "exact deployment/container/image/replicas/memory",
            "exact ServiceMonitor and Probe inventory",
            "OOMKilled and exit 137 for metrics-oom",
            "route-specific 429 classification for quota-exhaustion",
        ],
        "actions": actions,
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        coordinates = validate(args)
        plan = build_plan(args.mode, coordinates, inventory(args.environment))
        args.evidence.parent.mkdir(exist_ok=True)
        args.evidence.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(plan, indent=2))
        return 0
    except DrillError as exc:
        print(f"token.place incident drill refused: {exc}", file=sys.stderr)
        return 2
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        print("token.place incident drill refused: precondition validation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
