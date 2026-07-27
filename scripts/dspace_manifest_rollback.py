#!/usr/bin/env python3
"""Restore DSPACE from finalized immutable evidence and prove the result."""

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

# Permit direct execution by path while retaining the package import used by tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

SCHEMA_VERSION = 1
OPERATION = "dspaceManifestRollback"
CAPABILITY_SCHEMA = "sugarkube.dspace-runtime-verifier/v1"
RESULT_FIELDS = (
    "schemaVersion",
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "journeys",
)
REQUIRED_JOURNEYS = ("publicHome", "publicHealth", "chat")


class RollbackError(ValueError):
    """A rollback safety condition was not satisfied."""


def canonical(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def run(command: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        command, input=input_text, check=False, capture_output=True, text=True
    )
    if completed.returncode:
        # Command output can contain rendered secrets, HTTP bodies, or credentials.
        raise RollbackError(f"command failed ({command[0]})")
    return completed.stdout


def json_output(command: list[str], runner: Callable[..., str] = run) -> dict[str, Any]:
    try:
        value = json.loads(runner(command))
    except (json.JSONDecodeError, TypeError) as exc:
        raise RollbackError(f"{command[0]} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RollbackError(f"{command[0]} returned non-object JSON")
    return value


def load_target(path: Path, environment: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RollbackError(f"cannot read target finalized manifest: {path}") from exc
    if not isinstance(value, dict):
        raise RollbackError("target manifest must be a JSON object")
    try:
        release_manifest.validate(value, True)
    except release_manifest.ManifestError as exc:
        raise RollbackError(f"target must be finalized DSPACE release evidence: {exc}") from exc
    if value["environment"] != environment:
        raise RollbackError("target manifest environment does not match requested environment")
    return value


def target_projection(value: dict[str, Any]) -> dict[str, Any]:
    """Project final evidence through the existing candidate/OCI validator."""
    projected = {field: value[field] for field in release_manifest.CANDIDATE_FIELDS}
    projected["recordType"] = "candidate"
    return release_manifest.validate(projected, False)


def fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def verifier_capabilities(executable: Path, runner: Callable[..., str] = run) -> dict[str, Any]:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RollbackError("runtime verifier must be an available executable file")
    value = json_output([str(executable), "capabilities"], runner)
    expected = {"schemaVersion", "checks", "acceptsRequestOnStdin"}
    if set(value) != expected:
        raise RollbackError("runtime verifier capabilities contain missing or unknown fields")
    if value["schemaVersion"] != CAPABILITY_SCHEMA or value["acceptsRequestOnStdin"] is not True:
        raise RollbackError("runtime verifier uses an incompatible capability contract")
    checks = value["checks"]
    required = [
        "applicationVersion",
        "runtimeSourceRevision",
        "frontendSourceRevision",
        "defaultProvider",
        *REQUIRED_JOURNEYS,
    ]
    if checks != required:
        raise RollbackError("runtime verifier does not advertise the exact required checks")
    return value


def validate_verifier_result(value: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    """Strict reusable verifier-result validation for rollback and later gates."""
    if set(value) != set(RESULT_FIELDS):
        raise RollbackError("runtime verifier result contains missing or unknown fields")
    if value["schemaVersion"] != CAPABILITY_SCHEMA:
        raise RollbackError("runtime verifier result schema is incompatible")
    comparisons = {
        "applicationVersion": target["applicationVersion"],
        "runtimeSourceRevision": target["sourceRevision"],
        "frontendSourceRevision": target["sourceRevision"],
        "defaultProvider": target["expectedDefaultChatProvider"],
    }
    for field, expected in comparisons.items():
        if not isinstance(value[field], str) or value[field] != expected:
            raise RollbackError(f"runtime verifier {field} mismatch")
    journeys = value["journeys"]
    if not isinstance(journeys, list) or len(journeys) != len(REQUIRED_JOURNEYS):
        raise RollbackError("runtime verifier journeys are incomplete")
    names: list[str] = []
    for item in journeys:
        if not isinstance(item, dict) or set(item) != {"name", "passed"}:
            raise RollbackError("runtime verifier journey result is malformed")
        if not isinstance(item["name"], str) or not isinstance(item["passed"], bool):
            raise RollbackError("runtime verifier journey fields have invalid types")
        names.append(item["name"])
        if not item["passed"]:
            raise RollbackError(f"runtime verifier journey failed: {item['name']}")
    if tuple(names) != REQUIRED_JOURNEYS:
        raise RollbackError("runtime verifier journeys are missing, unknown, or out of order")
    return value


def values_evidence(config: dict[str, Any], root: Path) -> list[dict[str, str]]:
    raw = config.get("SUGARKUBE_VALUES")
    if not isinstance(raw, str) or not raw:
        raise RollbackError("DSPACE configuration has no values chain")
    result = []
    for portable in raw.split(","):
        if not portable or Path(portable).is_absolute() or ".." in Path(portable).parts:
            raise RollbackError("values paths must be non-empty portable repository paths")
        path = root / portable
        if not path.is_file() or not os.access(path, os.R_OK):
            raise RollbackError(f"values file is missing or unreadable: {portable}")
        result.append({"path": portable, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def pod_identities(pods: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for pod in pods.get("items", []):
        metadata, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        containers = spec.get("containers", [])
        statuses = status.get("containerStatuses", [])
        result.append(
            {
                "name": metadata.get("name"),
                "uid": metadata.get("uid"),
                "startTime": status.get("startTime"),
                "deletionTimestamp": metadata.get("deletionTimestamp"),
                "phase": status.get("phase"),
                "ready": any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", [])
                ),
                "containers": [
                    {
                        "name": container.get("name"),
                        "image": container.get("image"),
                        "imageID": next(
                            (
                                s.get("imageID")
                                for s in statuses
                                if s.get("name") == container.get("name")
                            ),
                            None,
                        ),
                    }
                    for container in containers
                ],
            }
        )
    return sorted(result, key=lambda item: str(item["name"]))


def helm_binding(value: dict[str, Any]) -> tuple[Any, ...]:
    metadata = value.get("chart", {}).get("metadata", {})
    return (
        value.get("name"),
        value.get("namespace"),
        value.get("version"),
        value.get("info", {}).get("status"),
        value.get("info", {}).get("description"),
        metadata.get("name"),
        metadata.get("version"),
    )


def confirmation(environment: str, target: dict[str, Any], supplied: str) -> None:
    expected = f"DSPACE:prod:{target['sourceRevision']}"
    if environment == "prod" and not secrets.compare_digest(supplied, expected):
        raise RollbackError(f"production confirmation must exactly equal {expected}")
    if environment == "staging" and supplied:
        raise RollbackError("staging rollback is non-interactive; omit confirmation")


def reserve(path: Path, target: dict[str, Any], environment: str) -> tuple[str, Path]:
    normalized = path.expanduser().resolve(strict=False)
    sidecar = normalized.with_name(normalized.name + release_manifest.RESERVATION_SUFFIX)
    normalized.parent.mkdir(parents=True, exist_ok=True)
    if normalized.exists():
        raise RollbackError(f"refusing to overwrite rollback evidence: {normalized}")
    invocation = secrets.token_hex(32)
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "operation": OPERATION,
        "state": "reserved",
        "output": str(normalized),
        "targetManifestFingerprint": fingerprint(target),
        "environment": environment,
        "invocationId": invocation,
    }
    try:
        fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RollbackError(
            f"rollback evidence destination is already reserved: {sidecar}"
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(canonical(record))
        stream.flush()
        os.fsync(stream.fileno())
    return invocation, sidecar


def write_new(path: Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise RollbackError(f"refusing to overwrite rollback evidence: {path}") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def execute(args: argparse.Namespace, runner: Callable[..., str] = run) -> dict[str, Any]:
    if args.environment not in {"staging", "prod"}:
        raise RollbackError("environment must be staging or prod")
    root = Path(args.repository).resolve()
    target = load_target(args.manifest, args.environment)
    projected = target_projection(target)
    confirmation(args.environment, target, args.confirmation)
    started = _now()

    kubeconfig = str(Path(args.kubeconfig).expanduser())
    runner(
        [
            sys.executable,
            str(root / "scripts/cluster_identity.py"),
            "assert",
            "--kubeconfig",
            kubeconfig,
            "--env",
            args.environment,
        ]
    )
    config = json.loads(
        runner(
            [
                sys.executable,
                str(root / "scripts/app_config.py"),
                "json",
                "--app",
                "dspace",
                "--env",
                args.environment,
            ]
        )
    )
    if (
        config.get("SUGARKUBE_RELEASE") != "dspace"
        or config.get("SUGARKUBE_NAMESPACE") != "dspace"
        or config.get("SUGARKUBE_CHART") != "oci://" + release_manifest.CHART_REF
    ):
        raise RollbackError("resolved configuration is not canonical DSPACE")
    values = values_evidence(config, root)
    capabilities = verifier_capabilities(args.verifier, runner)
    oci = release_manifest.preflight(
        projected, release_manifest.IMAGE_REF, release_manifest.CHART_REF, args.oras
    )
    chart = release_manifest.chart_coordinate(projected)
    value_args = [item for entry in values for item in ("-f", str(root / entry["path"]))]
    runner(
        [
            "helm",
            "--kubeconfig",
            kubeconfig,
            "template",
            "dspace",
            chart,
            "--namespace",
            "dspace",
            *value_args,
            "--set-string",
            f"image.tag={target['imageTag']}",
        ]
    )

    helm_cmd = [
        "helm",
        "--kubeconfig",
        kubeconfig,
        "status",
        "dspace",
        "--namespace",
        "dspace",
        "-o",
        "json",
    ]
    pods_cmd = [
        "kubectl",
        "--kubeconfig",
        kubeconfig,
        "-n",
        "dspace",
        "get",
        "pods",
        "-l",
        "app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace",
        "-o",
        "json",
    ]
    before_helm = json_output(helm_cmd, runner)
    before_pods_json = json_output(pods_cmd, runner)
    before_pods = pod_identities(before_pods_json)
    target_summary = {
        "current": {
            "helmRevision": before_helm.get("version"),
            "status": before_helm.get("info", {}).get("status"),
            "chartName": before_helm.get("chart", {}).get("metadata", {}).get("name"),
            "chartVersion": before_helm.get("chart", {}).get("metadata", {}).get("version"),
            "pods": before_pods,
        },
        "target": {
            "chartVersion": target["chartVersion"],
            "chartDigest": target["chartDigest"],
            "imageTag": target["imageTag"],
            "imageDigest": target["imageDigest"],
            "sourceRevision": target["sourceRevision"],
            "applicationVersion": target["applicationVersion"],
            "provider": target["expectedDefaultChatProvider"],
        },
    }
    print("DSPACE current-versus-target preflight:\n" + canonical(target_summary), end="")
    current_chart = before_helm.get("chart", {}).get("metadata", {})
    current_app = [c for p in before_pods for c in p["containers"] if c["name"] == "dspace"]
    if (
        current_chart.get("version") == target["chartVersion"]
        and current_app
        and all(
            c["image"] == f"{release_manifest.IMAGE_REF}:{target['imageTag']}"
            and release_manifest._image_id_digest(c["imageID"]) == target["imageDigest"]
            for c in current_app
        )
    ):
        raise RollbackError("exact no-op rollback is not permitted")

    invocation, sidecar = reserve(args.evidence, target, args.environment)
    description = f"sugarkube-dspace-manifest-rollback:{invocation}"
    mutated = False
    try:
        mutation = [
            "helm",
            "--kubeconfig",
            kubeconfig,
            "upgrade",
            "dspace",
            chart,
            "--namespace",
            "dspace",
            *value_args,
            "--set-string",
            f"image.tag={target['imageTag']}",
            "--description",
            description,
            "--wait",
            "--timeout",
            args.timeout,
        ]
        runner(mutation)
        mutated = True
        runner(
            [
                "kubectl",
                "--kubeconfig",
                kubeconfig,
                "-n",
                "dspace",
                "rollout",
                "status",
                "deployment/dspace",
                "--timeout",
                args.timeout,
            ]
        )
        after_helm = json_output(helm_cmd, runner)
        after_pods_json = release_manifest._settle_release_pods(
            pods_cmd, runner=lambda command: runner(command)
        )
        after_pods = pod_identities(after_pods_json)
        workloads = json.loads(
            runner(
                [
                    "kubectl",
                    "--kubeconfig",
                    kubeconfig,
                    "-n",
                    "dspace",
                    "get",
                    "replicasets,deployments",
                    "-l",
                    "app.kubernetes.io/name=dspace,app.kubernetes.io/instance=dspace",
                    "-o",
                    "json",
                ]
            )
        )
        final_candidate = release_manifest.finalize(
            projected,
            after_helm,
            after_pods_json,
            workloads,
            oci,
            environment=args.environment,
            image_tag=target["imageTag"],
            chart_version=target["chartVersion"],
            release="dspace",
            namespace="dspace",
            cluster_environment=args.environment,
            invocation_description=description,
        )
        if (
            not isinstance(before_helm.get("version"), int)
            or after_helm.get("version", 0) <= before_helm["version"]
        ):
            raise RollbackError("Helm revision did not advance")
        before_ids = {(p["uid"], p["startTime"]) for p in before_pods}
        after_ids = {(p["uid"], p["startTime"]) for p in after_pods}
        artifact_changed = (
            any(
                c["imageID"] != target["imageDigest"]
                and not str(c["imageID"]).endswith(target["imageDigest"])
                for c in current_app
            )
            or current_chart.get("version") != target["chartVersion"]
        )
        if artifact_changed and (before_ids & after_ids or before_ids == after_ids):
            raise RollbackError(
                "target artifact differed but old serving pods remain or no replacement occurred"
            )
        request = {
            "schemaVersion": CAPABILITY_SCHEMA,
            "applicationVersion": target["applicationVersion"],
            "sourceRevision": target["sourceRevision"],
            "defaultProvider": target["expectedDefaultChatProvider"],
            "requiredJourneys": list(REQUIRED_JOURNEYS),
        }
        verifier_raw = runner([str(args.verifier), "verify"], input_text=json.dumps(request))
        try:
            verifier_value = json.loads(verifier_raw)
        except json.JSONDecodeError as exc:
            raise RollbackError("runtime verifier returned invalid JSON") from exc
        if not isinstance(verifier_value, dict):
            raise RollbackError("runtime verifier returned non-object JSON")
        verified = validate_verifier_result(verifier_value, target)
        stable_helm = json_output(helm_cmd, runner)
        if helm_binding(stable_helm) != helm_binding(after_helm):
            raise RollbackError("Helm release changed during rollback evidence collection")
        evidence = {
            "schemaVersion": SCHEMA_VERSION,
            "operation": OPERATION,
            "targetManifestFingerprint": fingerprint(target),
            "environment": args.environment,
            "release": "dspace",
            "namespace": "dspace",
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
            "values": values,
            "sugarkubeRevision": runner(["git", "-C", str(root), "rev-parse", "HEAD"]).strip(),
            "before": {"helmRevision": before_helm["version"], "pods": before_pods},
            "after": {"helmRevision": after_helm["version"], "pods": after_pods},
            "verification": {
                "oci": oci,
                "cluster": final_candidate["verificationResults"],
                "runtime": verified,
                "verifierCapabilities": capabilities,
            },
            "startedAt": started,
            "completedAt": _now(),
        }
        write_new(args.evidence.resolve(), evidence)
        sidecar.unlink()
        return evidence
    except Exception as exc:
        state = "cluster-state-may-have-changed" if mutated else "reserved"
        diagnostic = json.loads(sidecar.read_text(encoding="utf-8"))
        diagnostic["state"] = state
        diagnostic["failedAt"] = _now()
        diagnostic["failure"] = type(exc).__name__
        sidecar.write_text(canonical(diagnostic), encoding="utf-8")
        raise RollbackError(
            f"rollback failed after evidence reservation ({state}); preserve {sidecar} "
            "and reconcile manually; no automatic second rollback was attempted"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--verifier", required=True, type=Path)
    parser.add_argument("--confirmation", default="")
    parser.add_argument(
        "--kubeconfig", default=os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config"))
    )
    parser.add_argument("--oras", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras"))
    parser.add_argument("--timeout", default="5m")
    parser.add_argument("--repository", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args(argv)
    try:
        execute(args)
    except (RollbackError, release_manifest.ManifestError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
