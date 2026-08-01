#!/usr/bin/env python3
"""Restore DSPACE from finalized immutable evidence and prove the result."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

# Support the documented direct-script invocation from any working directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import app_config  # noqa: E402
from scripts import dspace_release_manifest as release  # noqa: E402

SCHEMA_VERSION = 1
OPERATION = "dspaceManifestRollback"
REQUIRED_CAPABILITIES = (
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
)
VERIFIER_FIELDS = (
    "schemaVersion",
    "environment",
    "release",
    "namespace",
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "journeys",
)
POD_TIMEOUT = 60.0
POLL_INTERVAL = 2.0


class RollbackError(ValueError):
    """The rollback cannot safely proceed or could not be proved."""


Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        # Command output is deliberately never reflected: verifier output may contain credentials.
        raise RollbackError(f"command failed: {command[0]}")
    return completed.stdout


def json_command(runner: Runner, command: list[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(runner(command))
    except (json.JSONDecodeError, OSError) as exc:
        raise RollbackError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise RollbackError(f"{label} must return a JSON object")
    return value


def exact_fields(value: dict[str, Any], fields: tuple[str, ...], label: str) -> None:
    missing = sorted(set(fields) - value.keys())
    unknown = sorted(value.keys() - set(fields))
    if missing or unknown:
        raise RollbackError(
            f"{label} schema mismatch (missing={','.join(missing) or '-'}; "
            f"unknown={','.join(unknown) or '-'})"
        )


def verifier_capabilities(
    executable: Path, environment: str, release_name: str, namespace: str, runner: Runner = run
) -> dict[str, Any]:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RollbackError("runtime verifier must be an existing executable file")
    value = json_command(
        runner,
        [
            str(executable),
            "capabilities",
            "--environment",
            environment,
            "--release",
            release_name,
            "--namespace",
            namespace,
        ],
        "runtime verifier",
    )
    exact_fields(
        value,
        ("schemaVersion", "environment", "release", "namespace", "capabilities"),
        "runtime verifier capabilities",
    )
    capabilities = value["capabilities"]
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["environment"] != environment
        or value["release"] != release_name
        or value["namespace"] != namespace
        or capabilities != list(REQUIRED_CAPABILITIES)
    ):
        raise RollbackError("runtime verifier has an incompatible capability contract")
    return value


def verifier_accepts_runtime_arguments(
    executable: Path,
    environment: str,
    manifest: Path,
    smoke_runner: Path | None,
    kubeconfig: str,
    config: str,
    runner: Runner = run,
) -> bool:
    """Negotiate the extended verify argv before any cluster mutation."""
    command = [
        str(executable),
        "capabilities",
        "--environment",
        environment,
        "--release",
        "dspace",
        "--namespace",
        "dspace",
        "--manifest",
        str(manifest),
        "--kubeconfig",
        kubeconfig,
    ]
    if smoke_runner:
        command.extend(("--smoke-runner", str(smoke_runner)))
    if config:
        command.extend(("--config", config))
    try:
        runner(command)
    except (OSError, RollbackError):
        return False
    return True


def validate_verifier_result(
    value: dict[str, Any], target: dict[str, Any], environment: str
) -> dict[str, Any]:
    """Validate reusable runtime/frontend/provider/journey proof from DSPACE tooling."""
    exact_fields(value, VERIFIER_FIELDS, "runtime verifier result")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise RollbackError("runtime verifier result schemaVersion must be 1")
    expected = {
        "environment": environment,
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": target["applicationVersion"],
        "runtimeSourceRevision": target["sourceRevision"],
        "frontendSourceRevision": target["sourceRevision"],
        "defaultProvider": target["expectedDefaultChatProvider"],
    }
    for field, wanted in expected.items():
        if not isinstance(value[field], str) or value[field] != wanted:
            raise RollbackError(f"runtime verifier {field} mismatch")
    journeys = value["journeys"]
    if not isinstance(journeys, list) or not journeys:
        raise RollbackError("runtime verifier must report public journeys")
    names: set[str] = set()
    for journey in journeys:
        if not isinstance(journey, dict):
            raise RollbackError("runtime verifier journeys must be objects")
        exact_fields(journey, ("name", "passed"), "runtime verifier journey")
        if (
            not isinstance(journey["name"], str)
            or not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*", journey["name"])
            or not isinstance(journey["passed"], bool)
            or journey["name"] in names
        ):
            raise RollbackError("runtime verifier journey has invalid fields")
        names.add(journey["name"])
        if not journey["passed"]:
            raise RollbackError("runtime verifier reported a failed public journey")
    if "/chat" not in names:
        raise RollbackError("runtime verifier did not prove the required /chat journey")
    return value


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def portable(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RollbackError("values files must be inside the Sugarkube repository") from exc


def stage_values(
    config: dict[str, str], root: Path, destination: Path
) -> tuple[list[Path], list[dict[str, str]]]:
    paths: list[Path] = []
    evidence: list[dict[str, str]] = []
    for raw in config["SUGARKUBE_VALUES"].split(","):
        path = Path(raw.strip())
        path = path if path.is_absolute() else root / path
        if not path.is_file() or not os.access(path, os.R_OK):
            raise RollbackError(f"values file is missing or unreadable: {raw.strip()}")
        content = path.read_bytes()
        staged = destination / f"{len(paths):02d}.yaml"
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        paths.append(staged)
        evidence.append(
            {
                "path": portable(path, root),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if not paths:
        raise RollbackError("DSPACE values chain is empty")
    return paths, evidence


def values_evidence(config: dict[str, str], root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    """Compatibility helper for callers that only need current values proof."""
    paths: list[Path] = []
    evidence: list[dict[str, str]] = []
    for raw in config["SUGARKUBE_VALUES"].split(","):
        path = Path(raw.strip()).expanduser()
        path = path if path.is_absolute() else root / path
        if not path.is_file() or not os.access(path, os.R_OK):
            raise RollbackError(f"values file is missing or unreadable: {raw.strip()}")
        content = path.read_bytes()
        paths.append(path)
        evidence.append(
            {"path": portable(path, root), "sha256": hashlib.sha256(content).hexdigest()}
        )
    if not paths:
        raise RollbackError("DSPACE values chain is empty")
    return paths, evidence


def helm_status(
    runner: Runner, kubeconfig: str, release_name: str, namespace: str
) -> dict[str, Any]:
    return json_command(
        runner,
        [
            "helm",
            "--kubeconfig",
            kubeconfig,
            "status",
            release_name,
            "--namespace",
            namespace,
            "-o",
            "json",
        ],
        "Helm status",
    )


def cluster_environment(runner: Runner, kubeconfig: str) -> str:
    nodes = json_command(
        runner,
        ["kubectl", "--kubeconfig", kubeconfig, "get", "nodes", "-o", "json"],
        "cluster nodes",
    )
    items = nodes.get("items", [])
    if not isinstance(items, list) or not items:
        raise RollbackError("cluster nodes do not prove one Sugarkube environment")
    labels = {
        item.get("metadata", {}).get("labels", {}).get("sugarkube.env")
        for item in items
        if isinstance(item, dict)
    }
    if len(labels) != 1 or None in labels:
        raise RollbackError("cluster nodes do not prove one Sugarkube environment")
    return labels.pop()


def pods(
    runner: Runner,
    kubeconfig: str,
    namespace: str,
    release_name: str,
    *,
    require_any: bool = True,
) -> list[dict[str, Any]]:
    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={release_name}"
    value = json_command(
        runner,
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "get",
            "pods",
            "--namespace",
            namespace,
            "-l",
            selector,
            "-o",
            "json",
        ],
        "DSPACE pods",
    )
    result = []
    for item in value.get("items", []):
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        declared = {
            c.get("name"): c.get("image")
            for c in item.get("spec", {}).get("containers", [])
            if isinstance(c, dict)
        }
        resolved = {
            c.get("name"): c.get("imageID")
            for c in status.get("containerStatuses", [])
            if isinstance(c, dict)
        }
        result.append(
            {
                "name": metadata.get("name"),
                "uid": metadata.get("uid"),
                "startTime": status.get("startTime"),
                "phase": status.get("phase"),
                "ready": any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", [])
                ),
                "terminating": metadata.get("deletionTimestamp") is not None,
                "images": declared,
                "imageIDs": resolved,
                "applicationImage": declared.get("dspace"),
                "applicationImageID": resolved.get("dspace"),
                "ownerReferences": metadata.get("ownerReferences", []),
            }
        )
    if require_any and not result:
        raise RollbackError("no release-owned DSPACE pods were found")
    return sorted(result, key=lambda item: str(item["name"]))


def chart_version(status: dict[str, Any]) -> str | None:
    value = status.get("chart", {}).get("metadata", {}).get("version")
    return value if isinstance(value, str) else None


def revision(status: dict[str, Any]) -> int:
    value = status.get("version")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RollbackError("Helm status lacks a valid revision")
    return value


def summary(
    current: dict[str, Any],
    current_pods: list[dict[str, Any]],
    target: dict[str, Any],
    values: list[dict[str, str]],
) -> str:
    images = sorted({application_image(pod) for pod in current_pods if application_image(pod)})
    image_ids = sorted(
        {application_image_id(pod) for pod in current_pods if application_image_id(pod)}
    )
    info = current.get("info", {})
    lines = [
        "DSPACE manifest rollback preflight:",
        (
            "  current: release=dspace namespace=dspace "
            f"helmStatus={info.get('status') or 'unknown'} "
            f"helmRevision={revision(current)} chartName="
            f"{current.get('chart', {}).get('metadata', {}).get('name') or 'unknown'} "
            f"chartVersion={chart_version(current) or 'unknown'} chartDigest=unknown"
        ),
        (
            f"           images={','.join(images) or 'unknown'} "
            f"imageIDs={','.join(image_ids) or 'unknown'}"
        ),
        (
            f"  target:  release=dspace namespace=dspace sourceRevision={target['sourceRevision']} "
            f"applicationVersion={target['applicationVersion']}"
        ),
        f"           chartVersion={target['chartVersion']} chartDigest={target['chartDigest']}",
        f"           imageTag={target['imageTag']} imageDigest={target['imageDigest']}",
        (
            f"           imageCoordinate={release.IMAGE_REF}:"
            f"{target['imageTag']}@{target['imageDigest']}"
        ),
        f"           provider={target['expectedDefaultChatProvider']}",
        "  values:  " + ",".join(f"{item['path']}={item['sha256']}" for item in values),
    ]
    return "\n".join(lines)


def confirmation(environment: str, supplied: str, target: dict[str, Any]) -> None:
    expected = f"dspace:prod:{target['sourceRevision']}"
    if environment == "prod" and supplied != expected:
        raise RollbackError(f"production confirmation must exactly equal {expected}")


def reserve(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RollbackError(f"refusing to overwrite rollback evidence: {path}")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RollbackError(f"rollback evidence destination is already reserved: {path}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(release._canonical(metadata))
        stream.flush()
        os.fsync(stream.fileno())
    release._sync_directory(path.parent)


def replace_reserved(path: Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(release._canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    release._sync_directory(path.parent)


def verify_post_pods(
    after: list[dict[str, Any]], before: list[dict[str, Any]], target: dict[str, Any], changed: bool
) -> None:
    if any(p["terminating"] for p in after):
        raise RollbackError("terminating old DSPACE pods remain")
    if any(p["phase"] != "Running" or not p["ready"] for p in after):
        raise RollbackError("all DSPACE pods must be Running and Ready")
    old = {(p["uid"], p["startTime"]) for p in before}
    new = {(p["uid"], p["startTime"]) for p in after}
    if changed and (old & new or old == new):
        raise RollbackError("DSPACE pod replacement was not proved")
    expected_image = f"{release.IMAGE_REF}:{target['imageTag']}@{target['imageDigest']}"
    for pod in after:
        if application_image(pod) != expected_image:
            raise RollbackError("DSPACE container image coordinate does not match target")
        try:
            resolved = release._image_id_digest(application_image_id(pod) or "")
        except release.ManifestError as exc:
            raise RollbackError("DSPACE resolved image ID is invalid") from exc
        if resolved != target["imageDigest"]:
            raise RollbackError("DSPACE resolved image ID does not match target digest")


def application_image(pod: dict[str, Any]) -> str | None:
    return pod.get("applicationImage", pod.get("images", {}).get("dspace"))


def application_image_id(pod: dict[str, Any]) -> str | None:
    return pod.get("applicationImageID", pod.get("imageIDs", {}).get("dspace"))


def rollback(args: argparse.Namespace, runner: Runner = run) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dspace-rollback-values-") as temporary:
        os.chmod(temporary, 0o700)
        return _rollback(args, runner, Path(temporary))


def _rollback(args: argparse.Namespace, runner: Runner, staged_directory: Path) -> dict[str, Any]:
    started = timestamp()
    args.manifest = args.manifest.expanduser()
    args.evidence = args.evidence.expanduser()
    args.verifier = args.verifier.expanduser()
    try:
        target = release.validate(release._object(args.manifest), True)
    except release.ManifestError as exc:
        raise RollbackError(f"target must be finalized DSPACE release evidence: {exc}") from exc
    if target["environment"] != args.environment:
        raise RollbackError("target manifest environment does not match selected environment")
    # The manifest module's OCI and cluster proof functions deliberately accept
    # candidate records. Project the exact candidate portion of the validated
    # final record rather than reimplementing or weakening those validators.
    approved = {field: target[field] for field in release.candidate_fields(target)}
    approved["recordType"] = "candidate"
    release.validate(approved, False)
    root = REPO_ROOT
    config = app_config.load_config("dspace", args.environment, args.config or None)
    if config["SUGARKUBE_CHART"] != f"oci://{release.CHART_REF}":
        raise RollbackError("DSPACE config chart repository is not canonical")
    if config["SUGARKUBE_RELEASE"] != "dspace" or config["SUGARKUBE_NAMESPACE"] != "dspace":
        raise RollbackError("DSPACE release and namespace must both be dspace")
    values, values_proof = stage_values(config, root, staged_directory)
    environment = cluster_environment(runner, args.kubeconfig)
    if environment != args.environment:
        raise RollbackError("connected cluster environment does not match selected environment")
    bundled_verifier = (
        args.verifier.resolve() == (REPO_ROOT / "scripts/dspace_runtime_verifier.py").resolve()
    )
    if bundled_verifier:
        configured_smoke = getattr(args, "smoke_runner", None) or os.environ.get(
            "DSPACE_SMOKE_RUNNER", ""
        )
        smoke_path = Path(configured_smoke).expanduser() if configured_smoke else None
        if smoke_path is None or not smoke_path.is_file() or not os.access(smoke_path, os.X_OK):
            raise RollbackError("smoke runner must be an existing executable file")
    capabilities = verifier_capabilities(
        args.verifier, args.environment, "dspace", "dspace", runner
    )
    extended_verifier = verifier_accepts_runtime_arguments(
        args.verifier,
        args.environment,
        args.manifest,
        getattr(args, "smoke_runner", None),
        args.kubeconfig,
        args.config,
        runner,
    )
    if bundled_verifier and not extended_verifier:
        raise RollbackError("repository runtime verifier rejected its required arguments")
    coordinate = release.chart_coordinate(approved)
    helm_values = [part for path in values for part in ("--values", str(path))]
    rendered_target = runner(
        [
            "helm",
            "--kubeconfig",
            args.kubeconfig,
            "template",
            "dspace",
            coordinate,
            "--namespace",
            "dspace",
            *helm_values,
            "--set-string",
            f"image.repository={release.IMAGE_REF}",
            "--set-string",
            f"image.tag={target['imageTag']}@{target['imageDigest']}",
        ]
    )
    before_helm = helm_status(runner, args.kubeconfig, "dspace", "dspace")
    before_pods = pods(runner, args.kubeconfig, "dspace", "dspace", require_any=False)
    # Keep the registry proof fresh: no tag resolution occurs between this
    # exact-digest check and confirmation/reservation/mutation.
    try:
        oci = release.preflight(
            approved,
            release.IMAGE_REF,
            release.CHART_REF,
            args.oras,
            environment=args.environment,
            image_tag=target["imageTag"],
            chart_version=target["chartVersion"],
            runner=runner,
        )
    except release.ManifestError as exc:
        raise RollbackError("OCI preflight validation failed") from exc
    print(summary(before_helm, before_pods, target, values_proof))
    current_images = {application_image(pod) for pod in before_pods if application_image(pod)}
    current_ids: set[str] = set()
    for pod in before_pods:
        image_id = application_image_id(pod)
        if not image_id:
            continue
        try:
            current_ids.add(release._image_id_digest(image_id))
        except release.ManifestError:
            # Old state is context, not a safety assertion. Preserve malformed
            # identities in pod evidence and recover rather than crashing.
            current_ids.clear()
            break
    try:
        installed_render = runner(
            [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "get",
                "manifest",
                "dspace",
                "--namespace",
                "dspace",
            ]
        )
    except RollbackError:
        installed_render = None
    expected_image = f"{release.IMAGE_REF}:{target['imageTag']}@{target['imageDigest']}"
    if (
        installed_render is not None
        and installed_render == rendered_target
        and current_images == {expected_image}
        and current_ids == {target["imageDigest"]}
    ):
        raise RollbackError("current rendered release is already the exact approved target")
    # Matching chart version and image identity alone is not exact proof: Helm
    # status cannot establish the installed OCI chart digest.
    confirmation(args.environment, args.confirm, target)
    sugarkube_revision = runner(["git", "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sugarkube_revision):
        raise RollbackError("could not capture the Sugarkube revision")
    if revision(helm_status(runner, args.kubeconfig, "dspace", "dspace")) != revision(before_helm):
        raise RollbackError("Helm revision changed during preflight")

    invocation = uuid.uuid4().hex
    target_fingerprint = hashlib.sha256(release._canonical(target).encode()).hexdigest()
    evidence: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "operation": OPERATION,
        "state": "reserved",
        "invocationId": invocation,
        "targetManifestFingerprint": target_fingerprint,
        "environment": args.environment,
        "release": "dspace",
        "namespace": "dspace",
        "startedAt": started,
        "sugarkubeRevision": sugarkube_revision,
        "target": {
            key: target[key]
            for key in (
                "chartVersion",
                "chartDigest",
                "imageTag",
                "imageDigest",
                "sourceRevision",
                "chartSourceRevision",
                "applicationVersion",
                "expectedDefaultChatProvider",
            )
            if key in target
        },
        "values": values_proof,
        "before": {
            "helmRevision": revision(before_helm),
            "helmStatus": before_helm.get("info", {}).get("status"),
            "chartVersion": chart_version(before_helm),
            "pods": before_pods,
        },
        "ociPreflight": oci,
    }
    reserve(args.evidence, evidence)
    mutated = False
    failed_stage = "pre-mutation-revalidation"
    description = f"sugarkube-dspace-manifest-rollback:{invocation}"
    try:
        if runner(["git", "rev-parse", "HEAD"]).strip() != sugarkube_revision:
            raise RollbackError("Sugarkube revision changed before mutation")
        command = [
            "helm",
            "--kubeconfig",
            args.kubeconfig,
            "upgrade",
            "dspace",
            coordinate,
            "--namespace",
            "dspace",
            "--description",
            description,
            *helm_values,
            "--set-string",
            f"image.repository={release.IMAGE_REF}",
            "--set-string",
            f"image.tag={target['imageTag']}@{target['imageDigest']}",
            "--wait",
            "--timeout",
            args.timeout,
        ]
        failed_stage = "helm-upgrade"
        # From this point onward Helm may have accepted or partially applied the
        # request even when the command reports failure.
        mutated = True
        runner(command)
        failed_stage = "rollout-wait"
        runner(
            [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "rollout",
                "status",
                "deployment/dspace",
                "--namespace",
                "dspace",
                "--timeout",
                args.timeout,
            ]
        )
        failed_stage = "pod-settling-and-proof"
        deadline = time.monotonic() + POD_TIMEOUT
        while True:
            after_pods = pods(runner, args.kubeconfig, "dspace", "dspace")
            if not any(p["terminating"] for p in after_pods):
                break
            if time.monotonic() >= deadline:
                raise RollbackError("timed out waiting for old terminating pods to disappear")
            time.sleep(POLL_INTERVAL)
        after_helm = helm_status(runner, args.kubeconfig, "dspace", "dspace")
        after_revision = revision(after_helm)
        if (
            after_helm.get("name") != "dspace"
            or after_helm.get("namespace") != "dspace"
            or after_helm.get("info", {}).get("status") != "deployed"
        ):
            raise RollbackError("Helm did not report the expected deployed release")
        if after_helm.get("info", {}).get("description") != description:
            raise RollbackError("Helm release description is not bound to this invocation")
        if after_revision <= revision(before_helm):
            raise RollbackError("Helm revision did not advance")
        if (
            after_helm.get("chart", {}).get("metadata", {}).get("name") != "dspace"
            or chart_version(after_helm) != target["chartVersion"]
        ):
            raise RollbackError("installed chart name/version does not match target")
        changed = (
            chart_version(before_helm) != target["chartVersion"]
            or current_ids != {target["imageDigest"]}
            or current_images
            != {f"{release.IMAGE_REF}:{target['imageTag']}@{target['imageDigest']}"}
        )
        verify_post_pods(after_pods, before_pods, target, changed)
        # Reuse finalization's strict Deployment/ReplicaSet ownership validator.
        failed_stage = "ownership-and-finalization-proof"
        workloads = json_command(
            runner,
            [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "get",
                "replicasets,deployments",
                "--namespace",
                "dspace",
                "-l",
                "app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace",
                "-o",
                "json",
            ],
            "DSPACE workloads",
        )
        raw_pods = json_command(
            runner,
            [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "get",
                "pods",
                "--namespace",
                "dspace",
                "-l",
                "app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace",
                "-o",
                "json",
            ],
            "DSPACE pods",
        )
        finalizer_proof = release.finalize(
            approved,
            after_helm,
            raw_pods,
            workloads,
            oci,
            environment=args.environment,
            image_tag=target["imageTag"],
            chart_version=target["chartVersion"],
            release="dspace",
            namespace="dspace",
            cluster_environment=args.environment,
            invocation_description=description,
            expected_image_coordinate=(
                f"{release.IMAGE_REF}:{target['imageTag']}@{target['imageDigest']}"
            ),
        )
        verifier_command = [
            str(args.verifier),
            "verify",
            "--environment",
            args.environment,
            "--release",
            "dspace",
            "--namespace",
            "dspace",
            "--application-version",
            target["applicationVersion"],
            "--source-revision",
            target["sourceRevision"],
            "--provider",
            target["expectedDefaultChatProvider"],
        ]
        # The repository verifier owns these extended arguments.  Preserve the
        # original verify contract for compatible third-party verifiers rather
        # than discovering that they reject new flags after Helm has mutated.
        if extended_verifier:
            verifier_command.extend(("--manifest", str(args.manifest)))
            smoke_runner = getattr(args, "smoke_runner", None)
            if smoke_runner:
                verifier_command.extend(("--smoke-runner", str(smoke_runner)))
            verifier_command.extend(("--kubeconfig", str(args.kubeconfig)))
            if args.config:
                verifier_command.extend(("--config", str(args.config)))
        failed_stage = "runtime-verification"
        verifier = validate_verifier_result(
            json_command(runner, verifier_command, "runtime verifier"), target, args.environment
        )
        failed_stage = "revision-stability-collection"
        stable = helm_status(runner, args.kubeconfig, "dspace", "dspace")
        if revision(stable) != after_revision:
            raise RollbackError("Helm revision changed concurrently during evidence collection")
        result = {
            **evidence,
            "state": "succeeded",
            "completedAt": timestamp(),
            "sugarkubeRevision": sugarkube_revision,
            "helm": {
                "beforeRevision": revision(before_helm),
                "afterRevision": after_revision,
                "status": "deployed",
                "chartName": "dspace",
                "chartVersion": chart_version(after_helm),
            },
            "pods": {"before": before_pods, "after": after_pods},
            "verification": {
                "oci": oci,
                "clusterEnvironment": environment,
                "verifierCapabilities": capabilities,
                "finalizerChecks": finalizer_proof.get("verificationResults", []),
                "runtime": {
                    "applicationVersion": verifier["applicationVersion"],
                    "sourceRevision": verifier["runtimeSourceRevision"],
                },
                "frontend": {"sourceRevision": verifier["frontendSourceRevision"]},
                "provider": {"default": verifier["defaultProvider"]},
                "journeys": verifier["journeys"],
            },
        }
        replace_reserved(args.evidence, result)
        return result
    except Exception as exc:
        diagnostics: dict[str, Any] = {}
        try:
            observed_helm = helm_status(runner, args.kubeconfig, "dspace", "dspace")
            observed_info = observed_helm.get("info", {})
            observed_chart = observed_helm.get("chart", {}).get("metadata", {})
            diagnostics["helm"] = {
                "release": observed_helm.get("name"),
                "namespace": observed_helm.get("namespace"),
                "revision": revision(observed_helm),
                "status": observed_info.get("status"),
                "chartName": observed_chart.get("name"),
                "chartVersion": chart_version(observed_helm),
                "invocationDescriptionMatches": observed_info.get("description") == description,
            }
        except Exception:
            diagnostics["helm"] = "unavailable"
        try:
            diagnostics["pods"] = pods(
                runner, args.kubeconfig, "dspace", "dspace", require_any=False
            )
        except Exception:
            diagnostics["pods"] = "unavailable"
        evidence.update(
            state="failed",
            failedStage=failed_stage,
            failureCode=f"{failed_stage}-failed",
            failureType=("rollback" if isinstance(exc, RollbackError) else "dependency"),
            failedAt=timestamp(),
            clusterMayHaveChanged=mutated,
            diagnostics=diagnostics,
        )
        replace_reserved(args.evidence, evidence)
        raise RollbackError(
            "rollback failed; cluster state may have changed; reconcile with "
            f"preserved evidence {args.evidence}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--smoke-runner", type=Path)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--kubeconfig", default=str(Path.home() / ".kube" / "config-sugarkube"))
    parser.add_argument("--oras", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras"))
    parser.add_argument("--timeout", default="10m")
    args = parser.parse_args(argv)
    try:
        rollback(args)
    except (RollbackError, app_config.AppConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
