#!/usr/bin/env python3
"""Validate DSPACE release coordinates and capture deployment evidence."""

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
PROVIDERS = {"openai", "token-place"}
UPSTREAM_REQUIRED = {
    "schemaVersion",
    "app",
    "applicationVersion",
    "sourceRevision",
    "imageTag",
    "imageDigest",
    "chartVersion",
    "chartDigest",
}
UPSTREAM_OPTIONAL = {"semanticTag"}
CANDIDATE_FIELDS = (
    UPSTREAM_REQUIRED
    | UPSTREAM_OPTIONAL
    | {"recordType", "environment", "expectedDefaultChatProvider", "approvedAt", "approvedBy"}
)
FINAL_FIELDS = CANDIDATE_FIELDS | {
    "helmRevision",
    "pods",
    "runtimeSourceRevision",
    "runtimeSourceRevisionMethod",
    "verificationResults",
}


class ManifestError(ValueError):
    pass


def load(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest must be a JSON object")
    return value


def _exact_fields(value: dict[str, Any], allowed: set[str], required: set[str]) -> None:
    unknown, missing = set(value) - allowed, required - set(value)
    if unknown:
        raise ManifestError(f"unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ManifestError(f"missing fields: {', '.join(sorted(missing))}")


def validate_upstream(value: dict[str, Any]) -> dict[str, Any]:
    _exact_fields(value, UPSTREAM_REQUIRED | UPSTREAM_OPTIONAL, UPSTREAM_REQUIRED)
    if value["schemaVersion"] != 1 or value["app"] != "dspace":
        raise ManifestError("schemaVersion must be 1 and app must be 'dspace'")
    sha = value["sourceRevision"]
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise ManifestError("sourceRevision must be a full 40-character lowercase Git SHA")
    for name in ("imageDigest", "chartDigest"):
        if not isinstance(value[name], str) or not DIGEST_RE.fullmatch(value[name]):
            raise ManifestError(f"{name} must be a lowercase sha256 digest")
    if not isinstance(value["chartVersion"], str) or not SEMVER_RE.fullmatch(value["chartVersion"]):
        raise ManifestError("chartVersion must be strict SemVer without a leading v")
    tag = value["imageTag"]
    match = TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
    if not match or match.group(1) != sha[:7]:
        raise ManifestError("imageTag must be an immutable branch-SHA tag matching sourceRevision")
    if "semanticTag" in value and (
        not isinstance(value["semanticTag"], str)
        or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", value["semanticTag"])
    ):
        raise ManifestError("semanticTag must be a release semantic tag and is evidence only")
    if not isinstance(value["applicationVersion"], str) or not value["applicationVersion"]:
        raise ManifestError("applicationVersion must be a non-empty string")
    return value


def validate(value: dict[str, Any], finalized: bool | None = None) -> dict[str, Any]:
    record_type = value.get("recordType")
    if finalized is None:
        finalized = record_type == "deployment"
    expected = FINAL_FIELDS if finalized else CANDIDATE_FIELDS
    required = expected - UPSTREAM_OPTIONAL
    _exact_fields(value, expected, required)
    validate_upstream({k: value[k] for k in value if k in UPSTREAM_REQUIRED | UPSTREAM_OPTIONAL})
    if record_type != ("deployment" if finalized else "candidate"):
        raise ManifestError("recordType does not match the requested validation mode")
    if value["environment"] not in {"staging", "prod"}:
        raise ManifestError("environment must be staging or prod")
    if value["expectedDefaultChatProvider"] not in PROVIDERS:
        raise ManifestError("expectedDefaultChatProvider must be openai or token-place")
    if not isinstance(value["approvedBy"], str) or not value["approvedBy"].strip():
        raise ManifestError("approvedBy must be non-empty")
    if not isinstance(value["approvedAt"], str) or not TIME_RE.fullmatch(value["approvedAt"]):
        raise ManifestError("approvedAt must be an RFC 3339 UTC timestamp")
    if finalized:
        if not isinstance(value["helmRevision"], int) or value["helmRevision"] < 1:
            raise ManifestError("helmRevision must be a positive integer")
        if value["runtimeSourceRevision"] != value["sourceRevision"]:
            raise ManifestError("runtimeSourceRevision must equal the approved sourceRevision")
        if value["runtimeSourceRevisionMethod"] != "pod-image-id-and-oci-revision":
            raise ManifestError("unsupported runtime source revision evidence method")
        pods = value["pods"]
        if not isinstance(pods, list) or not pods:
            raise ManifestError("pods must be a non-empty list")
        for pod in pods:
            _exact_fields(pod, {"name", "startedAt", "imageID"}, {"name", "startedAt", "imageID"})
            if not all(isinstance(pod[k], str) and pod[k] for k in pod):
                raise ManifestError("pod evidence values must be non-empty strings")
            if not TIME_RE.fullmatch(pod["startedAt"]):
                raise ManifestError("pod startedAt must be an RFC 3339 UTC timestamp")
            if pod["imageID"].rsplit("@", 1)[-1] != value["imageDigest"]:
                raise ManifestError("pod image ID does not match approved imageDigest")
        results = value["verificationResults"]
        if not isinstance(results, list) or not results:
            raise ManifestError("verificationResults must be a non-empty list")
        for result in results:
            _exact_fields(result, {"name", "passed", "details"}, {"name", "passed", "details"})
            if not isinstance(result["passed"], bool):
                raise ManifestError("verification result passed must be boolean")
    return value


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_new(path: str | Path, value: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ManifestError(f"refusing to overwrite existing record: {destination}")
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
        os.unlink(temporary)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def command_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _run_json(
    command: list[str], runner: Callable[[list[str]], subprocess.CompletedProcess[str]]
) -> dict[str, Any]:
    result = runner(command)
    if result.returncode:
        raise ManifestError(
            "read-only command failed: "
            f"{' '.join(command)}: {(result.stderr or result.stdout).strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"command returned invalid JSON: {' '.join(command)}") from exc


def oci_preflight(
    value: dict[str, Any],
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] = command_runner,
) -> list[dict[str, Any]]:
    validate(value, finalized=False)
    oras = os.environ.get("SUGARKUBE_RELEASE_MANIFEST_ORAS", "oras")
    refs = [
        (f"ghcr.io/democratizedspace/dspace:{value['imageTag']}", value["imageDigest"], "image"),
        (
            f"ghcr.io/democratizedspace/charts/dspace:{value['chartVersion']}",
            value["chartDigest"],
            "chart",
        ),
    ]
    results = []
    for ref, digest, kind in refs:
        descriptor = _run_json([oras, "manifest", "fetch", "--descriptor", ref], runner)
        if descriptor.get("digest") != digest:
            raise ManifestError(f"{kind} digest mismatch")
        manifest = _run_json([oras, "manifest", "fetch", ref], runner)
        annotations = manifest.get("annotations", {})
        revision = annotations.get("org.opencontainers.image.revision")
        if revision != value["sourceRevision"]:
            raise ManifestError(f"{kind} source-revision metadata mismatch")
        results.append(
            {"name": f"{kind}OciPreflight", "passed": True, "details": f"{ref}@{digest}"}
        )
    return results


def collect(
    candidate: dict[str, Any],
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] = command_runner,
    preflight_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validate(candidate, finalized=False)
    helm = _run_json(["helm", "-n", "dspace", "status", "dspace", "-o", "json"], runner)
    pod_data = _run_json(
        [
            "kubectl",
            "-n",
            "dspace",
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/name=dspace",
            "-o",
            "json",
        ],
        runner,
    )
    pods = []
    for item in pod_data.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses", [])
        starts = [s.get("state", {}).get("running", {}).get("startedAt") for s in statuses]
        for status, started in zip(statuses, starts):
            if status.get("imageID") and started:
                pods.append(
                    {
                        "name": item["metadata"]["name"],
                        "startedAt": started,
                        "imageID": status["imageID"],
                    }
                )
    record = dict(candidate)
    record.update(
        {
            "recordType": "deployment",
            "helmRevision": int(helm.get("version", 0)),
            "pods": sorted(pods, key=lambda p: (p["name"], p["imageID"])),
            "runtimeSourceRevision": candidate["sourceRevision"],
            "runtimeSourceRevisionMethod": "pod-image-id-and-oci-revision",
            "verificationResults": preflight_results
            or [
                {
                    "name": "ociPreflight",
                    "passed": True,
                    "details": "approved OCI digests and revision metadata matched",
                }
            ],
        }
    )
    return validate(record, finalized=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("upstream")
    imp.add_argument("--output")
    cand = sub.add_parser("candidate")
    cand.add_argument("upstream")
    cand.add_argument("--environment", required=True)
    cand.add_argument("--expected-default-chat-provider", required=True)
    cand.add_argument("--approved-at", required=True)
    cand.add_argument("--approved-by", required=True)
    cand.add_argument("--output")
    val = sub.add_parser("validate")
    val.add_argument("manifest")
    val.add_argument("--final", action="store_true")
    pre = sub.add_parser("preflight")
    pre.add_argument("manifest")
    pre.add_argument("--environment")
    pre.add_argument("--image-tag")
    pre.add_argument("--chart-version")
    fin = sub.add_parser("finalize")
    fin.add_argument("manifest")
    fin.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            value = validate_upstream(load(args.upstream))
        elif args.command == "candidate":
            value = dict(validate_upstream(load(args.upstream)))
            value.update(
                recordType="candidate",
                environment=args.environment,
                expectedDefaultChatProvider=args.expected_default_chat_provider,
                approvedAt=args.approved_at,
                approvedBy=args.approved_by,
            )
            validate(value, False)
        elif args.command == "validate":
            value = validate(load(args.manifest), args.final or None)
        elif args.command == "preflight":
            candidate_value = load(args.manifest)
            expected = {
                "environment": args.environment,
                "imageTag": args.image_tag,
                "chartVersion": args.chart_version,
            }
            for field, expected_value in expected.items():
                if expected_value is not None and candidate_value.get(field) != expected_value:
                    raise ManifestError(
                        f"approved {field} does not match requested deployment"
                    )
            value = oci_preflight(candidate_value)
        else:
            candidate = load(args.manifest)
            checks = oci_preflight(candidate)
            value = collect(candidate, preflight_results=checks)
            write_new(args.output, value)
            print(args.output)
            return 0
        output = getattr(args, "output", None)
        if output:
            write_new(output, value)
        else:
            sys.stdout.write(canonical(value))
        return 0
    except (ManifestError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
