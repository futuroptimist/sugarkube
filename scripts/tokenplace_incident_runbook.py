#!/usr/bin/env python3
"""Build a fail-closed token.place incident recovery/drill plan.

The default is repository-only validation and a redacted plan.  ``--execute`` is
deliberately limited to staging and still requires a human acknowledgement.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHA_IMAGE = re.compile(r"^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$")
DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")
MODES = {"metrics-oom", "quota-exhaustion"}


class GuardError(ValueError):
    """A precondition failed before mutation."""


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
    replicas: int
    memory_limit: str
    service_monitor: str
    root_probe: str
    metadata_probe: str
    livez_probe: str
    healthz_probe: str
    drill_id: str

    def validate(self) -> None:
        strings = (
            self.host,
            self.context,
            self.namespace,
            self.deployment,
            self.container,
            self.service_monitor,
            self.root_probe,
            self.metadata_probe,
            self.livez_probe,
            self.healthz_probe,
            self.drill_id,
        )
        if any(not value or not DNS_LABEL.fullmatch(value) for value in strings):
            raise GuardError("all names and the host must be explicit DNS-safe values")
        if (
            self.environment != "staging"
            or "prod" in self.context.lower()
            or "prod" in self.host.lower()
        ):
            raise GuardError("drills require an explicit non-production staging identity")
        if not self.kubeconfig.is_file():
            raise GuardError("kubeconfig must name one existing regular file")
        if not SHA_IMAGE.fullmatch(self.image):
            raise GuardError("image must be an immutable registry digest")
        if self.replicas < 1 or not re.fullmatch(r"[1-9][0-9]*(?:Mi|Gi)", self.memory_limit):
            raise GuardError("replicas and memory limit must be explicit positive values")
        resources = {
            self.service_monitor,
            self.root_probe,
            self.metadata_probe,
            self.livez_probe,
            self.healthz_probe,
        }
        if len(resources) != 5:
            raise GuardError("monitoring resources must be five distinct exact names")
        expected = {
            "root": f"blackbox-tokenplace-staging-root",
            "metadata": f"blackbox-tokenplace-staging-metadata",
            "livez": f"blackbox-tokenplace-staging-livez",
            "healthz": f"blackbox-tokenplace-staging-healthz",
        }
        if any(getattr(self, f"{key}_probe") != value for key, value in expected.items()):
            raise GuardError("probe coordinates do not match the staging inventory")


def restoration_order(mode: str) -> list[str]:
    if mode not in MODES:
        raise GuardError("incident mode is invalid")
    return [
        "replace",
        "ready-and-image",
        "compute-register",
        "compute-poll",
        "encrypted-e2e",
        "restore-root",
        "observe-root",
        "restore-metadata",
        "observe-metadata",
        "restore-metrics",
        "extended-observation",
        "cleanup",
    ]


def authoritative_oom(reason: str | None, exit_code: int | None) -> bool:
    """Require both Kubernetes termination fields; readiness is intentionally irrelevant."""
    return reason == "OOMKilled" and exit_code == 137


def selected_pauses(mode: str, c: Coordinates) -> list[tuple[str, str]]:
    if mode == "metrics-oom":
        return [("servicemonitor", c.service_monitor)]
    if mode == "quota-exhaustion":
        return [("probe", c.root_probe), ("probe", c.metadata_probe)]
    raise GuardError("incident mode is invalid")


def plan(mode: str, c: Coordinates) -> dict:
    c.validate()
    pauses = selected_pauses(mode, c)
    rollbacks = [
        f"restore label release=kube-prometheus-stack on {kind}/{name}" for kind, name in pauses
    ]
    return {
        "schemaVersion": 1,
        "drillId": c.drill_id,
        "environment": "staging",
        "mode": mode,
        "classification": "read-only-before-mutation",
        "pause": [f"{kind}/{name}" for kind, name in pauses],
        "preserved": [f"probe/{c.livez_probe}", f"probe/{c.healthz_probe}"],
        "rollbackCoordinates": rollbacks,
        "replacementStateLoss": [
            "process-local relay counters and registrations",
            "pod emptyDir multiprocess metric files",
        ],
        "mandatoryGates": restoration_order(mode),
        "evidence": [
            "deployment coordinate",
            "termination reason and exit code",
            "events summary",
            "probe and ServiceMonitor coordinates",
            "endpoint status classes",
            "bounded route/cardinality and memory summaries",
            "compute recovery",
            "encrypted E2EE pass/fail",
            "cleanup pass/fail",
        ],
        "stateChanged": {
            "cluster": False,
            "production": False,
            "repository": False,
            "external": False,
        },
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=sorted(MODES), required=True)
    for name in (
        "host",
        "kubeconfig",
        "context",
        "environment",
        "namespace",
        "deployment",
        "container",
        "image",
        "memory-limit",
        "service-monitor",
        "root-probe",
        "metadata-probe",
        "livez-probe",
        "healthz-probe",
        "drill-id",
    ):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--replicas", required=True, type=int)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--acknowledge-state-loss", action="store_true")
    return p


def main(argv=None, runner=subprocess.run) -> int:
    args = parser().parse_args(argv)
    try:
        values = vars(args).copy()
        mode, execute, ack = (
            values.pop("mode"),
            values.pop("execute"),
            values.pop("acknowledge_state_loss"),
        )
        values["kubeconfig"] = Path(values["kubeconfig"])
        c = Coordinates(**values)
        result = plan(mode, c)
        if execute:
            if not ack:
                raise GuardError("--execute requires --acknowledge-state-loss")
            # Exact live classification is intentionally delegated to kubectl; no mutation occurs here.
            check = runner(
                [
                    "kubectl",
                    "--kubeconfig",
                    str(c.kubeconfig),
                    "--context",
                    c.context,
                    "-n",
                    c.namespace,
                    "get",
                    "deployment",
                    c.deployment,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if check.returncode:
                raise GuardError("read-only deployment classification failed")
            raise GuardError("live mutation is not implemented; use the reviewed operator gates")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except GuardError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
