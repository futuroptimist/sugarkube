#!/usr/bin/env python3
"""Fail-closed live-staging prerequisite for a DSPACE production promotion."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts import dspace_release_manifest as release

COORDINATES = (
    "applicationVersion",
    "sourceRevision",
    "imageTag",
    "imageDigest",
    "chartVersion",
    "chartDigest",
    "semanticTag",
    "expectedDefaultChatProvider",
)


class GateError(ValueError):
    """A safely reportable staging-gate failure."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--staging-evidence", type=Path, required=True)
    parser.add_argument("--smoke-runner", type=Path, required=True)
    parser.add_argument("--config", default="")
    parser.add_argument("--kubeconfig", required=True)
    args = parser.parse_args(argv)
    try:
        candidate = release.validate(release._object(args.manifest), False)
        evidence = release.validate(release._object(args.staging_evidence), True)
        if candidate["environment"] != "prod" or evidence["environment"] != "staging":
            raise GateError("manifest/evidence mismatch")
        if any(candidate[key] != evidence[key] for key in COORDINATES):
            raise GateError("manifest/evidence mismatch")
        status = subprocess.run(
            [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "status",
                "dspace",
                "--namespace",
                "dspace",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode:
            raise GateError("staging drift")
        try:
            live = json.loads(status.stdout)
        except json.JSONDecodeError as exc:
            raise GateError("staging drift") from exc
        if live.get("version") != evidence["helmRevision"]:
            raise GateError("staging drift")
        verifier = Path(__file__).with_name("dspace_runtime_verifier.py")
        command = [
            str(verifier),
            "verify",
            "--environment",
            "staging",
            "--release",
            "dspace",
            "--namespace",
            "dspace",
            "--manifest",
            str(args.staging_evidence),
            "--smoke-runner",
            str(args.smoke_runner),
            "--kubeconfig",
            args.kubeconfig,
        ]
        if args.config:
            command += ["--config", args.config]
        checked = subprocess.run(command, capture_output=True, text=True, check=False)
        if checked.returncode:
            raise GateError("staging drift")
    except (release.ManifestError, OSError, KeyError, GateError) as exc:
        label = str(exc) if isinstance(exc, GateError) else "manifest/evidence mismatch"
        print(f"ERROR: DSPACE production gate: {label}", file=sys.stderr)
        return 2
    print("DSPACE production staging gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
