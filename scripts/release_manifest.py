#!/usr/bin/env python3
"""Validate and enrich DSPACE release manifests without third-party packages."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*-([0-9a-f]{7})$")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

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
PROVIDERS = {"openai"}  # Existing DSPACE configuration contract spelling.
RUNTIME_METHOD = "oci-artifact-revision-and-all-pod-image-digests"


class ManifestError(ValueError):
    """A release record is absent, non-canonical, or internally inconsistent."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{name} must be a JSON object")
    return value


def _exact(data: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = sorted(set(fields) - set(data))
    unknown = sorted(set(data) - set(fields))
    if missing or unknown:
        parts = []
        if missing:
            parts.append("missing fields: " + ", ".join(missing))
        if unknown:
            parts.append("unknown fields: " + ", ".join(unknown))
        raise ManifestError("; ".join(parts))


def validate(data: dict[str, Any], finalized: bool | None = None) -> dict[str, Any]:
    """Return *data* after strict schema and cross-field validation."""
    data = _object(data, "manifest")
    if finalized is None:
        finalized = "helmRevision" in data
    fields = FINAL_FIELDS if finalized else CANDIDATE_FIELDS
    _exact(data, fields)
    if data["schemaVersion"] != 1 or data["app"] != "dspace":
        raise ManifestError("schemaVersion must be 1 and app must be 'dspace'")
    for field in fields:
        if field not in {
            "schemaVersion",
            "helmRevision",
            "pods",
            "verificationResults",
        } and not isinstance(data[field], str):
            raise ManifestError(f"{field} must be a string")
    if not SEMVER_RE.fullmatch(data["applicationVersion"]):
        raise ManifestError("applicationVersion must be strict SemVer")
    if not SHA_RE.fullmatch(data["sourceRevision"]):
        raise ManifestError("sourceRevision must be a full lowercase Git SHA")
    tag = TAG_RE.fullmatch(data["imageTag"])
    if not tag or tag.group(1) != data["sourceRevision"][:7]:
        raise ManifestError("imageTag must be an immutable branch-SHA tag matching sourceRevision")
    if data["imageTag"].startswith(("latest-", "staging-", "prod-", "production-")):
        raise ManifestError("imageTag must not be a mutable or environment coordinate")
    for field in ("imageDigest", "chartDigest"):
        if not DIGEST_RE.fullmatch(data[field]):
            raise ManifestError(f"{field} must be a lowercase sha256 digest")
    if not SEMVER_RE.fullmatch(data["chartVersion"]):
        raise ManifestError("chartVersion must be strict SemVer")
    if data["semanticTag"] and not SEMVER_RE.fullmatch(data["semanticTag"].removeprefix("v")):
        raise ManifestError("semanticTag must be empty or a semantic evidence tag")
    if data["environment"] not in {"staging", "prod"}:
        raise ManifestError("environment must be staging or prod")
    if data["expectedDefaultChatProvider"] not in PROVIDERS:
        raise ManifestError("expectedDefaultChatProvider must be openai")
    if not TIME_RE.fullmatch(data["approvedAt"]):
        raise ManifestError("approvedAt must be a UTC RFC3339 timestamp")
    if not data["approvedBy"].strip():
        raise ManifestError("approvedBy must identify the approving operator")
    if finalized:
        if (
            not isinstance(data["helmRevision"], int)
            or isinstance(data["helmRevision"], bool)
            or data["helmRevision"] < 1
        ):
            raise ManifestError("helmRevision must be a positive integer")
        pods = data["pods"]
        if not isinstance(pods, list) or not pods:
            raise ManifestError("pods must be a non-empty array")
        names: set[str] = set()
        for pod in pods:
            pod = _object(pod, "pod")
            _exact(pod, ("name", "startTime", "imageID"))
            if not all(isinstance(pod[k], str) and pod[k] for k in pod):
                raise ManifestError("pod evidence values must be non-empty strings")
            if pod["name"] in names or not TIME_RE.fullmatch(pod["startTime"]):
                raise ManifestError("pod names must be unique and startTime must be UTC RFC3339")
            names.add(pod["name"])
            digest = pod["imageID"].rsplit("@", 1)[-1]
            if digest != data["imageDigest"]:
                raise ManifestError("every pod imageID must equal the approved imageDigest")
        if data["runtimeSourceRevision"] != data["sourceRevision"]:
            raise ManifestError("runtimeSourceRevision must equal the approved sourceRevision")
        if data["runtimeSourceRevisionMethod"] != RUNTIME_METHOD:
            raise ManifestError("unsupported runtimeSourceRevisionMethod")
        results = data["verificationResults"]
        if not isinstance(results, list) or not results:
            raise ManifestError("verificationResults must be a non-empty array")
        for result in results:
            result = _object(result, "verification result")
            _exact(result, ("name", "passed", "details"))
            if (
                not isinstance(result["name"], str)
                or not result["name"]
                or not isinstance(result["passed"], bool)
                or not isinstance(result["details"], str)
            ):
                raise ManifestError("invalid structured verification result")
            if not result["passed"]:
                raise ManifestError(f"verification failed: {result['name']}")
    return data


def load(path: str | Path) -> dict[str, Any]:
    try:
        return _object(json.loads(Path(path).read_text(encoding="utf-8")), "manifest")
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON manifest {path}: {exc}") from exc


def canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, indent=2, separators=(",", ": ")) + "\n"


def candidate(
    upstream: dict[str, Any], environment: str, provider: str, approved_at: str, approved_by: str
) -> dict[str, Any]:
    _exact(upstream, UPSTREAM_FIELDS)
    result = {field: upstream[field] for field in UPSTREAM_FIELDS}
    result.update(
        environment=environment,
        expectedDefaultChatProvider=provider,
        approvedAt=approved_at,
        approvedBy=approved_by,
    )
    return validate(result, False)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run_json(command: list[str], runner: Runner = subprocess.run) -> dict[str, Any]:
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise ManifestError(
            f"read-only OCI command failed: {' '.join(command)}: {completed.stderr.strip()}"
        )
    try:
        return _object(json.loads(completed.stdout), "OCI command output")
    except json.JSONDecodeError as exc:
        raise ManifestError("OCI command did not return JSON") from exc


def preflight(
    data: dict[str, Any],
    image: str,
    chart: str,
    runner: Runner = subprocess.run,
    environment: str = "",
    image_tag: str = "",
    chart_version: str = "",
) -> None:
    """Read OCI evidence with skopeo/oras and compare it before cluster mutation."""
    validate(data, False)
    for actual, expected, name in (
        (data["environment"], environment, "environment"),
        (data["imageTag"], image_tag, "image tag"),
        (data["chartVersion"], chart_version, "chart version"),
    ):
        if expected and actual != expected:
            raise ManifestError(f"approved {name} {actual!r} does not match requested {expected!r}")
    image_info = _run_json(["skopeo", "inspect", f"docker://{image}:{data['imageTag']}"], runner)
    if image_info.get("Digest") != data["imageDigest"]:
        raise ManifestError("image digest mismatch")
    labels = image_info.get("Labels") or {}
    revision = labels.get("org.opencontainers.image.revision")
    if revision != data["sourceRevision"]:
        raise ManifestError("image source-revision metadata mismatch")
    descriptor = _run_json(
        ["oras", "manifest", "fetch", "--descriptor", f"{chart}:{data['chartVersion']}"], runner
    )
    if descriptor.get("digest") != data["chartDigest"]:
        raise ManifestError("chart digest mismatch")
    annotations = descriptor.get("annotations") or {}
    revision = annotations.get("org.opencontainers.image.revision") or annotations.get(
        "org.opencontainers.artifact.revision"
    )
    if revision != data["sourceRevision"]:
        raise ManifestError("chart source-revision metadata mismatch")


def finalize(
    data: dict[str, Any],
    helm: dict[str, Any],
    pod_list: dict[str, Any],
    results: list[dict[str, Any]],
    oci_revision: str,
) -> dict[str, Any]:
    validate(data, False)
    if oci_revision != data["sourceRevision"]:
        raise ManifestError("OCI artifact revision does not equal approved sourceRevision")
    pods = []
    for item in pod_list.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses", [])
        if not statuses:
            raise ManifestError("running pod lacks resolved container image evidence")
        for status in statuses:
            pods.append(
                {
                    "name": item["metadata"]["name"],
                    "startTime": item["status"]["startTime"],
                    "imageID": status.get("imageID", ""),
                }
            )
    out = dict(data)
    out.update(
        helmRevision=int(helm["version"]),
        pods=pods,
        runtimeSourceRevision=data["sourceRevision"],
        runtimeSourceRevisionMethod=RUNTIME_METHOD,
        verificationResults=results,
    )
    return validate(out, True)


def write_atomic(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path)
    if target.exists():
        raise ManifestError(f"refusing to overwrite existing record: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(canonical(data))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    except FileExistsError as exc:
        raise ManifestError(f"refusing to overwrite existing record: {target}") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


def collect(
    candidate_path: str,
    output: str,
    namespace: str = "dspace",
    release: str = "dspace",
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Collect read-only Helm/pod state and persist a finalized deployment record."""
    data = load(candidate_path)
    helm = _run_json(
        ["helm", "status", release, "--namespace", namespace, "--output", "json"], runner
    )
    pods = _run_json(
        [
            "kubectl",
            "--namespace",
            namespace,
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/instance={release}",
            "--output",
            "json",
        ],
        runner,
    )
    result = finalize(
        data,
        helm,
        pods,
        [
            {
                "name": "ociPreflight",
                "passed": True,
                "details": (
                    "approved image and chart digest/revision metadata matched before mutation"
                ),
            },
            {
                "name": "helmRollout",
                "passed": True,
                "details": "Helm deployment command and rollout waits completed",
            },
            {
                "name": "podImageDigests",
                "passed": True,
                "details": "all resolved running pod image IDs match the approved digest",
            },
        ],
        data["sourceRevision"],
    )
    write_atomic(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("candidate")
    make.add_argument("upstream")
    make.add_argument("--environment", required=True)
    make.add_argument("--provider", default="openai")
    make.add_argument("--approved-at", required=True)
    make.add_argument("--approved-by", required=True)
    make.add_argument("--output", required=True)
    check = sub.add_parser("validate")
    check.add_argument("manifest")
    check.add_argument("--final", action="store_true")
    pre = sub.add_parser("preflight")
    pre.add_argument("manifest")
    pre.add_argument("--image", default="ghcr.io/democratizedspace/dspace")
    pre.add_argument("--chart", default="ghcr.io/democratizedspace/charts/dspace")
    pre.add_argument("--environment", default="")
    pre.add_argument("--image-tag", default="")
    pre.add_argument("--chart-version", default="")
    fin = sub.add_parser("finalize")
    fin.add_argument("manifest")
    fin.add_argument("--helm-json", required=True)
    fin.add_argument("--pods-json", required=True)
    fin.add_argument("--verification-json", required=True)
    fin.add_argument("--oci-revision", required=True)
    fin.add_argument("--output", required=True)
    gather = sub.add_parser("collect")
    gather.add_argument("manifest")
    gather.add_argument("--output", required=True)
    gather.add_argument("--namespace", default="dspace")
    gather.add_argument("--release", default="dspace")
    args = parser.parse_args(argv)
    try:
        if args.command == "candidate":
            write_atomic(
                args.output,
                candidate(
                    load(args.upstream),
                    args.environment,
                    args.provider,
                    args.approved_at,
                    args.approved_by,
                ),
            )
        elif args.command == "validate":
            validate(load(args.manifest), args.final)
        elif args.command == "preflight":
            preflight(
                load(args.manifest),
                args.image,
                args.chart,
                environment=args.environment,
                image_tag=args.image_tag,
                chart_version=args.chart_version,
            )
        elif args.command == "finalize":
            write_atomic(
                args.output,
                finalize(
                    load(args.manifest),
                    load(args.helm_json),
                    load(args.pods_json),
                    json.loads(Path(args.verification_json).read_text()),
                    args.oci_revision,
                ),
            )
        else:
            collect(args.manifest, args.output, args.namespace, args.release)
    except (ManifestError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
