#!/usr/bin/env python3
"""Validate DSPACE release manifests and record deployment evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

UPSTREAM_FIELDS = (
    "schemaVersion",
    "app",
    "applicationVersion",
    "sourceRevision",
    "imageTag",
    "imageDigest",
    "chartVersion",
    "chartDigest",
    "semanticTag",
)
CANDIDATE_FIELDS = UPSTREAM_FIELDS + (
    "recordType",
    "environment",
    "expectedDefaultChatProvider",
    "approvedAt",
    "approvedBy",
)
FINAL_FIELDS = CANDIDATE_FIELDS + (
    "helmRevision",
    "pods",
    "runtimeSourceRevision",
    "runtimeSourceRevisionMethod",
    "verificationResults",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
IMAGE_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*-([0-9a-f]{7})$")
PROVIDERS = {"token-place", "openai"}
REVISION_ANNOTATION = "org.opencontainers.image.revision"
RUNTIME_METHOD = "podImageID+ociRevisionAnnotation"


class ManifestError(ValueError):
    """A release record is missing or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest must be a JSON object")
    return value


def _exact_fields(value: dict[str, Any], expected: tuple[str, ...]) -> None:
    missing = sorted(set(expected) - value.keys())
    unknown = sorted(value.keys() - set(expected))
    if missing or unknown:
        parts = []
        if missing:
            parts.append("missing fields: " + ", ".join(missing))
        if unknown:
            parts.append("unknown fields: " + ", ".join(unknown))
        raise ManifestError("; ".join(parts))


def _validate_upstream(value: dict[str, Any]) -> None:
    if value["schemaVersion"] != 1 or value["app"] != "dspace":
        raise ManifestError("schemaVersion must be 1 and app must be 'dspace'")
    if not isinstance(value["applicationVersion"], str) or not SEMVER_RE.fullmatch(
        value["applicationVersion"]
    ):
        raise ManifestError("applicationVersion must be strict SemVer")
    sha = value["sourceRevision"]
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise ManifestError(
            "sourceRevision must be a full 40-character lowercase Git SHA"
        )
    tag = value["imageTag"]
    match = IMAGE_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        raise ManifestError(
            "imageTag must be an immutable lowercase branch-SHA tag with a seven-character suffix"
        )
    if match.group(1) != sha[:7]:
        raise ManifestError("imageTag suffix does not match sourceRevision")
    for field in ("imageDigest", "chartDigest"):
        if not isinstance(value[field], str) or not DIGEST_RE.fullmatch(value[field]):
            raise ManifestError(f"{field} must be a lowercase sha256 digest")
    if not isinstance(value["chartVersion"], str) or not SEMVER_RE.fullmatch(
        value["chartVersion"]
    ):
        raise ManifestError("chartVersion must be strict SemVer")
    semantic = value["semanticTag"]
    if semantic is not None and (
        not isinstance(semantic, str) or semantic != f"v{value['applicationVersion']}"
    ):
        raise ManifestError(
            "semanticTag must be null or v<applicationVersion> evidence"
        )


def validate(value: dict[str, Any], finalized: bool | None = None) -> dict[str, Any]:
    record_type = value.get("recordType")
    if finalized is None:
        finalized = record_type == "final"
    expected = FINAL_FIELDS if finalized else CANDIDATE_FIELDS
    _exact_fields(value, expected)
    _validate_upstream(value)
    if record_type != ("final" if finalized else "candidate"):
        raise ManifestError("recordType does not match the requested record kind")
    if value["environment"] not in {"staging", "prod"}:
        raise ManifestError("environment must be staging or prod")
    if value["expectedDefaultChatProvider"] not in PROVIDERS:
        raise ManifestError("expectedDefaultChatProvider must be token-place or openai")
    if not isinstance(value["approvedBy"], str) or not value["approvedBy"].strip():
        raise ManifestError("approvedBy must be non-empty")
    approved = value["approvedAt"]
    if not isinstance(approved, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", approved
    ):
        raise ManifestError("approvedAt must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        dt.datetime.strptime(approved, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ManifestError("approvedAt is not a valid UTC timestamp") from exc
    if finalized:
        if (
            not isinstance(value["helmRevision"], int)
            or isinstance(value["helmRevision"], bool)
            or value["helmRevision"] < 1
        ):
            raise ManifestError("helmRevision must be a positive integer")
        pods = value["pods"]
        if not isinstance(pods, list) or not pods:
            raise ManifestError("pods must be a non-empty list")
        names: set[str] = set()
        for pod in pods:
            if not isinstance(pod, dict):
                raise ManifestError("each pod must be an object")
            _exact_fields(pod, ("name", "startTime", "imageID"))
            if not all(isinstance(pod[k], str) and pod[k] for k in pod):
                raise ManifestError("pod evidence values must be non-empty strings")
            if pod["name"] in names:
                raise ManifestError("pod names must be unique")
            names.add(pod["name"])
            if _image_id_digest(pod["imageID"]) != value["imageDigest"]:
                raise ManifestError(
                    f"pod {pod['name']} imageID does not match approved imageDigest"
                )
        if value["runtimeSourceRevision"] != value["sourceRevision"]:
            raise ManifestError("runtimeSourceRevision must match sourceRevision")
        if value["runtimeSourceRevisionMethod"] != RUNTIME_METHOD:
            raise ManifestError(f"runtimeSourceRevisionMethod must be {RUNTIME_METHOD}")
        results = value["verificationResults"]
        if not isinstance(results, list) or not results:
            raise ManifestError("verificationResults must be a non-empty list")
        for result in results:
            if not isinstance(result, dict):
                raise ManifestError("verification results must be objects")
            _exact_fields(result, ("check", "passed", "details"))
            if (
                not isinstance(result["check"], str)
                or not isinstance(result["passed"], bool)
                or not isinstance(result["details"], str)
            ):
                raise ManifestError("verification result fields have invalid types")
            if not result["passed"]:
                raise ManifestError(f"verification failed: {result['check']}")
    return value


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ManifestError(
                f"refusing to overwrite existing record: {path}"
            ) from exc
        # Persist the new directory entry as well as the file contents. Some
        # filesystems otherwise permit a successful return followed by losing
        # the link during a power failure.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not supported on every platform/filesystem.
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)


def candidate(
    upstream: dict[str, Any],
    environment: str,
    provider: str,
    approved_at: str,
    approved_by: str,
) -> dict[str, Any]:
    _exact_fields(upstream, UPSTREAM_FIELDS)
    _validate_upstream(upstream)
    result = {field: upstream[field] for field in UPSTREAM_FIELDS}
    result.update(
        recordType="candidate",
        environment=environment,
        expectedDefaultChatProvider=provider,
        approvedAt=approved_at,
        approvedBy=approved_by,
    )
    return validate(result, False)


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise ManifestError(
            f"command failed ({command[0]}): {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout


def _oras_evidence(oras: str, reference: str) -> tuple[str, str]:
    descriptor = json.loads(
        _run([oras, "manifest", "fetch", "--descriptor", reference])
    )
    manifest = json.loads(_run([oras, "manifest", "fetch", reference]))
    digest = descriptor.get("digest")
    annotations = manifest.get("annotations", {})
    revision = annotations.get(REVISION_ANNOTATION) or descriptor.get(
        "annotations", {}
    ).get(REVISION_ANNOTATION)
    if not isinstance(digest, str) or not isinstance(revision, str):
        raise ManifestError(
            f"OCI descriptor for {reference} lacks digest or revision annotation"
        )
    return digest, revision


def preflight(
    value: dict[str, Any],
    image_ref: str,
    chart_ref: str,
    oras: str,
    environment: str | None = None,
    image_tag: str | None = None,
    chart_version: str | None = None,
) -> list[dict[str, Any]]:
    validate(value, False)
    selected = (
        ("environment", environment),
        ("imageTag", image_tag),
        ("chartVersion", chart_version),
    )
    for field, expected in selected:
        if expected is not None and value[field] != expected:
            raise ManifestError(f"selected {field} does not match approved manifest")
    image_digest, image_revision = _oras_evidence(
        oras, f"{image_ref}:{value['imageTag']}"
    )
    chart_digest, chart_revision = _oras_evidence(
        oras, f"{chart_ref}:{value['chartVersion']}"
    )
    checks = (
        ("imageDigest", image_digest, value["imageDigest"]),
        ("chartDigest", chart_digest, value["chartDigest"]),
        ("imageSourceRevision", image_revision, value["sourceRevision"]),
        ("chartSourceRevision", chart_revision, value["sourceRevision"]),
    )
    results = [
        {
            "check": name,
            "passed": actual == expected,
            "details": f"expected {expected}; resolved {actual}",
        }
        for name, actual, expected in checks
    ]
    failed = [item["check"] for item in results if not item["passed"]]
    if failed:
        raise ManifestError("OCI preflight mismatch: " + ", ".join(failed))
    return results


def _image_id_digest(image_id: str) -> str:
    match = re.search(r"sha256:[0-9a-f]{64}$", image_id)
    if not match:
        raise ManifestError(f"non-canonical pod imageID: {image_id}")
    return match.group(0)


def finalize(
    value: dict[str, Any],
    helm_json: dict[str, Any],
    pods_json: dict[str, Any],
    preflight_results: list[dict[str, Any]],
) -> dict[str, Any]:
    validate(value, False)
    revision = helm_json.get("version")
    pods = []
    for item in pods_json.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses", [])
        if len(statuses) != 1:
            raise ManifestError(
                "DSPACE pods must expose exactly one application container imageID"
            )
        pods.append(
            {
                "name": item.get("metadata", {}).get("name"),
                "startTime": item.get("status", {}).get("startTime"),
                "imageID": statuses[0].get("imageID"),
            }
        )
    pods.sort(key=lambda item: str(item["name"]))
    if not preflight_results:
        raise ManifestError("finalization requires fresh OCI preflight results")
    results = [
        *preflight_results,
        {
            "check": "podImageDigests",
            "passed": True,
            "details": "every running pod imageID matched approved image digest",
        },
    ]
    result = dict(value)
    result.update(
        recordType="final",
        helmRevision=revision,
        pods=pods,
        runtimeSourceRevision=value["sourceRevision"],
        runtimeSourceRevisionMethod=RUNTIME_METHOD,
        verificationResults=results,
    )
    return validate(result, True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("candidate")
    make.add_argument("--upstream", type=Path, required=True)
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--environment", required=True)
    make.add_argument("--provider", required=True)
    make.add_argument("--approved-at", required=True)
    make.add_argument("--approved-by", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--final", action="store_true")
    flight = sub.add_parser("preflight")
    flight.add_argument("--manifest", type=Path, required=True)
    flight.add_argument("--image-ref", default="ghcr.io/democratizedspace/dspace")
    flight.add_argument(
        "--chart-ref", default="ghcr.io/democratizedspace/charts/dspace"
    )
    flight.add_argument(
        "--oras-command", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras")
    )
    flight.add_argument("--environment")
    flight.add_argument("--image-tag")
    flight.add_argument("--chart-version")
    finish = sub.add_parser("finalize")
    finish.add_argument("--manifest", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument("--release", default="dspace")
    finish.add_argument("--namespace", default="dspace")
    finish.add_argument("--image-ref", default="ghcr.io/democratizedspace/dspace")
    finish.add_argument(
        "--chart-ref", default="ghcr.io/democratizedspace/charts/dspace"
    )
    finish.add_argument(
        "--oras-command", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras")
    )
    available = sub.add_parser("check-output")
    available.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "candidate":
            result = candidate(
                _object(args.upstream),
                args.environment,
                args.provider,
                args.approved_at,
                args.approved_by,
            )
            _write_new(args.output, result)
        elif args.command == "validate":
            result = validate(_object(args.manifest), args.final)
            sys.stdout.write(_canonical(result))
        elif args.command == "preflight":
            result = preflight(
                _object(args.manifest),
                args.image_ref,
                args.chart_ref,
                args.oras_command,
                args.environment,
                args.image_tag,
                args.chart_version,
            )
            sys.stdout.write(_canonical(result))
        elif args.command == "finalize":
            source = _object(args.manifest)
            results = preflight(
                source, args.image_ref, args.chart_ref, args.oras_command
            )
            helm = json.loads(
                _run(
                    [
                        "helm",
                        "status",
                        args.release,
                        "--namespace",
                        args.namespace,
                        "-o",
                        "json",
                    ]
                )
            )
            pods = json.loads(
                _run(
                    [
                        "kubectl",
                        "-n",
                        args.namespace,
                        "get",
                        "pods",
                        "-l",
                        "app.kubernetes.io/name=dspace",
                        "-o",
                        "json",
                    ]
                )
            )
            result = finalize(source, helm, pods, results)
            _write_new(args.output, result)
        else:
            if args.output.exists():
                raise ManifestError(
                    f"refusing to overwrite existing record: {args.output}"
                )
    except (ManifestError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
