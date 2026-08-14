#!/usr/bin/env python3
"""Restore DSPACE from finalized immutable evidence and prove the result."""

from __future__ import annotations

import argparse
import copy
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
from scripts import app_chart  # noqa: E402
from scripts import dspace_release_manifest as release  # noqa: E402

SCHEMA_VERSION = 1
OPERATION = "dspaceManifestRollback"
RECOVERY_OPERATION = "dspaceProductionMetricsPullPolicyRecovery"
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
MAINTENANCE_TARGET_FIELDS = (
    "schemaVersion",
    "app",
    "applicationVersion",
    "sourceRevision",
    "imageTag",
    "imageDigest",
    "semanticTag",
    "chartSourceRevision",
    "chartVersion",
    "chartDigest",
)
PRODUCTION_BASELINE = (
    REPO_ROOT / "deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json"
)
RECOVERY_OPERATION = "dspaceProductionMetricsPullPolicyRecovery"
RECOVERY_CONFIRMATION = "dspace:prod:recover-revision-10-pull-policy"
FAILED_RECONCILIATION_FIELDS = (
    "schemaVersion",
    "operation",
    "state",
    "failedStage",
    "failureCode",
    "clusterMayHaveChanged",
    "invocationId",
    "targetManifestFingerprint",
    "sugarkubeRevision",
    "environment",
    "release",
    "namespace",
    "before",
    "target",
)
RECORDED_TARGET_FIELDS = (
    "chartVersion",
    "chartDigest",
    "imageTag",
    "imageDigest",
    "sourceRevision",
    "chartSourceRevision",
    "applicationVersion",
    "expectedDefaultChatProvider",
)


class RollbackError(ValueError):
    """The rollback cannot safely proceed or could not be proved."""


Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        # Command output is deliberately never reflected: verifier output may contain credentials.
        raise RollbackError(f"command failed: {command[0]}")
    return completed.stdout


def chart_pin(path: Path) -> str:
    """Read a chart pin with the shared parser and redact filesystem failures."""
    try:
        return app_chart.read_pin(str(path))
    except (OSError, SystemExit, ValueError) as exc:
        raise RollbackError("configured production chart pin is unreadable or invalid") from exc


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


def helm_history(runner: Runner, kubeconfig: str, release_name: str, namespace: str) -> object:
    try:
        return json.loads(
            runner(
                [
                    "helm",
                    "--kubeconfig",
                    kubeconfig,
                    "history",
                    release_name,
                    "--namespace",
                    namespace,
                    "-o",
                    "json",
                ]
            )
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise RollbackError("Helm history did not return valid JSON") from exc


def helm_snapshot(
    runner: Runner,
    kubeconfig: str,
    release_name: str,
    namespace: str,
    *,
    require_deployed: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None, tuple[str, str, int]]:
    """Read a redaction-safe, revision-bound Helm release identity."""
    status = helm_status(runner, kubeconfig, release_name, namespace)
    history: list[dict[str, Any]] | None = None
    try:
        needs_history = release.helm_status_needs_history(status)
        if needs_history:
            history_payload = helm_history(runner, kubeconfig, release_name, namespace)
            revision_value = status["version"]
            if not isinstance(history_payload, list) or not all(
                isinstance(item, dict) for item in history_payload
            ):
                raise release.ManifestError("invalid Helm release identity")
            history = history_payload
            matches = [
                item
                for item in history
                if isinstance(item, dict) and item.get("revision") == revision_value
            ]
            if len(matches) != 1:
                raise release.ManifestError("invalid Helm release identity")
            coordinate = matches[0].get("chart")
            prefix = f"{release_name}-"
            if not isinstance(coordinate, str) or not coordinate.startswith(prefix):
                raise release.ManifestError("invalid Helm release identity")
            expected_version = coordinate[len(prefix) :]
        else:
            chart = status.get("chart")
            metadata = chart.get("metadata") if isinstance(chart, dict) else None
            if not isinstance(metadata, dict):
                raise release.ManifestError("invalid Helm release identity")
            expected_version = metadata.get("version")
        if not isinstance(expected_version, str) or not release.SEMVER_RE.fullmatch(
            expected_version
        ):
            raise release.ManifestError("invalid Helm release identity")
        identity = release.resolve_helm_identity(status, history, release_name, expected_version)
    except release.ManifestError as exc:
        raise RollbackError("Helm release identity is invalid") from exc
    if status.get("name") != release_name or status.get("namespace") != namespace:
        raise RollbackError("Helm release identity is invalid")
    info = status.get("info")
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("status"), str)
        or (require_deployed and info["status"] != "deployed")
    ):
        raise RollbackError("Helm release identity is invalid")
    return status, history, identity


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


def revision(status: dict[str, Any]) -> int:
    value = status.get("version")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RollbackError("Helm status lacks a valid revision")
    return value


def summary(
    current: dict[str, Any],
    current_identity: tuple[str, str, int],
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
            f"helmRevision={current_identity[2]} chartName={current_identity[0]} "
            f"chartVersion={current_identity[1]} chartDigest=unknown"
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


def recovery_confirmation(supplied: str) -> None:
    if supplied != RECOVERY_CONFIRMATION:
        raise RollbackError(f"recovery confirmation must exactly equal {RECOVERY_CONFIRMATION}")


def runtime_verifier_command(
    args: argparse.Namespace,
    target: dict[str, Any],
    manifest: Path,
    *,
    expected_revision: int | None = None,
) -> list[str]:
    """Build the repository verifier invocation used on both sides of mutation."""
    command = [
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
        "--manifest",
        str(manifest),
        "--smoke-runner",
        str(args.smoke_runner),
        "--kubeconfig",
        str(args.kubeconfig),
    ]
    if args.config:
        command.extend(("--config", str(args.config)))
    if expected_revision is not None:
        command.extend(("--expected-helm-revision", str(expected_revision)))
    return command


def failed_reconciliation(
    path: Path, target: dict[str, Any], runner: Runner
) -> tuple[dict[str, Any], str]:
    """Validate the immutable failure that alone authorizes the revision-10 repair."""
    try:
        raw = path.expanduser().read_bytes()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise json.JSONDecodeError("evidence is not an object", "", 0)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RollbackError("preserved failed reconciliation evidence is unreadable") from exc
    # Failure records may also contain the normal immutable lifecycle metadata,
    # but every incident-authorizing field is mandatory.  In particular, do not
    # use ``get``-based projections which silently ignore missing target fields.
    missing = sorted(set(FAILED_RECONCILIATION_FIELDS) - value.keys())
    if missing:
        raise RollbackError("preserved failed reconciliation evidence schema is incomplete")
    if (
        value.get("schemaVersion") != SCHEMA_VERSION
        or value.get("environment") != "prod"
        or value.get("release") != "dspace"
        or value.get("namespace") != "dspace"
        or value.get("operation") != "dspaceProductionMetricsReconciliation"
        or value.get("state") != "failed"
        or value.get("failedStage") != "ownership-and-finalization-proof"
        or value.get("failureCode") != "ownership-and-finalization-proof-failed"
        or value.get("clusterMayHaveChanged") is not True
    ):
        raise RollbackError("preserved evidence is not the authorized failed reconciliation")
    invocation = value.get("invocationId")
    fingerprint = value.get("targetManifestFingerprint")
    revision = value.get("sugarkubeRevision")
    if not isinstance(invocation, str) or not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise RollbackError("failed reconciliation invocation binding is invalid")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise RollbackError("failed reconciliation target binding is invalid")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RollbackError("failed reconciliation Sugarkube revision is invalid")
    try:
        runner(["git", "merge-base", "--is-ancestor", revision, "HEAD"])
    except RollbackError as exc:
        raise RollbackError(
            "failed reconciliation Sugarkube revision is not an ancestor of HEAD"
        ) from exc
    expected_fingerprint = hashlib.sha256(release._canonical(target).encode()).hexdigest()
    if fingerprint != expected_fingerprint:
        raise RollbackError("failed reconciliation is not bound to the reviewed target")
    before = value.get("before")
    if not isinstance(before, dict) or (
        before.get("helmRevision"),
        before.get("chartName"),
        before.get("chartVersion"),
    ) != (9, "dspace", "3.0.2"):
        raise RollbackError("failed reconciliation before state is not revision 9/chart 3.0.2")
    recorded_target = value.get("target")
    expected_target = {field: target[field] for field in RECORDED_TARGET_FIELDS}
    if recorded_target != expected_target:
        raise RollbackError("failed reconciliation target differs from the reviewed target")
    return value, hashlib.sha256(raw).hexdigest()


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
    after: list[dict[str, Any]],
    before: list[dict[str, Any]],
    target: dict[str, Any],
    changed: bool,
    *,
    retain_tag: bool = False,
) -> None:
    if any(p["terminating"] for p in after):
        raise RollbackError("terminating old DSPACE pods remain")
    if any(p["phase"] != "Running" or not p["ready"] for p in after):
        raise RollbackError("all DSPACE pods must be Running and Ready")
    old = {(p["uid"], p["startTime"]) for p in before}
    new = {(p["uid"], p["startTime"]) for p in after}
    if changed and (old & new or old == new):
        raise RollbackError("DSPACE pod replacement was not proved")
    expected_image = f"{release.IMAGE_REF}:{target['imageTag']}"
    if not retain_tag:
        expected_image += f"@{target['imageDigest']}"
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


def assert_production_target(kubeconfig: str, runner: Runner) -> None:
    context = runner(["kubectl", "--kubeconfig", kubeconfig, "config", "current-context"]).strip()
    if context != "sugar-prod":
        raise RollbackError("metrics configuration reconciliation requires sugar-prod")
    runner(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "cluster_identity.py"),
            "assert",
            "--kubeconfig",
            kubeconfig,
            "--env",
            "prod",
        ]
    )


def configuration_comparison_baselines(
    live_values: dict[str, Any], desired_values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build strict baselines, canonicalizing only an omitted live image repository."""
    baseline = copy.deepcopy(live_values)
    baseline.pop("metrics", None)
    baseline.pop("serviceMonitor", None)
    desired_baseline = copy.deepcopy(desired_values)
    desired_baseline.pop("metrics", None)
    desired_baseline.pop("serviceMonitor", None)

    live_image = baseline.get("image")
    desired_image = desired_baseline.get("image")
    if not isinstance(live_image, dict) or not isinstance(desired_image, dict):
        raise RollbackError("unrelated Helm values drift blocks configuration reconciliation")
    desired_repository = desired_image.get("repository")
    if not isinstance(desired_repository, str) or desired_repository != release.IMAGE_REF:
        raise RollbackError("unrelated Helm values drift blocks configuration reconciliation")
    if "repository" not in live_image:
        live_image["repository"] = release.IMAGE_REF
    return baseline, desired_baseline


def validate_workload_pull_policy(
    workloads: dict[str, Any], expected: str, raw_pods: dict[str, Any] | None = None
) -> None:
    deployments = [
        item
        for item in workloads.get("items", [])
        if isinstance(item, dict) and item.get("kind") == "Deployment"
    ]
    if len(deployments) != 1:
        raise RollbackError("expected exactly one DSPACE Deployment")
    if deployments[0].get("spec", {}).get("replicas") != 2:
        raise RollbackError("DSPACE Deployment must have exactly two replicas")
    containers = (
        deployments[0].get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    )
    policies = [item.get("imagePullPolicy") for item in containers if item.get("name") == "dspace"]
    if policies != [expected]:
        raise RollbackError(f"Deployment and pod-template pull policy must be exactly {expected}")
    if raw_pods is None:
        return
    pod_items = raw_pods.get("items")
    if not isinstance(pod_items, list) or len(pod_items) != 2:
        raise RollbackError("expected exactly two DSPACE pods")
    for pod in pod_items:
        if not isinstance(pod, dict):
            raise RollbackError("DSPACE pod discovery returned an unexpected object")
        status = pod.get("status", {})
        ready = any(
            item.get("type") == "Ready" and item.get("status") == "True"
            for item in status.get("conditions", [])
            if isinstance(item, dict)
        )
        containers = pod.get("spec", {}).get("containers", [])
        policies = [
            item.get("imagePullPolicy")
            for item in containers
            if isinstance(item, dict) and item.get("name") == "dspace"
        ]
        if status.get("phase") != "Running" or not ready or policies != [expected]:
            raise RollbackError(f"exactly two Ready DSPACE pods must use {expected}")


def raw_release_objects(
    runner: Runner, kubeconfig: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    selector = "app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace"
    common = ["--namespace", "dspace", "-l", selector, "-o", "json"]
    workloads = json_command(
        runner,
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "get",
            "replicasets,deployments",
            *common,
        ],
        "DSPACE workloads",
    )
    raw_pods = json_command(
        runner,
        ["kubectl", "--kubeconfig", kubeconfig, "get", "pods", *common],
        "DSPACE pods",
    )
    return workloads, raw_pods


def deployment_contract(value: dict[str, Any]) -> dict[str, Any]:
    """Select the full operator-controlled Deployment contract."""
    spec = value.get("spec", {})
    template = spec.get("template", {})
    pod_spec = template.get("spec", {})
    deployment_fields = (
        "replicas",
        "selector",
        "strategy",
        "minReadySeconds",
        "revisionHistoryLimit",
        "progressDeadlineSeconds",
        "paused",
    )
    pod_fields = (
        "containers",
        "initContainers",
        "ephemeralContainers",
        "volumes",
        "serviceAccountName",
        "automountServiceAccountToken",
        "securityContext",
        "nodeSelector",
        "affinity",
        "tolerations",
        "topologySpreadConstraints",
        "schedulerName",
        "priorityClassName",
        "priority",
        "runtimeClassName",
        "dnsPolicy",
        "dnsConfig",
        "hostAliases",
        "hostNetwork",
        "hostPID",
        "hostIPC",
        "shareProcessNamespace",
        "terminationGracePeriodSeconds",
        "imagePullSecrets",
        "restartPolicy",
        "enableServiceLinks",
        "preemptionPolicy",
        "readinessGates",
        "overhead",
        "setHostnameAsFQDN",
        "hostname",
        "subdomain",
        "os",
        "resourceClaims",
    )
    # Validation normalizes proven live-only metadata on this projection. Keep
    # the raw objects intact because release.finalize consumes them afterward.
    contract = {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": {
            "name": value.get("metadata", {}).get("name"),
            "namespace": value.get("metadata", {}).get("namespace"),
            "labels": value.get("metadata", {}).get("labels", {}),
            "annotations": value.get("metadata", {}).get("annotations", {}),
        },
        "spec": {key: spec[key] for key in deployment_fields if key in spec},
        "templateMetadata": {
            key: template.get("metadata", {}).get(key, {}) for key in ("labels", "annotations")
        },
        "podSpec": {key: pod_spec[key] for key in pod_fields if key in pod_spec},
    }
    return copy.deepcopy(contract)


_KUBERNETES_DEPLOYMENT_DEFAULTS: dict[tuple[str, ...], Any] = {
    ("spec", "strategy", "type"): "RollingUpdate",
    ("spec", "strategy", "rollingUpdate", "maxUnavailable"): "25%",
    ("spec", "strategy", "rollingUpdate", "maxSurge"): "25%",
    ("spec", "revisionHistoryLimit"): 10,
    ("spec", "progressDeadlineSeconds"): 600,
    ("podSpec", "dnsPolicy"): "ClusterFirst",
    ("podSpec", "restartPolicy"): "Always",
    ("podSpec", "schedulerName"): "default-scheduler",
    ("podSpec", "securityContext"): {},
    ("podSpec", "terminationGracePeriodSeconds"): 30,
    ("podSpec", "enableServiceLinks"): True,
    ("podSpec", "preemptionPolicy"): "PreemptLowerPriority",
    ("podSpec", "serviceAccountName"): "default",
    ("podSpec", "containers", "*", "terminationMessagePath"): "/dev/termination-log",
    ("podSpec", "containers", "*", "terminationMessagePolicy"): "File",
    ("podSpec", "initContainers", "*", "terminationMessagePath"): "/dev/termination-log",
    ("podSpec", "initContainers", "*", "terminationMessagePolicy"): "File",
}


def _is_defaulted_subtree(live: Any, path: tuple[str, ...]) -> bool:
    if path in _KUBERNETES_DEPLOYMENT_DEFAULTS:
        return _KUBERNETES_DEPLOYMENT_DEFAULTS[path] == live
    if isinstance(live, dict):
        return bool(live) and all(
            _is_defaulted_subtree(value, (*path, key)) for key, value in live.items()
        )
    return False


def _rendered_contract_matches(rendered: Any, live: Any, path: tuple[str, ...] = ()) -> bool:
    """Compare a render with live state, accepting only explicit API defaults."""
    if isinstance(rendered, dict):
        if not isinstance(live, dict):
            return False
        for key, rendered_value in rendered.items():
            if key not in live or not _rendered_contract_matches(
                rendered_value, live[key], (*path, key)
            ):
                return False
        for key in live.keys() - rendered.keys():
            if not _is_defaulted_subtree(live[key], (*path, key)):
                return False
        return True
    if isinstance(rendered, list):
        return isinstance(live, list) and len(rendered) == len(live) and all(
            _rendered_contract_matches(rendered_item, live_item, (*path, "*"))
            for rendered_item, live_item in zip(rendered, live, strict=True)
        )
    return rendered == live


def validate_rendered_deployment(rendered: str, workloads: dict[str, Any]) -> None:
    rendered_deployments = [
        item
        for item in app_chart.safe_yaml_documents(rendered)
        if isinstance(item, dict) and item.get("kind") == "Deployment"
    ]
    live_deployments = [
        item
        for item in workloads.get("items", [])
        if isinstance(item, dict) and item.get("kind") == "Deployment"
    ]
    if len(rendered_deployments) != 1 or len(live_deployments) != 1:
        raise RollbackError("expected exactly one rendered and live DSPACE Deployment")
    rendered_contract = deployment_contract(rendered_deployments[0])
    live_contract = deployment_contract(live_deployments[0])

    # Helm templates commonly omit the namespace, while the API always returns it.
    # Normalize only the namespace of this fixed production release.
    if rendered_contract["metadata"]["namespace"] is None:
        rendered_contract["metadata"]["namespace"] = "dspace"
    if live_contract["metadata"]["namespace"] != "dspace":
        raise RollbackError("live Deployment contract differs from rendered target")

    rendered_annotations = rendered_contract["metadata"]["annotations"]
    live_annotations = live_contract["metadata"]["annotations"]
    if not isinstance(rendered_annotations, dict) or not isinstance(live_annotations, dict):
        raise RollbackError("live Deployment contract differs from rendered target")
    live_only_annotations = {
        "meta.helm.sh/release-name": "dspace",
        "meta.helm.sh/release-namespace": "dspace",
    }
    for key, expected in live_only_annotations.items():
        if live_annotations.get(key) != expected:
            raise RollbackError("live Deployment contract differs from rendered target")
        if key not in rendered_annotations:
            live_annotations.pop(key)
    revision_key = "deployment.kubernetes.io/revision"
    revision = live_annotations.get(revision_key)
    if not isinstance(revision, str) or re.fullmatch(r"[1-9][0-9]*", revision) is None:
        raise RollbackError("live Deployment contract differs from rendered target")
    if revision_key not in rendered_annotations:
        live_annotations.pop(revision_key)
    if not _rendered_contract_matches(
        rendered_contract, live_contract
    ):
        raise RollbackError("live Deployment contract differs from rendered target")


def chart_maintenance_target(baseline: dict[str, Any], path: Path) -> dict[str, Any]:
    """Apply a strict reviewed chart tuple without rewriting finalized evidence."""
    if (
        baseline.get("environment") != "prod"
        or baseline.get("expectedDefaultChatProvider") != "openai"
        or (
            baseline.get("chartSourceRevision"),
            baseline.get("chartVersion"),
            baseline.get("chartDigest"),
        )
        != (
            "63063e287adb92a4158ce2c8e7d378b73f52c1c5",
            "3.0.2",
            "sha256:8b862135e52146f301a41259d6dabb053ed891d798fc1c8c95ca775b2b8e9575",
        )
    ):
        raise RollbackError("baseline is not the approved finalized production chart tuple")
    try:
        reviewed = release._object(path.expanduser())
    except release.ManifestError as exc:
        raise RollbackError(f"chart maintenance target is invalid: {exc}") from exc
    exact_fields(reviewed, MAINTENANCE_TARGET_FIELDS, "chart maintenance target")
    if reviewed.get("schemaVersion") != 2 or reviewed.get("app") != "dspace":
        raise RollbackError("chart maintenance target must be schema 2 for dspace")
    approved_application = {
        "app": "dspace",
        "applicationVersion": "3.0.1",
        "sourceRevision": "1a31a569aff2dbeb238e8c2688b9e85140d2077d",
        "imageTag": "main-1a31a56",
        "imageDigest": "sha256:23dbc573377549136c1f10b05706b3c176ffbabaf04a3194381a24752104a401",
        "semanticTag": "v3.0.1",
    }
    preserved = (
        "app",
        "applicationVersion",
        "sourceRevision",
        "imageTag",
        "imageDigest",
        "semanticTag",
    )
    if any(reviewed.get(field) != baseline.get(field) for field in preserved):
        raise RollbackError("chart maintenance target changes an application or image field")
    if any(reviewed.get(field) != wanted for field, wanted in approved_application.items()):
        raise RollbackError("chart maintenance target is not the approved application tuple")
    chart_tuple = (
        reviewed.get("chartSourceRevision"),
        reviewed.get("chartVersion"),
        reviewed.get("chartDigest"),
    )
    if chart_tuple != (
        "62da11005354e9f9a89c2e58584cdce4c8ec35aa",
        "3.0.3",
        "sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c",
    ):
        raise RollbackError("chart maintenance target is not the reviewed production chart tuple")
    target = copy.deepcopy(baseline)
    for field in ("chartSourceRevision", "chartVersion", "chartDigest"):
        target[field] = reviewed[field]
    return target


def rollback(args: argparse.Namespace, runner: Runner = run) -> dict[str, Any]:
    recovery = getattr(args, "production_metrics_recovery", False)
    args.evidence = args.evidence.expanduser()
    # These attributes cross the pre-reservation boundary deliberately: the
    # outer lifecycle is responsible for preserving failures until an evidence
    # file has been reserved, while _rollback owns the reserved lifecycle.
    args._recovery_failed_stage = "kubeconfig-and-cluster-identity"
    args._recovery_original_failure = None
    try:
        if getattr(args, "configuration_reconciliation", False):
            if not args.kubeconfig or ":" in args.kubeconfig:
                raise RollbackError(
                    "metrics configuration reconciliation requires one explicit absolute kubeconfig"
                )
            kubeconfig = Path(args.kubeconfig).expanduser()
            if not kubeconfig.is_absolute():
                raise RollbackError(
                    "metrics configuration reconciliation requires one explicit absolute kubeconfig"
                )
            args.kubeconfig = str(kubeconfig)
        with tempfile.TemporaryDirectory(prefix="dspace-rollback-values-") as temporary:
            os.chmod(temporary, 0o700)
            if getattr(args, "configuration_reconciliation", False):
                assert_production_target(args.kubeconfig, runner)
            return _rollback(args, runner, Path(temporary))
    except Exception as exc:
        # Preserve every pre-reservation recovery rejection. An existing path is
        # deliberately left byte-for-byte untouched.
        if recovery and not args.evidence.exists():
            failed_stage = args._recovery_failed_stage
            failure = {
                "schemaVersion": SCHEMA_VERSION,
                "operation": RECOVERY_OPERATION,
                "state": "failed",
                "failedStage": failed_stage,
                "failureCode": f"{failed_stage}-failed",
                "failedAt": timestamp(),
                "clusterMayHaveChanged": False,
                "diagnostics": {"failureType": type(exc).__name__},
            }
            if args._recovery_original_failure is not None:
                failure["originalFailure"] = args._recovery_original_failure
            reserve(args.evidence, failure)
        raise


def _rollback(args: argparse.Namespace, runner: Runner, staged_directory: Path) -> dict[str, Any]:
    started = timestamp()
    args.manifest = args.manifest.expanduser()
    args.evidence = args.evidence.expanduser()
    args.verifier = args.verifier.expanduser()
    if getattr(args, "production_metrics_recovery", False):
        args._recovery_failed_stage = "failed-evidence-authorization"
    try:
        baseline = release.validate(release._object(args.manifest), True)
    except release.ManifestError as exc:
        raise RollbackError(f"target must be finalized DSPACE release evidence: {exc}") from exc
    if baseline["environment"] != args.environment:
        raise RollbackError("target manifest environment does not match selected environment")
    configuration_reconciliation = getattr(args, "configuration_reconciliation", False)
    recovery = getattr(args, "production_metrics_recovery", False)
    metrics_operation = configuration_reconciliation
    target = baseline
    if metrics_operation and getattr(args, "maintenance_target", None):
        target = chart_maintenance_target(baseline, args.maintenance_target)
    failed_result = failed_reconciliation(args.failed_evidence, target, runner) if recovery else None
    failed, failed_evidence_sha256 = failed_result if failed_result else (None, None)
    if recovery:
        args._recovery_original_failure = {
            "invocationId": failed["invocationId"],
            "targetManifestFingerprint": failed["targetManifestFingerprint"],
            "evidenceSha256": failed_evidence_sha256,
        }
        args._recovery_failed_stage = "live-state-and-provenance"
    image_value = target["imageTag"]
    if not metrics_operation:
        image_value += f"@{target['imageDigest']}"
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
    if metrics_operation and getattr(args, "maintenance_target", None):
        configured_version = chart_pin(root / config["SUGARKUBE_VERSION_FILE"])
        if configured_version != target["chartVersion"]:
            raise RollbackError("configured production chart pin differs from maintenance target")
    values, values_proof = stage_values(config, root, staged_directory)
    environment = cluster_environment(runner, args.kubeconfig)
    if environment != args.environment:
        raise RollbackError("connected cluster environment does not match selected environment")
    bundled_verifier = (
        args.verifier.resolve() == (REPO_ROOT / "scripts/dspace_runtime_verifier.py").resolve()
    )
    if recovery and not bundled_verifier:
        raise RollbackError("recovery requires the repository runtime verifier")
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
    verifier_manifest = args.manifest
    if metrics_operation and target is not baseline:
        verifier_manifest = staged_directory / "approved-target.json"
        verifier_manifest.write_text(release._canonical(approved), encoding="utf-8")
        os.chmod(verifier_manifest, 0o600)
    extended_verifier = verifier_accepts_runtime_arguments(
        args.verifier,
        args.environment,
        verifier_manifest,
        getattr(args, "smoke_runner", None),
        args.kubeconfig,
        args.config,
        runner,
    )
    if bundled_verifier and not extended_verifier:
        raise RollbackError("repository runtime verifier rejected its required arguments")
    coordinate = release.chart_coordinate(approved)
    helm_values = [part for path in values for part in ("--values", str(path))]
    pull_policy_args = (
        ["--set-string", "image.pullPolicy=Always"] if metrics_operation else []
    )
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
            f"image.tag={image_value}",
            *pull_policy_args,
        ]
    )
    before_helm, _before_history, before_identity = helm_snapshot(
        runner, args.kubeconfig, "dspace", "dspace"
    )
    before_pods = pods(runner, args.kubeconfig, "dspace", "dspace", require_any=False)
    recovery_workloads = None
    recovery_raw_pods = None
    recovery_render = None
    if metrics_operation:
        if args.environment != "prod":
            raise RollbackError("metrics configuration reconciliation is production-only")
        expected_before_revision = 10 if recovery else baseline["helmRevision"]
        expected_before_chart = target["chartVersion"] if recovery else baseline["chartVersion"]
        if before_identity[2] != expected_before_revision:
            raise RollbackError("live Helm revision differs from authorized provenance")
        runner(
            [
                "env",
                f"KUBECONFIG={args.kubeconfig}",
                sys.executable,
                str(REPO_ROOT / "scripts" / "observability_app_metrics.py"),
                "secret-check",
                "--app",
                "dspace",
                "--env",
                "prod",
            ]
        )
        if before_identity[:2] != ("dspace", expected_before_chart):
            provenance = "authorized live chart" if recovery else "finalized provenance"
            raise RollbackError(f"live chart coordinate differs from {provenance}")
        if recovery and before_helm.get("info", {}).get("description") != (
            f"sugarkube-dspace-metrics-reconciliation:{failed['invocationId']}"
        ):
            raise RollbackError("revision 10 is not bound to the failed invocation")
        if len(before_pods) != 2 or any(not pod.get("ready") for pod in before_pods):
            raise RollbackError("live release must have exactly two Ready DSPACE pods")
        live_values = json_command(
            runner,
            [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "get",
                "values",
                "dspace",
                "--namespace",
                "dspace",
                "-o",
                "json",
            ],
            "Helm stored values",
        )
        desired_values = app_chart.merged_values_document(tuple(str(path) for path in values))
        if not isinstance(desired_values, dict):
            raise RollbackError("desired values are structurally invalid")
        desired_values["image"] = {
            "repository": release.IMAGE_REF,
            "tag": target["imageTag"],
            "pullPolicy": "Always",
        }
        if recovery:
            recovery_workloads, recovery_raw_pods = raw_release_objects(runner, args.kubeconfig)
            validate_workload_pull_policy(
                recovery_workloads, "IfNotPresent", recovery_raw_pods
            )
        current_values_path = staged_directory / "live-values.json"
        current_values_path.write_text(release._canonical(live_values), encoding="utf-8")
        os.chmod(current_values_path, 0o600)
        installed_manifest = runner(
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
        approved_current_render = runner(
            [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "template",
                "dspace",
                release.chart_coordinate(
                    {
                        **approved,
                        "chartVersion": (
                            target["chartVersion"] if recovery else baseline["chartVersion"]
                        ),
                        "chartDigest": (
                            target["chartDigest"] if recovery else baseline["chartDigest"]
                        ),
                    }
                ),
                "--namespace",
                "dspace",
                "--values",
                str(current_values_path),
            ]
        )
        if installed_manifest.strip() != approved_current_render.strip():
            raise RollbackError("live manifest does not match the approved chart digest")
        if recovery:
            recovery_render = approved_current_render
            validate_rendered_deployment(recovery_render, recovery_workloads)
        try:
            release.verify_helm_stored_values(
                approved,
                desired_values,
                "prod",
            )
        except release.ManifestError as exc:
            raise RollbackError("desired production metrics contract is invalid") from exc

        if recovery:
            recovery_values = copy.deepcopy(desired_values)
            recovery_values["image"].pop("pullPolicy")
            if live_values != recovery_values:
                raise RollbackError(
                    "live values have drift beyond the sole recoverable pull policy"
                )
            computed_values = json_command(
                runner,
                [
                    "helm",
                    "--kubeconfig",
                    args.kubeconfig,
                    "get",
                    "values",
                    "dspace",
                    "--namespace",
                    "dspace",
                    "--all",
                    "-o",
                    "json",
                ],
                "Helm computed values",
            )
            defaults_path = staged_directory / "chart-defaults.yaml"
            defaults_path.write_text(
                runner(["helm", "show", "values", coordinate]), encoding="utf-8"
            )
            os.chmod(defaults_path, 0o600)
            expected_computed = app_chart.merged_values_document(
                (str(defaults_path), *(str(path) for path in values))
            )
            if not isinstance(expected_computed, dict):
                raise RollbackError("chart defaults produced invalid computed values")
            expected_image_values = expected_computed.get("image")
            if not isinstance(expected_image_values, dict):
                raise RollbackError("chart defaults do not define image values")
            expected_image_values.update(
                repository=release.IMAGE_REF,
                tag=target["imageTag"],
                pullPolicy="IfNotPresent",
            )
            if computed_values != expected_computed:
                raise RollbackError(
                    "live computed values differ from the exact recoverable chart defaults"
                )
            strict_computed = copy.deepcopy(expected_computed)
            strict_computed["image"]["pullPolicy"] = "Always"
            try:
                release.verify_helm_stored_values(approved, strict_computed, "prod")
            except release.ManifestError as exc:
                raise RollbackError("live computed values violate the approved contract") from exc
            # Prove the complete incident state, including both public journeys,
            # bounded remote chat, replica/ownership identity and revision 10,
            # before asking for authorization or reserving/mutating anything.
            args._recovery_failed_stage = "runtime-and-metrics-preflight"
            validate_verifier_result(
                json_command(
                    runner,
                    runtime_verifier_command(
                        args, target, verifier_manifest, expected_revision=10
                    ),
                    "recovery runtime preflight",
                ),
                target,
                "prod",
            )
            # This repository verifier owns the Secret, ServiceMonitor, exactly
            # two healthy targets, metric-family, and Grafana API contract.
            runner(
                [
                    "env",
                    f"KUBECONFIG={args.kubeconfig}",
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "observability_app_metrics.py"),
                    "verify",
                    "--app",
                    "dspace",
                    "--env",
                    "prod",
                ]
            )
        else:
            live_metrics = live_values.get("metrics")
            live_monitor = live_values.get("serviceMonitor")
            if live_metrics not in (None, {"enabled": False}) or live_monitor not in (
                None,
                {"enabled": False},
            ):
                raise RollbackError("live metrics values are not the approved disabled baseline")
            baseline_values, desired_baseline = configuration_comparison_baselines(
                live_values, desired_values
            )
            if baseline_values != desired_baseline:
                raise RollbackError(
                    "unrelated Helm values drift blocks configuration reconciliation"
                )
    # Keep the registry proof fresh: no tag resolution occurs between this
    # exact-digest check and confirmation/reservation/mutation.
    if recovery:
        args._recovery_failed_stage = "immutable-oci-provenance"
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
    if recovery:
        args._recovery_failed_stage = "live-state-and-provenance"
    print(summary(before_helm, before_identity, before_pods, target, values_proof))
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
    if metrics_operation and (
        current_images != {f"{release.IMAGE_REF}:{target['imageTag']}"}
        or current_ids != {target["imageDigest"]}
    ):
        raise RollbackError("live image coordinate differs from finalized provenance")
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
    expected_image = f"{release.IMAGE_REF}:{image_value}"
    if (
        installed_render is not None
        and installed_render == rendered_target
        and current_images == {expected_image}
        and current_ids == {target["imageDigest"]}
    ):
        raise RollbackError("current rendered release is already the exact approved target")
    if metrics_operation:
        render_errors = app_chart.validate_rendered_manifest(
            rendered_target,
            app_chart.ReleaseInputs(
                "dspace",
                args.environment,
                "dspace",
                "dspace",
                coordinate,
                target["chartVersion"],
                tuple(str(path) for path in values),
                target["imageTag"],
            ),
        )
        if render_errors:
            raise RollbackError("strict application chart render validation failed")
    # Matching chart version and image identity alone is not exact proof: Helm
    # status cannot establish the installed OCI chart digest.
    if recovery:
        args._recovery_failed_stage = "confirmation"
    (
        recovery_confirmation(args.confirm)
        if recovery
        else confirmation(args.environment, args.confirm, target)
    )
    sugarkube_revision = runner(["git", "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sugarkube_revision):
        raise RollbackError("could not capture the Sugarkube revision")
    _, _, preflight_identity = helm_snapshot(runner, args.kubeconfig, "dspace", "dspace")
    if preflight_identity != before_identity:
        raise RollbackError("Helm revision changed during preflight")

    invocation = uuid.uuid4().hex
    target_fingerprint = hashlib.sha256(release._canonical(target).encode()).hexdigest()
    evidence: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "operation": (
            RECOVERY_OPERATION
            if recovery
            else (
                "dspaceProductionMetricsReconciliation"
                if configuration_reconciliation
                else OPERATION
            )
        ),
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
            "helmRevision": before_identity[2],
            "helmStatus": before_helm.get("info", {}).get("status"),
            "chartName": before_identity[0],
            "chartVersion": before_identity[1],
            "pods": before_pods,
        },
        "ociPreflight": oci,
    }
    if recovery:
        evidence["originalFailure"] = {
            "invocationId": failed["invocationId"],
            "targetManifestFingerprint": failed["targetManifestFingerprint"],
            "evidenceSha256": failed_evidence_sha256,
        }
    if recovery:
        args._recovery_failed_stage = "reservation"
    reserve(args.evidence, evidence)
    mutated = False
    production_target_verified = not metrics_operation
    failed_stage = "pre-mutation-revalidation"
    operation = (
        "metrics-pull-policy-recovery"
        if recovery
        else ("metrics-reconciliation" if configuration_reconciliation else "manifest-rollback")
    )
    description = f"sugarkube-dspace-{operation}:{invocation}"
    try:
        if metrics_operation:
            production_target_verified = False
            assert_production_target(args.kubeconfig, runner)
            production_target_verified = True
        if runner(["git", "rev-parse", "HEAD"]).strip() != sugarkube_revision:
            raise RollbackError("Sugarkube revision changed before mutation")
        if metrics_operation:
            current_status, current_history, current_identity = helm_snapshot(
                runner, args.kubeconfig, "dspace", "dspace"
            )
            if recovery:
                history_payload = helm_history(runner, args.kubeconfig, "dspace", "dspace")
                if not isinstance(history_payload, list) or not all(
                    isinstance(item, dict) for item in history_payload
                ):
                    raise RollbackError("revision-10 Helm history changed before mutation")
                current_history = history_payload
                try:
                    current_identity = release.resolve_helm_identity(
                        current_status,
                        current_history,
                        "dspace",
                        target["chartVersion"],
                    )
                except release.ManifestError as exc:
                    raise RollbackError(
                        "revision-10 Helm history changed before mutation"
                    ) from exc
            if current_identity != before_identity:
                raise RollbackError("Helm coordinates changed before mutation")
            current_pods = pods(runner, args.kubeconfig, "dspace", "dspace")
            if current_pods != before_pods:
                raise RollbackError("DSPACE pods changed before mutation")
            current_values = json_command(
                runner,
                [
                    "helm",
                    "--kubeconfig",
                    args.kubeconfig,
                    "get",
                    "values",
                    "dspace",
                    "--namespace",
                    "dspace",
                    "-o",
                    "json",
                ],
                "Helm stored values",
            )
            if current_values != live_values:
                raise RollbackError("Helm values changed before mutation")
            if recovery:
                current_computed_values = json_command(
                    runner,
                    [
                        "helm",
                        "--kubeconfig",
                        args.kubeconfig,
                        "get",
                        "values",
                        "dspace",
                        "--namespace",
                        "dspace",
                        "--all",
                        "-o",
                        "json",
                    ],
                    "Helm computed values",
                )
                if current_computed_values != computed_values:
                    raise RollbackError("Helm computed values changed before mutation")
                current_workloads, current_raw_pods = raw_release_objects(
                    runner, args.kubeconfig
                )
                validate_workload_pull_policy(
                    current_workloads, "IfNotPresent", current_raw_pods
                )
                validate_rendered_deployment(recovery_render, current_workloads)
            runner(
                [
                    "env",
                    f"KUBECONFIG={args.kubeconfig}",
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "observability_app_metrics.py"),
                    "secret-check",
                    "--app",
                    "dspace",
                    "--env",
                    "prod",
                ]
            )
            production_target_verified = False
            assert_production_target(args.kubeconfig, runner)
            production_target_verified = True
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
            f"image.tag={image_value}",
            *pull_policy_args,
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
        after_helm, after_history, after_identity = helm_snapshot(
            runner, args.kubeconfig, "dspace", "dspace"
        )
        after_revision = after_identity[2]
        if (
            after_helm.get("name") != "dspace"
            or after_helm.get("namespace") != "dspace"
            or after_helm.get("info", {}).get("status") != "deployed"
        ):
            raise RollbackError("Helm did not report the expected deployed release")
        if after_helm.get("info", {}).get("description") != description:
            raise RollbackError("Helm release description is not bound to this invocation")
        if metrics_operation and after_revision != before_identity[2] + 1:
            raise RollbackError("Helm revision did not advance exactly once")
        if not metrics_operation and after_revision <= before_identity[2]:
            raise RollbackError("Helm revision did not advance")
        if after_identity[0] != "dspace" or after_identity[1] != target["chartVersion"]:
            raise RollbackError("installed chart name/version does not match target")
        changed = metrics_operation or (
            before_identity[1] != target["chartVersion"]
            or current_ids != {target["imageDigest"]}
            or current_images
            != {f"{release.IMAGE_REF}:{target['imageTag']}@{target['imageDigest']}"}
        )
        verify_post_pods(
            after_pods,
            before_pods,
            target,
            changed,
            retain_tag=metrics_operation,
        )
        if metrics_operation and len(after_pods) != 2:
            raise RollbackError("reconciliation did not produce exactly two Ready DSPACE pods")
        # Reuse finalization's strict Deployment/ReplicaSet ownership validator.
        failed_stage = "ownership-and-finalization-proof"
        workloads, raw_pods = raw_release_objects(runner, args.kubeconfig)
        if recovery:
            validate_workload_pull_policy(workloads, "Always", raw_pods)
            validate_rendered_deployment(rendered_target, workloads)
        helm_stored_values_result = None
        if approved["schemaVersion"] == 2:
            stored_values = json_command(
                runner,
                [
                    "helm",
                    "--kubeconfig",
                    args.kubeconfig,
                    "get",
                    "values",
                    "dspace",
                    "--namespace",
                    "dspace",
                    "--all",
                    "-o",
                    "json",
                ],
                "Helm stored values",
            )
            try:
                if recovery and stored_values != strict_computed:
                    raise RollbackError(
                        "post-upgrade computed values differ from the exact approved document"
                    )
                helm_stored_values_result = release.verify_helm_stored_values(
                    approved, stored_values, args.environment
                )
            except release.ManifestError as exc:
                raise RollbackError("post-upgrade Helm stored values are invalid") from exc
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
            expected_image_coordinate=f"{release.IMAGE_REF}:{image_value}",
            helm_stored_values_result=helm_stored_values_result,
            helm_history=after_history,
        )
        verifier_command = [
            str(args.verifier), "verify", "--environment", args.environment,
            "--release", "dspace", "--namespace", "dspace",
            "--application-version", target["applicationVersion"],
            "--source-revision", target["sourceRevision"],
            "--provider", target["expectedDefaultChatProvider"],
        ]
        # The repository verifier owns these extended arguments.  Preserve the
        # original verify contract for compatible third-party verifiers rather
        # than discovering that they reject new flags after Helm has mutated.
        if extended_verifier:
            verifier_command.extend(("--manifest", str(verifier_manifest)))
            smoke_runner = getattr(args, "smoke_runner", None)
            if smoke_runner:
                verifier_command.extend(("--smoke-runner", str(smoke_runner)))
            verifier_command.extend(("--kubeconfig", str(args.kubeconfig)))
            if args.config:
                verifier_command.extend(("--config", str(args.config)))
            if recovery:
                verifier_command.extend(("--expected-helm-revision", "11"))
        failed_stage = "runtime-verification"
        verifier = validate_verifier_result(
            json_command(runner, verifier_command, "runtime verifier"), target, args.environment
        )
        if metrics_operation:
            failed_stage = "production-metrics-verification"
            runner(
                [
                    "env",
                    f"KUBECONFIG={args.kubeconfig}",
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "observability_app_metrics.py"),
                    "verify",
                    "--app",
                    "dspace",
                    "--env",
                    "prod",
                ]
            )
        failed_stage = "revision-stability-collection"
        _stable, _stable_history, stable_identity = helm_snapshot(
            runner, args.kubeconfig, "dspace", "dspace"
        )
        if stable_identity != after_identity:
            raise RollbackError("Helm revision changed concurrently during evidence collection")
        result = {
            **evidence,
            "state": "succeeded",
            "completedAt": timestamp(),
            "sugarkubeRevision": sugarkube_revision,
            "helm": {
                "beforeRevision": before_identity[2],
                "afterRevision": after_revision,
                "status": "deployed",
                "chartName": "dspace",
                "chartVersion": after_identity[1],
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
                **(
                    {
                        "helmStoredValues": helm_stored_values_result,
                        "productionMetrics": {
                            "secretContract": True,
                            "serviceMonitor": True,
                            "healthyTargets": 2,
                            "requiredFamilies": True,
                            "unauthenticatedStatus": 401,
                        },
                    }
                    if metrics_operation
                    else {}
                ),
            },
        }
        replace_reserved(args.evidence, result)
        return result
    except Exception as exc:
        diagnostics: dict[str, Any] = {}
        if production_target_verified:
            try:
                observed_helm, _observed_history, observed_identity = helm_snapshot(
                    runner,
                    args.kubeconfig,
                    "dspace",
                    "dspace",
                    require_deployed=False,
                )
                observed_info = observed_helm.get("info", {})
                diagnostics["helm"] = {
                    "release": observed_helm.get("name"),
                    "namespace": observed_helm.get("namespace"),
                    "revision": observed_identity[2],
                    "status": observed_info.get("status"),
                    "chartName": observed_identity[0],
                    "chartVersion": observed_identity[1],
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
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--maintenance-target", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--smoke-runner", type=Path)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--kubeconfig")
    parser.add_argument("--oras", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras"))
    parser.add_argument("--timeout", default="10m")
    parser.add_argument("--configuration-reconciliation", action="store_true")
    parser.add_argument("--production-metrics-recovery", action="store_true")
    parser.add_argument("--failed-evidence", type=Path)
    args = parser.parse_args(argv)
    if args.production_metrics_recovery:
        if (
            args.configuration_reconciliation
            or args.manifest is not None
            or args.baseline_manifest is not None
        ):
            parser.error(
                "production metrics recovery does not accept reconciliation or manifest flags"
            )
        if args.failed_evidence is None or args.maintenance_target is None:
            parser.error(
                "production metrics recovery requires --failed-evidence and --maintenance-target"
            )
        args.configuration_reconciliation = True
        args.baseline_manifest = PRODUCTION_BASELINE
    if args.configuration_reconciliation:
        if (
            args.manifest is not None
            or args.baseline_manifest is None
            or args.maintenance_target is None
        ):
            parser.error(
                "configuration reconciliation requires --baseline-manifest and "
                "--maintenance-target, not --manifest"
            )
        args.manifest = args.baseline_manifest
    elif (
        args.manifest is None
        or args.baseline_manifest is not None
        or args.maintenance_target is not None
    ):
        parser.error("rollback requires --manifest and does not accept maintenance coordinates")
    if args.kubeconfig is None and not (
        args.configuration_reconciliation
    ):
        args.kubeconfig = str(Path.home() / ".kube" / "config-sugarkube")
    try:
        rollback(args)
    except (RollbackError, app_config.AppConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
