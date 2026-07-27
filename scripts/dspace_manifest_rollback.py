#!/usr/bin/env python3
"""Fail-closed DSPACE rollback from immutable finalized release evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import dspace_release_manifest as release  # noqa: E402

SCHEMA_VERSION = 1
VERIFIER_CAPABILITIES = {
    "schemaVersion": 1,
    "capabilities": [
        "applicationVersion",
        "runtimeSourceRevision",
        "frontendSourceRevision",
        "defaultProvider",
        "publicJourneys",
    ],
}
JOURNEYS = ("home", "chat")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def run(command: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(command, input=input_text, text=True, capture_output=True)
    if completed.returncode:
        # Verifier/command output can contain credentials.  Report only the
        # executable and status, never stdout, stderr, headers, or bodies.
        raise release.ManifestError(f"command failed ({command[0]}, exit {completed.returncode})")
    return completed.stdout


def json_command(command: list[str], *, input_text: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(run(command, input_text=input_text))
    except json.JSONDecodeError as exc:
        raise release.ManifestError(f"invalid JSON returned by {command[0]}") from exc
    if not isinstance(value, dict):
        raise release.ManifestError(f"{command[0]} returned non-object JSON")
    return value


def validate_capabilities(value: dict[str, Any]) -> None:
    if value != VERIFIER_CAPABILITIES:
        raise release.ManifestError("verifier does not implement the required exact capabilities")


def validate_verifier_result(value: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "schemaVersion",
        "applicationVersion",
        "runtimeSourceRevision",
        "frontendSourceRevision",
        "defaultProvider",
        "journeys",
    }
    if set(value) != expected_fields or value.get("schemaVersion") != 1:
        raise release.ManifestError("verifier result has missing or unknown fields")
    expected = {
        "applicationVersion": target["applicationVersion"],
        "runtimeSourceRevision": target["sourceRevision"],
        "frontendSourceRevision": target["sourceRevision"],
        "defaultProvider": target["expectedDefaultChatProvider"],
    }
    for field, wanted in expected.items():
        if not isinstance(value.get(field), str) or value[field] != wanted:
            raise release.ManifestError(f"verifier {field} mismatch")
    journeys = value.get("journeys")
    if not isinstance(journeys, list) or len(journeys) != len(JOURNEYS):
        raise release.ManifestError("verifier journeys must contain the exact required journeys")
    seen: set[str] = set()
    for item in journeys:
        if not isinstance(item, dict) or set(item) != {"name", "passed"}:
            raise release.ManifestError("verifier journey result has invalid fields")
        if (
            item.get("name") not in JOURNEYS
            or item["name"] in seen
            or item.get("passed") is not True
        ):
            raise release.ManifestError("a required public journey failed or was duplicated")
        seen.add(item["name"])
    if seen != set(JOURNEYS):
        raise release.ManifestError("verifier omitted a required public journey")
    return value


def values_evidence(raw: str, root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    if not raw:
        raise release.ManifestError("the complete values-file chain is required")
    paths: list[Path] = []
    evidence = []
    for entry in raw.split(","):
        supplied = Path(entry)
        path = supplied if supplied.is_absolute() else root / supplied
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise release.ManifestError(f"values file is unavailable: {entry}") from exc
        paths.append(path)
        try:
            portable = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            portable = path.resolve().as_posix()
        evidence.append({"path": portable, "sha256": hashlib.sha256(content).hexdigest()})
    return paths, evidence


def pods(value: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in value.get("items", []):
        meta, spec, status = item.get("metadata", {}), item.get("spec", {}), item.get("status", {})
        result.append(
            {
                "name": meta.get("name"),
                "uid": meta.get("uid"),
                "startTime": status.get("startTime"),
                "terminating": meta.get("deletionTimestamp") is not None,
                "images": [c.get("image") for c in spec.get("containers", [])],
                "imageIDs": [c.get("imageID") for c in status.get("containerStatuses", [])],
            }
        )
    return sorted(result, key=lambda item: str(item["name"]))


def fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode()
    ).hexdigest()


def reserve(path: Path, target_fingerprint: str, invocation: str) -> Path:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise release.ManifestError(f"refusing to overwrite existing record: {path}")
    sidecar = path.with_name(path.name + release.RESERVATION_SUFFIX)
    payload = {
        "schemaVersion": 1,
        "operation": "dspaceManifestRollback",
        "output": str(path),
        "targetManifestFingerprint": target_fingerprint,
        "invocationId": invocation,
    }
    try:
        fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise release.ManifestError(f"evidence destination is already reserved: {sidecar}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return sidecar


def write_evidence(path: Path, sidecar: Path, value: dict[str, Any]) -> None:
    release._write_new(path.expanduser().resolve(strict=False), value)
    sidecar.unlink()


def helm_status(helm: str, release_name: str, namespace: str) -> dict[str, Any]:
    return json_command([helm, "status", release_name, "--namespace", namespace, "-o", "json"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=("staging", "prod"))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--verifier", required=True)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--values", required=True)
    parser.add_argument("--release", default="dspace")
    parser.add_argument("--namespace", default="dspace")
    parser.add_argument("--cluster-environment", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--oras", default="oras")
    args = parser.parse_args(argv)
    reserved: Path | None = None
    mutated = False
    try:
        target = release._object(args.manifest)
        release.validate(target, True)
        if target["environment"] != args.environment:
            raise release.ManifestError("target manifest environment does not match selection")
        if args.cluster_environment != args.environment:
            raise release.ManifestError("connected cluster environment does not match selection")
        candidate = release.candidate_from_final(target)
        preflight = release.preflight(
            candidate,
            release.IMAGE_REF,
            "oci://" + release.CHART_REF,
            args.oras,
            environment=args.environment,
        )
        root = Path(__file__).resolve().parents[1]
        value_paths, value_records = values_evidence(args.values, root)
        verifier = Path(args.verifier)
        if not verifier.is_file() or not os.access(verifier, os.X_OK):
            raise release.ManifestError("verifier must name an available executable file")
        validate_capabilities(json_command([str(verifier), "capabilities"]))
        chart = release.chart_coordinate(candidate)
        template = [
            args.helm,
            "template",
            args.release,
            chart,
            "--namespace",
            args.namespace,
            "--set-string",
            f"image.tag={target['imageTag']}",
        ]
        for path in value_paths:
            template.extend(["-f", str(path)])
        run(template)
        before_helm = helm_status(args.helm, args.release, args.namespace)
        before_pods_json = json_command(
            [
                args.kubectl,
                "--kubeconfig",
                args.kubeconfig,
                "-n",
                args.namespace,
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/instance={args.release}",
                "-o",
                "json",
            ]
        )
        before = pods(before_pods_json)
        summary = {
            "current": {
                "helmRevision": before_helm.get("version"),
                "chartName": before_helm.get("chart", {}).get("metadata", {}).get("name"),
                "chartVersion": before_helm.get("chart", {}).get("metadata", {}).get("version"),
                "pods": before,
            },
            "target": {
                "chartVersion": target["chartVersion"],
                "chartDigest": target["chartDigest"],
                "imageTag": target["imageTag"],
                "imageDigest": target["imageDigest"],
                "sourceRevision": target["sourceRevision"],
            },
        }
        print(json.dumps(summary, sort_keys=True))
        current_images = {image for pod in before for image in pod["images"]}
        if (
            before_helm.get("chart", {}).get("metadata", {}).get("version")
            == target["chartVersion"]
            and current_images == {f"{release.IMAGE_REF}:{target['imageTag']}"}
            and all(
                release._image_id_digest(image_id) == target["imageDigest"]
                for pod in before
                for image_id in pod["imageIDs"]
            )
        ):
            raise release.ManifestError("refusing exact no-op rollback")
        confirmation = f"dspace:prod:{target['sourceRevision']}"
        if args.environment == "prod" and args.confirm != confirmation:
            raise release.ManifestError(
                f"production confirmation must exactly equal {confirmation}"
            )
        started_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        invocation = str(uuid.uuid4())
        target_fp = fingerprint(target)
        reserved = reserve(args.evidence, target_fp, invocation)
        description = f"sugarkube-dspace-manifest-rollback:{invocation}:{reserved}"
        upgrade = [
            args.helm,
            "upgrade",
            args.release,
            chart,
            "--namespace",
            args.namespace,
            "--description",
            description,
            "--set-string",
            f"image.tag={target['imageTag']}",
            "--wait",
        ]
        for path in value_paths:
            upgrade.extend(["-f", str(path)])
        mutated = True
        run(upgrade)
        run(
            [
                args.kubectl,
                "--kubeconfig",
                args.kubeconfig,
                "-n",
                args.namespace,
                "rollout",
                "status",
                "deployment/dspace",
                "--timeout=5m",
            ]
        )
        post_pods_json = release._settle_release_pods(
            [
                args.kubectl,
                "--kubeconfig",
                args.kubeconfig,
                "-n",
                args.namespace,
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/instance={args.release}",
                "-o",
                "json",
            ],
            runner=run,
        )
        workloads = json_command(
            [
                args.kubectl,
                "--kubeconfig",
                args.kubeconfig,
                "-n",
                args.namespace,
                "get",
                "replicasets,deployments",
                "-l",
                f"app.kubernetes.io/instance={args.release}",
                "-o",
                "json",
            ]
        )
        after_helm = helm_status(args.helm, args.release, args.namespace)
        after = pods(post_pods_json)
        if (
            not isinstance(before_helm.get("version"), int)
            or after_helm.get("version") <= before_helm["version"]
        ):
            raise release.ManifestError("Helm revision did not advance")
        finalized = release.finalize(
            candidate,
            after_helm,
            post_pods_json,
            workloads,
            preflight,
            environment=args.environment,
            image_tag=target["imageTag"],
            chart_version=target["chartVersion"],
            release=args.release,
            namespace=args.namespace,
            cluster_environment=args.cluster_environment,
            invocation_description=description,
        )
        expected_changed = (
            current_images != {f"{release.IMAGE_REF}:{target['imageTag']}"}
            or before_helm.get("chart", {}).get("metadata", {}).get("version")
            != target["chartVersion"]
        )
        old_ids = {(p["uid"], p["startTime"]) for p in before}
        new_ids = {(p["uid"], p["startTime"]) for p in after}
        if expected_changed and (old_ids & new_ids or old_ids == new_ids):
            raise release.ManifestError(
                "target artifact changed but serving pod identities were not replaced"
            )
        request = {
            "schemaVersion": 1,
            "applicationVersion": target["applicationVersion"],
            "sourceRevision": target["sourceRevision"],
            "defaultProvider": target["expectedDefaultChatProvider"],
            "requiredJourneys": list(JOURNEYS),
        }
        verification = validate_verifier_result(
            json_command([str(verifier), "verify"], input_text=canonical(request)), target
        )
        stable = helm_status(args.helm, args.release, args.namespace)
        if (
            stable.get("version") != after_helm.get("version")
            or stable.get("info", {}).get("status") != "deployed"
        ):
            raise release.ManifestError("Helm revision changed during evidence collection")
        completed_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence = {
            "schemaVersion": SCHEMA_VERSION,
            "operation": "dspaceManifestRollback",
            "targetManifestFingerprint": target_fp,
            "environment": args.environment,
            "release": args.release,
            "namespace": args.namespace,
            "invocationId": invocation,
            "target": {
                k: target[k]
                for k in (
                    "chartVersion",
                    "chartDigest",
                    "imageTag",
                    "imageDigest",
                    "sourceRevision",
                    "applicationVersion",
                    "expectedDefaultChatProvider",
                )
            },
            "values": value_records,
            "sugarkubeRevision": run(["git", "-C", str(root), "rev-parse", "HEAD"]).strip(),
            "before": {"helmRevision": before_helm["version"], "pods": before},
            "after": {"helmRevision": after_helm["version"], "pods": after},
            "verification": {
                "oci": preflight,
                "cluster": finalized["verificationResults"],
                "runtime": verification,
            },
            "startedAt": started_at,
            "completedAt": completed_at,
        }
        write_evidence(args.evidence, reserved, evidence)
        return 0
    except (release.ManifestError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if reserved is not None or mutated:
            print(
                "Cluster state may have changed; reservation and diagnostics are preserved "
                "for reconciliation. Do not retry automatically.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
