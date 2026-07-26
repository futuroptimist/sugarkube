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
from typing import Any, Callable

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
IMAGE_TAG = re.compile(r"^(?:main|v[0-9]+)-([0-9a-f]{7})$")
PROVIDERS = {"openai", "token-place"}
UPSTREAM = (
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
CANDIDATE = UPSTREAM + ("environment", "expectedDefaultChatProvider", "approvedAt", "approvedBy")
FINAL = CANDIDATE + (
    "helmRevision",
    "pods",
    "runtimeSourceRevision",
    "runtimeSourceRevisionMethod",
    "verificationResults",
)
RUNTIME_METHOD = "oci-revision-and-all-pod-image-digests"


class ManifestError(ValueError):
    """A release record is absent, malformed, or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest must be a JSON object")
    return value


def _keys(value: dict[str, Any], expected: tuple[str, ...]) -> None:
    missing = sorted(set(expected) - value.keys())
    unknown = sorted(value.keys() - set(expected))
    if missing or unknown:
        details = []
        if missing:
            details.append("missing fields: " + ", ".join(missing))
        if unknown:
            details.append("unknown fields: " + ", ".join(unknown))
        raise ManifestError("; ".join(details))


def validate(value: dict[str, Any], *, finalized: bool = False) -> dict[str, Any]:
    _keys(value, FINAL if finalized else CANDIDATE)
    if value["schemaVersion"] != 1 or value["app"] != "dspace":
        raise ManifestError("schemaVersion must be 1 and app must be dspace")
    for name in ("applicationVersion", "chartVersion"):
        if not isinstance(value[name], str) or not SEMVER.fullmatch(value[name]):
            raise ManifestError(f"{name} must be strict SemVer without a leading v")
    if not isinstance(value["sourceRevision"], str) or not SHA.fullmatch(value["sourceRevision"]):
        raise ManifestError("sourceRevision must be a full lowercase 40-character Git SHA")
    for name in ("imageDigest", "chartDigest"):
        if not isinstance(value[name], str) or not DIGEST.fullmatch(value[name]):
            raise ManifestError(f"{name} must be a lowercase sha256 digest")
    tag = value["imageTag"]
    match = IMAGE_TAG.fullmatch(tag) if isinstance(tag, str) else None
    if not match or match.group(1) != value["sourceRevision"][:7]:
        raise ManifestError(
            "imageTag must be an immutable main-<7sha> or vN-<7sha> matching sourceRevision"
        )
    if value["semanticTag"] != f"v{value['applicationVersion']}":
        raise ManifestError("semanticTag must equal v<applicationVersion> and is evidence only")
    if value["environment"] not in {"staging", "prod"}:
        raise ManifestError("environment must be staging or prod")
    if value["expectedDefaultChatProvider"] not in PROVIDERS:
        raise ManifestError("expectedDefaultChatProvider must be openai or token-place")
    if not isinstance(value["approvedBy"], str) or not value["approvedBy"].strip():
        raise ManifestError("approvedBy must be non-empty")
    try:
        approved = dt.datetime.fromisoformat(str(value["approvedAt"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError("approvedAt must be an RFC 3339 timestamp") from exc
    if approved.tzinfo is None:
        raise ManifestError("approvedAt must include a timezone")
    if finalized:
        if not isinstance(value["helmRevision"], int) or value["helmRevision"] < 1:
            raise ManifestError("helmRevision must be a positive integer")
        pods = value["pods"]
        if not isinstance(pods, list) or not pods:
            raise ManifestError("pods must be a non-empty list")
        for pod in pods:
            if not isinstance(pod, dict):
                raise ManifestError("each pod must be an object")
            _keys(pod, ("name", "startedAt", "imageID"))
            if not all(isinstance(pod[k], str) and pod[k] for k in pod):
                raise ManifestError("pod evidence values must be non-empty strings")
            if (
                pod["imageID"].removeprefix("docker-pullable://").split("@")[-1]
                != value["imageDigest"]
            ):
                raise ManifestError(
                    f"pod {pod['name']} imageID does not match approved imageDigest"
                )
        if value["runtimeSourceRevision"] != value["sourceRevision"]:
            raise ManifestError("runtimeSourceRevision must equal approved sourceRevision")
        if value["runtimeSourceRevisionMethod"] != RUNTIME_METHOD:
            raise ManifestError("unsupported runtimeSourceRevisionMethod")
        results = value["verificationResults"]
        if (
            not isinstance(results, list)
            or not results
            or any(
                not isinstance(item, dict)
                or set(item) != {"name", "passed", "details"}
                or not isinstance(item["passed"], bool)
                for item in results
            )
        ):
            raise ManifestError("verificationResults must contain canonical structured results")
    return value


def upstream(value: dict[str, Any]) -> dict[str, Any]:
    _keys(value, UPSTREAM)
    # Candidate-only validation supplies the environment and approval fields.
    trial = {
        **value,
        "environment": "staging",
        "expectedDefaultChatProvider": "openai",
        "approvedAt": "2000-01-01T00:00:00Z",
        "approvedBy": "validation",
    }
    validate(trial)
    return value


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def atomic_create(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ManifestError(f"refusing to overwrite existing record: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # fails closed if another writer won the race
    except FileExistsError as exc:
        raise ManifestError(f"refusing to overwrite existing record: {path}") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def command_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _run_json(runner: Runner, command: list[str], label: str) -> dict[str, Any]:
    result = runner(command)
    if result.returncode:
        raise ManifestError(f"{label} failed: {(result.stderr or result.stdout).strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{label} did not return JSON") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{label} did not return a JSON object")
    return data


def preflight(value: dict[str, Any], runner: Runner = command_runner) -> None:
    """Read only OCI verification using crane and oras, both registry-native clients."""
    validate(value)
    image = f"ghcr.io/democratizedspace/dspace:{value['imageTag']}"
    digest = runner(["crane", "digest", image])
    if digest.returncode or digest.stdout.strip() != value["imageDigest"]:
        raise ManifestError("resolved image-index digest does not match imageDigest")
    config = _run_json(runner, ["crane", "config", image], "image config inspection")
    revision = config.get("config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
    if revision != value["sourceRevision"]:
        raise ManifestError("image source-revision metadata does not match sourceRevision")
    chart = f"ghcr.io/democratizedspace/charts/dspace:{value['chartVersion']}"
    manifest = _run_json(runner, ["oras", "manifest", "fetch", chart], "chart inspection")
    if manifest.get("digest") != value["chartDigest"]:
        raise ManifestError("resolved chart OCI digest does not match chartDigest")
    annotations = manifest.get("annotations", {})
    if annotations.get("org.opencontainers.image.revision") != value["sourceRevision"]:
        raise ManifestError("chart source-revision metadata does not match sourceRevision")


def finalize(
    candidate: dict[str, Any],
    helm: dict[str, Any],
    kube: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    validate(candidate)
    pods = []
    for item in kube.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses", [])
        if len(statuses) != 1:
            raise ManifestError("each DSPACE pod must expose exactly one application container")
        pods.append(
            {
                "name": item["metadata"]["name"],
                "startedAt": item["status"]["startTime"],
                "imageID": statuses[0]["imageID"],
            }
        )
    record = {
        **candidate,
        "helmRevision": int(helm["version"]),
        "pods": sorted(pods, key=lambda p: p["name"]),
        "runtimeSourceRevision": candidate["sourceRevision"],
        "runtimeSourceRevisionMethod": RUNTIME_METHOD,
        "verificationResults": results,
    }
    return validate(record, finalized=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    candidate = sub.add_parser("candidate")
    candidate.add_argument("--upstream", type=Path, required=True)
    candidate.add_argument("--environment", required=True)
    candidate.add_argument("--expected-default-chat-provider", required=True)
    candidate.add_argument("--approved-at", required=True)
    candidate.add_argument("--approved-by", required=True)
    candidate.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("manifest", type=Path)
    check.add_argument("--final", action="store_true")
    flight = sub.add_parser("preflight")
    flight.add_argument("manifest", type=Path)
    flight.add_argument("--environment")
    flight.add_argument("--image-tag")
    flight.add_argument("--chart-version")
    finish = sub.add_parser("finalize")
    finish.add_argument("manifest", type=Path)
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument("--namespace", default="dspace")
    finish.add_argument("--release", default="dspace")
    finish.add_argument("--verification-results", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "candidate":
            value = {
                **upstream(_object(args.upstream)),
                "environment": args.environment,
                "expectedDefaultChatProvider": args.expected_default_chat_provider,
                "approvedAt": args.approved_at,
                "approvedBy": args.approved_by,
            }
            atomic_create(args.output, validate(value))
        elif args.command == "validate":
            value = validate(_object(args.manifest), finalized=args.final)
            if args.manifest.read_text(encoding="utf-8") != canonical(value):
                raise ManifestError("manifest JSON is not canonical; regenerate it")
        elif args.command == "preflight":
            value = validate(_object(args.manifest))
            comparisons = (
                ("environment", args.environment),
                ("imageTag", args.image_tag),
                ("chartVersion", args.chart_version),
            )
            for field, supplied in comparisons:
                if supplied is not None and value[field] != supplied:
                    raise ManifestError(f"approved {field} does not match deployment coordinate")
            preflight(value)
        else:
            candidate_value = validate(_object(args.manifest))
            helm = _run_json(
                command_runner,
                ["helm", "status", args.release, "-n", args.namespace, "-o", "json"],
                "Helm evidence",
            )
            kube = _run_json(
                command_runner,
                [
                    "kubectl",
                    "-n",
                    args.namespace,
                    "get",
                    "pods",
                    "-l",
                    f"app.kubernetes.io/instance={args.release}",
                    "-o",
                    "json",
                ],
                "pod evidence",
            )
            results = json.loads(args.verification_results.read_text(encoding="utf-8"))
            atomic_create(args.output, finalize(candidate_value, helm, kube, results))
    except (ManifestError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
