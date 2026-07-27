#!/usr/bin/env python3
"""Fail-closed rollback of DSPACE to an approved, finalized release record."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from scripts import dspace_release_manifest as release

SCHEMA_VERSION = 1
OPERATION = "dspaceManifestRollback"
VERIFY_CAPABILITIES = (
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
)
RESULT_FIELDS = (
    "schemaVersion",
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "journeys",
)


class RollbackError(ValueError):
    """A rollback safety invariant was not satisfied."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def run(command: list[str]) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode:
        # Tool output can contain credentials or response bodies. Deliberately report
        # only the executable and exit status.
        raise RollbackError(
            f"{Path(command[0]).name} failed with exit status {completed.returncode}"
        )
    return completed.stdout


def json_run(runner: Callable[[list[str]], str], command: list[str]) -> dict[str, Any]:
    try:
        result = json.loads(runner(command))
    except json.JSONDecodeError as exc:
        raise RollbackError(f"{Path(command[0]).name} returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RollbackError(f"{Path(command[0]).name} returned non-object JSON")
    return result


def exact_fields(value: dict[str, Any], fields: tuple[str, ...], what: str) -> None:
    if set(value) != set(fields):
        raise RollbackError(f"{what} has missing or unknown fields")


def target_candidate(final: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate final evidence and project its approved immutable candidate."""
    release.validate(final, True)
    candidate = {field: final[field] for field in release.CANDIDATE_FIELDS}
    candidate["recordType"] = "candidate"
    return release.validate(candidate, False)


def manifest_fingerprint(final: dict[str, Any]) -> str:
    release.validate(final, True)
    return "sha256:" + hashlib.sha256(canonical(final).encode()).hexdigest()


def validate_capabilities(value: dict[str, Any]) -> None:
    exact_fields(value, ("schemaVersion", "capabilities"), "verifier capabilities")
    if value["schemaVersion"] != 1 or not isinstance(value["capabilities"], dict):
        raise RollbackError("verifier capabilities use an incompatible schema")
    exact_fields(value["capabilities"], VERIFY_CAPABILITIES, "verifier capabilities")
    if any(value["capabilities"][name] is not True for name in VERIFY_CAPABILITIES):
        raise RollbackError("verifier cannot establish every required capability")


def validate_verifier_result(value: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Validate the reusable DSPACE runtime/frontend/journey proof contract."""
    exact_fields(value, RESULT_FIELDS, "verifier result")
    expected = {
        "schemaVersion": 1,
        "applicationVersion": target["applicationVersion"],
        "runtimeSourceRevision": target["sourceRevision"],
        "frontendSourceRevision": target["sourceRevision"],
        "defaultProvider": target["expectedDefaultChatProvider"],
    }
    for field, wanted in expected.items():
        if value[field] != wanted or isinstance(value[field], bool):
            raise RollbackError(f"verifier {field} does not match approved target")
    journeys = value["journeys"]
    if not isinstance(journeys, list) or not journeys:
        raise RollbackError("verifier must report public journeys")
    names: set[str] = set()
    for journey in journeys:
        if not isinstance(journey, dict):
            raise RollbackError("verifier journey must be an object")
        exact_fields(journey, ("name", "passed"), "verifier journey")
        if not isinstance(journey["name"], str) or not journey["name"] or journey["name"] in names:
            raise RollbackError("verifier journey names must be unique non-empty strings")
        if journey["passed"] is not True:
            raise RollbackError(f"public journey failed: {journey['name']}")
        names.add(journey["name"])
    if "/chat" not in names:
        raise RollbackError("verifier result must include release-appropriate /chat journey")
    return value


def values_evidence(raw: str, root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    paths: list[Path] = []
    evidence: list[dict[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise RollbackError(f"values file is not readable: {item}") from exc
        paths.append(path)
        try:
            portable = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            portable = path.resolve().as_posix()
        evidence.append({"path": portable, "sha256": hashlib.sha256(data).hexdigest()})
    if not paths:
        raise RollbackError("DSPACE values chain is empty")
    return paths, evidence


def pod_identities(
    pods: dict[str, Any], target: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    result = []
    for pod in pods.get("items", []):
        metadata = pod.get("metadata", {})
        status = pod.get("status", {})
        containers = pod.get("spec", {}).get("containers", [])
        statuses = {item.get("name"): item for item in status.get("containerStatuses", [])}
        if metadata.get("deletionTimestamp") is not None:
            raise RollbackError("terminating old DSPACE pod remains")
        if target is not None:
            if status.get("phase") != "Running" or not any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in status.get("conditions", [])
            ):
                raise RollbackError("all DSPACE pods must be Running and Ready")
        for container in containers:
            state = statuses.get(container.get("name"), {})
            identity = {
                "name": metadata.get("name"),
                "uid": metadata.get("uid"),
                "startTime": status.get("startTime"),
                "container": container.get("name"),
                "image": container.get("image"),
                "imageID": state.get("imageID"),
            }
            if not all(isinstance(identity[k], str) and identity[k] for k in identity):
                raise RollbackError("pod identity evidence is incomplete")
            if target is not None:
                wanted = f"{release.IMAGE_REF}:{target['imageTag']}"
                if identity["image"] != wanted:
                    raise RollbackError(
                        "DSPACE container does not declare the target immutable image"
                    )
                try:
                    digest = release._image_id_digest(identity["imageID"])
                except release.ManifestError as exc:
                    raise RollbackError(str(exc)) from exc
                if digest != target["imageDigest"]:
                    raise RollbackError("DSPACE container imageID does not match target digest")
            result.append(identity)
    if not result:
        raise RollbackError("no release-owned DSPACE pod containers found")
    return sorted(result, key=lambda item: (item["name"], item["container"]))


def helm_identity(value: dict[str, Any], release_name: str, namespace: str) -> dict[str, Any]:
    metadata = value.get("chart", {}).get("metadata", {})
    info = value.get("info", {})
    result = {
        "release": value.get("name"),
        "namespace": value.get("namespace"),
        "revision": value.get("version"),
        "status": info.get("status"),
        "chartName": metadata.get("name"),
        "chartVersion": metadata.get("version"),
    }
    if result["release"] != release_name or result["namespace"] != namespace:
        raise RollbackError("Helm status identifies the wrong release or namespace")
    if not isinstance(result["revision"], int) or isinstance(result["revision"], bool):
        raise RollbackError("Helm status lacks a numeric revision")
    return result


def reserve(
    path: Path, fingerprint: str, environment: str, release_name: str, namespace: str
) -> tuple[str, Path]:
    output = path.resolve(strict=False)
    sidecar = release.reservation_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise RollbackError(f"refusing to overwrite rollback evidence: {output}")
    invocation = secrets.token_hex(32)
    record = {
        "schemaVersion": 1,
        "operation": OPERATION,
        "output": str(output),
        "targetManifestFingerprint": fingerprint,
        "environment": environment,
        "release": release_name,
        "namespace": namespace,
        "invocationId": invocation,
    }
    try:
        fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RollbackError(f"rollback evidence is already reserved: {sidecar}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return invocation, sidecar


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise RollbackError(f"refusing to overwrite rollback evidence: {path}") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


def execute(args: argparse.Namespace, runner: Callable[[list[str]], str] = run) -> dict[str, Any]:
    started = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if not args.manifest.is_file():
        raise RollbackError(f"finalized target manifest does not exist: {args.manifest}")
    try:
        final = json.loads(args.manifest.read_text(encoding="utf-8"))
        target = target_candidate(final)
    except (OSError, json.JSONDecodeError, release.ManifestError) as exc:
        raise RollbackError(f"invalid finalized target manifest: {exc}") from exc
    if target["environment"] != args.environment:
        raise RollbackError("target manifest environment does not match selected environment")

    config = json_run(
        runner,
        [
            args.python,
            str(args.root / "scripts/app_config.py"),
            "json",
            "--app",
            "dspace",
            "--env",
            args.environment,
        ],
    )
    required = (
        "SUGARKUBE_APP",
        "SUGARKUBE_ENV",
        "SUGARKUBE_CHART",
        "SUGARKUBE_RELEASE",
        "SUGARKUBE_NAMESPACE",
        "SUGARKUBE_VALUES",
    )
    if any(not isinstance(config.get(key), str) or not config[key] for key in required):
        raise RollbackError("resolved DSPACE environment configuration is incomplete")
    if config["SUGARKUBE_CHART"].removeprefix("oci://") != release.CHART_REF:
        raise RollbackError("resolved DSPACE chart is not the canonical chart")
    values, value_records = values_evidence(config["SUGARKUBE_VALUES"], args.root)
    release_name, namespace = config["SUGARKUBE_RELEASE"], config["SUGARKUBE_NAMESPACE"]

    runner(
        [
            args.just,
            "--justfile",
            str(args.root / "justfile"),
            "assert-cluster-env",
            args.environment,
            os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config")),
        ]
    )
    oci = release.preflight(
        target,
        release.IMAGE_REF,
        config["SUGARKUBE_CHART"],
        args.oras,
        environment=args.environment,
        runner=runner,
    )
    chart = release.chart_coordinate(target)
    value_args = [part for path in values for part in ("-f", str(path))]
    runner(
        [
            args.helm,
            "template",
            release_name,
            chart,
            "--namespace",
            namespace,
            *value_args,
            "--set",
            f"image.tag={target['imageTag']}",
        ]
    )

    validate_capabilities(json_run(runner, [str(args.verifier), "capabilities"]))
    before_helm = helm_identity(
        json_run(
            runner, [args.helm, "status", release_name, "--namespace", namespace, "-o", "json"]
        ),
        release_name,
        namespace,
    )
    pod_command = [
        args.kubectl,
        "-n",
        namespace,
        "get",
        "pods",
        "-l",
        f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={release_name}",
        "-o",
        "json",
    ]
    before_pods_json = json_run(runner, pod_command)
    before_pods = pod_identities(before_pods_json)
    workload_command = [
        args.kubectl,
        "-n",
        namespace,
        "get",
        "replicasets,deployments",
        "-l",
        f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={release_name}",
        "-o",
        "json",
    ]
    # Capture the ownership objects during read-only preflight as well as after rollout.
    json_run(runner, workload_command)
    current_digest = sorted({p["imageID"].rsplit("@", 1)[-1] for p in before_pods})
    summary = {
        "current": {
            **before_helm,
            "imageCoordinates": sorted({p["image"] for p in before_pods}),
            "imageDigests": current_digest,
        },
        "target": {
            "chartName": "dspace",
            "chartVersion": target["chartVersion"],
            "chartDigest": target["chartDigest"],
            "imageTag": target["imageTag"],
            "imageDigest": target["imageDigest"],
            "sourceRevision": target["sourceRevision"],
        },
    }
    print(json.dumps(summary, sort_keys=True))
    expected_image = f"{release.IMAGE_REF}:{target['imageTag']}"
    if (
        before_helm["chartName"] == "dspace"
        and before_helm["chartVersion"] == target["chartVersion"]
        and {p["image"] for p in before_pods} == {expected_image}
        and set(current_digest) == {target["imageDigest"]}
    ):
        raise RollbackError("rollback target is already active; refusing exact no-op")
    if args.environment == "prod":
        wanted = f"dspace:prod:{target['sourceRevision']}"
        if args.confirm != wanted:
            raise RollbackError(f"production confirmation must exactly equal {wanted}")

    fingerprint = manifest_fingerprint(final)
    invocation, sidecar = reserve(
        args.evidence, fingerprint, args.environment, release_name, namespace
    )
    description = f"sugarkube-dspace-manifest-rollback:{invocation}"
    mutated = False
    try:
        runner(
            [
                args.helm,
                "upgrade",
                release_name,
                chart,
                "--namespace",
                namespace,
                "--description",
                description,
                *value_args,
                "--set",
                f"image.tag={target['imageTag']}",
            ]
        )
        mutated = True
        runner(
            [
                args.kubectl,
                "-n",
                namespace,
                "rollout",
                "status",
                f"deployment/{release_name}",
                f"--timeout={args.timeout}",
            ]
        )
        after_raw = json_run(
            runner, [args.helm, "status", release_name, "--namespace", namespace, "-o", "json"]
        )
        after_helm = helm_identity(after_raw, release_name, namespace)
        if after_helm["status"] != "deployed" or after_helm["revision"] <= before_helm["revision"]:
            raise RollbackError("Helm revision did not advance to a deployed release")
        if (
            after_helm["chartName"] != "dspace"
            or after_helm["chartVersion"] != target["chartVersion"]
        ):
            raise RollbackError("installed chart identity/version does not match target")
        settled_pods_json = release._settle_release_pods(pod_command, runner=runner)
        workloads_json = json_run(runner, workload_command)
        # Reuse the release-manifest workflow's strict Helm, Deployment/ReplicaSet,
        # readiness, declared-image, image-ID, and OCI-result validation.
        try:
            release.finalize(
                target,
                after_raw,
                settled_pods_json,
                workloads_json,
                oci,
                environment=args.environment,
                image_tag=target["imageTag"],
                chart_version=target["chartVersion"],
                release=release_name,
                namespace=namespace,
                cluster_environment=args.environment,
                invocation_description=description,
            )
        except release.ManifestError as exc:
            raise RollbackError(str(exc)) from exc
        after_pods = pod_identities(settled_pods_json, target)
        old = {(p["uid"], p["startTime"]) for p in before_pods}
        new = {(p["uid"], p["startTime"]) for p in after_pods}
        if old & new or new == old:
            raise RollbackError(
                "target artifact differed but serving pod replacement was not proven"
            )
        verifier = validate_verifier_result(
            json_run(
                runner,
                [
                    str(args.verifier),
                    "verify",
                    "--application-version",
                    target["applicationVersion"],
                    "--source-revision",
                    target["sourceRevision"],
                    "--provider",
                    target["expectedDefaultChatProvider"],
                ],
            ),
            target,
        )
        stable = helm_identity(
            json_run(
                runner, [args.helm, "status", release_name, "--namespace", namespace, "-o", "json"]
            ),
            release_name,
            namespace,
        )
        if stable != after_helm:
            raise RollbackError("Helm release changed concurrently during evidence collection")
        finished = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        evidence = {
            "schemaVersion": SCHEMA_VERSION,
            "operation": OPERATION,
            "targetManifestFingerprint": fingerprint,
            "environment": args.environment,
            "release": release_name,
            "namespace": namespace,
            "invocationId": invocation,
            "target": {
                key: target[key]
                for key in (
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
            "sugarkubeRevision": runner(["git", "-C", str(args.root), "rev-parse", "HEAD"]).strip(),
            "before": {"helm": before_helm, "pods": before_pods},
            "after": {"helm": after_helm, "pods": after_pods},
            "verification": {
                "oci": oci,
                "clusterEnvironment": args.environment,
                "runtime": verifier,
            },
            "startedAt": started.isoformat().replace("+00:00", "Z"),
            "finishedAt": finished.isoformat().replace("+00:00", "Z"),
        }
        write_new(args.evidence.resolve(strict=False), evidence)
        sidecar.unlink()
        return evidence
    except Exception as exc:
        state = (
            "cluster state may have changed; reservation preserved for reconciliation"
            if mutated
            else "reservation preserved for reconciliation"
        )
        raise RollbackError(f"rollback failed after evidence reservation; {state}: {exc}") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--environment", choices=("staging", "prod"), required=True)
    result.add_argument("--manifest", type=Path, required=True)
    result.add_argument("--evidence", type=Path, required=True)
    result.add_argument("--verifier", type=Path, required=True)
    result.add_argument("--confirm", default="")
    result.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    result.add_argument("--python", default=sys.executable)
    result.add_argument("--just", default="just")
    result.add_argument("--helm", default="helm")
    result.add_argument("--kubectl", default="kubectl")
    result.add_argument("--oras", default="oras")
    result.add_argument("--timeout", default="180s")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not args.verifier.is_file() or not os.access(args.verifier, os.X_OK):
            raise RollbackError("runtime-and-journey verifier is absent or not executable")
        execute(args)
    except RollbackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
