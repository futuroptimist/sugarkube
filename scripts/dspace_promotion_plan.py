#!/usr/bin/env python3
"""Fail-closed, offline-only planning for the DSPACE 3.1.1 promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import app_chart
import dspace_manifest_rollback as rollback
import dspace_release_manifest as release

ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = ROOT / "docs/apps/dspace.promotion-target.json"
BASELINE_PATH = (
    ROOT / "deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json"
)
HISTORICAL_STAGING_PATH = (
    ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
)
MAINTENANCE_PATH = ROOT / "docs/apps/dspace.prod-metrics-chart-target.json"
FAMILIES = (
    "dspace_build_info",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "dspace_http_request_duration_seconds_bucket",
    "dspace_http_requests_total",
    "dspace_instrumentation_up",
)
DEFAULT_FAMILIES = ("process_cpu_user_seconds_total", "nodejs_eventloop_lag_seconds")
TARGET = {
    "applicationVersion": "3.1.1",
    "sourceRevision": "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2",
    "chartSourceRevision": "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2",
    "imageTag": "main-22f506e",
    "imageDigest": "sha256:467890df969cc7938cb760f965fd8f90a8912b1dcb1f8425bc808216b7e1512b",
    "chartVersion": "3.1.2",
    "chartDigest": "sha256:544a3e31ab827e6d2bf28754a19d8af17b0402b75159c2a40c1b3dfe5eb60161",
    "semanticTag": "v3.1.1",
}


class PlanError(ValueError):
    """Planning input is unsafe, incomplete, or inconsistent."""


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"invalid JSON report: {path}") from exc
    if not isinstance(value, dict):
        raise PlanError("report must be an object")
    return value


def exact(value: dict[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise PlanError(f"{label} schema mismatch")


def target() -> dict[str, Any]:
    value = load(TARGET_PATH)
    release._exact_fields(value, release.UPSTREAM_FIELDS_V2)
    release._validate_upstream(value)
    if value != {"schemaVersion": 2, "app": "dspace", **TARGET}:
        raise PlanError("promotion target is not the reviewed coordinate set")
    return value


def artifact_report(value: dict[str, Any], wanted: dict[str, Any]) -> str:
    exact(value, {"schemaVersion", "image", "chart", "releaseTags"}, "artifact report")
    exact(value["image"], {"tag", "digest", "revisionAnnotation", "platforms"}, "image")
    exact(
        value["chart"],
        {"version", "digest", "archiveDigest", "sourceRevision", "name", "appVersion"},
        "chart",
    )
    exact(value["releaseTags"], {"application", "chart"}, "release tags")
    image = value["image"]
    expected_image_coordinates = {
        "tag": wanted["imageTag"],
        "digest": wanted["imageDigest"],
        "revisionAnnotation": wanted["sourceRevision"],
    }
    expected_chart = {
        "version": wanted["chartVersion"],
        "digest": wanted["chartDigest"],
        "sourceRevision": wanted["chartSourceRevision"],
        "name": "dspace",
        "appVersion": wanted["applicationVersion"],
    }
    if (
        value["schemaVersion"] != 1
        or {key: image[key] for key in expected_image_coordinates}
        != expected_image_coordinates
        or not isinstance(image["platforms"], list)
        or len(image["platforms"]) != 2
        or set(image["platforms"]) != {"linux/amd64", "linux/arm64"}
        or {key: value["chart"][key] for key in expected_chart} != expected_chart
        or not isinstance(value["chart"]["archiveDigest"], str)
        or not release.DIGEST_RE.fullmatch(value["chart"]["archiveDigest"])
    ):
        raise PlanError("artifact provenance does not match the reviewed target")
    if value["releaseTags"] != {
        "application": wanted["semanticTag"],
        "chart": f"chart-v{wanted['chartVersion']}",
    }:
        raise PlanError("release tags do not match the reviewed target")
    return value["chart"]["archiveDigest"]


def source_report(value: dict[str, Any], wanted: dict[str, Any]) -> None:
    exact(
        value,
        {
            "schemaVersion",
            "sourceRevision",
            "privacySafe",
            "rawMetricsIncluded",
            "metricDefinitions",
        },
        "source report",
    )
    if (
        value["schemaVersion"] != 1
        or value["sourceRevision"] != wanted["sourceRevision"]
        or value["privacySafe"] is not True
        or value["rawMetricsIncluded"] is not False
        or not isinstance(value["metricDefinitions"], list)
        or len(value["metricDefinitions"]) != len(FAMILIES)
        or set(value["metricDefinitions"]) != set(FAMILIES)
    ):
        raise PlanError(
            "source report does not prove the privacy-safe required metric definitions"
        )


def classifier_report(value: dict[str, Any]) -> None:
    exact(
        value,
        {
            "schemaVersion",
            "reportType",
            "release",
            "namespace",
            "clusterMutationPerformed",
            "prometheusTargets",
            "publicMetricsStatus",
            "secretContract",
            "metricSamples",
            "classification",
        },
        "classifier report",
    )
    exact(value["prometheusTargets"], {"total", "healthy", "scrapeErrors"}, "targets")
    exact(value["secretContract"], {"exists", "valueRead"}, "secret contract")
    expected_samples = {name: 2 for name in DEFAULT_FAMILIES} | {
        name: 0 for name in FAMILIES
    }
    if (
        value["schemaVersion"] != 1
        or value["reportType"] != "boundedDspaceMetricsClassifier"
        or (value["release"], value["namespace"]) != ("dspace", "dspace")
        or value["clusterMutationPerformed"] is not False
        or value["prometheusTargets"] != {"total": 2, "healthy": 2, "scrapeErrors": 0}
        or value["publicMetricsStatus"] != 401
        or value["secretContract"] != {"exists": True, "valueRead": False}
        or value["metricSamples"] != expected_samples
        or value["classification"] != "IMMUTABLE_APP_LACKS_REQUIRED_DSPACE_METRICS"
    ):
        raise PlanError("classifier report is incomplete, unsafe, or inconsistent")


def failed_reconciliation(path: Path) -> None:
    baseline = release.validate(load(BASELINE_PATH), finalized=True)
    old_target = rollback.chart_maintenance_target(baseline, MAINTENANCE_PATH)
    rollback.failed_reconciliation(path, old_target)


def staging_proof(value: dict[str, Any], wanted: dict[str, Any]) -> None:
    exact(
        value,
        {"schemaVersion", "evidence", "metricsResult", "smokeResult"},
        "staging proof",
    )
    evidence = release.validate(value["evidence"], finalized=True)
    release_fields = set(TARGET)
    coordinates = {key: evidence[key] for key in release_fields}
    runtime = evidence.get("runtimeVerification")
    expected_runtime = {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": wanted["applicationVersion"],
        "runtimeSourceRevision": wanted["sourceRevision"],
        "frontendSourceRevision": wanted["sourceRevision"],
        "defaultProvider": "openai",
        "journeys": [
            {"name": "/build-meta.json", "passed": True},
            {"name": "/", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }
    expected_image_id = "ghcr.io/democratizedspace/dspace@" + wanted["imageDigest"]
    if (
        value["schemaVersion"] != 1
        or evidence["environment"] != "staging"
        or evidence["expectedDefaultChatProvider"] != "openai"
        or coordinates != {key: wanted[key] for key in release_fields}
        or len(evidence["pods"]) != 2
        or any(pod.get("imageID") != expected_image_id for pod in evidence["pods"])
        or runtime != expected_runtime
        or value["metricsResult"]
        != {
            "targets": 2,
            "healthyTargets": 2,
            "scrapeErrors": 0,
            "families": list(FAMILIES),
            "serverObservedJourney": True,
        }
        or value["smokeResult"]
        != {"remoteChat": True, "runtimeFrontendPublicDirectAgreement": True}
    ):
        raise PlanError("staging proof cannot authorize the reviewed target")


def historical_staging_evidence(path: Path, wanted: dict[str, Any]) -> None:
    supplied = release.validate(load(path), finalized=True)
    canonical = release.validate(load(HISTORICAL_STAGING_PATH), finalized=True)
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    supplied_json = json.dumps(supplied, sort_keys=True, separators=(",", ":"))
    if supplied_json != canonical_json:
        raise PlanError(
            "historical staging evidence is not the canonical repository record"
        )
    upstream_fields = set(release.UPSTREAM_FIELDS_V2) - {"schemaVersion", "app"}
    historical_coordinates = {key: supplied[key] for key in upstream_fields}
    reviewed_coordinates = {key: wanted[key] for key in upstream_fields}
    if historical_coordinates == reviewed_coordinates:
        raise PlanError(
            "historical staging evidence unexpectedly matches the reviewed target"
        )


def render(
    chart: Path, wanted: dict[str, Any], archive_digest: str, environment: str
) -> None:
    actual = "sha256:" + hashlib.sha256(chart.read_bytes()).hexdigest()
    if actual != archive_digest:
        raise PlanError("offline chart archive digest mismatch")
    values = [
        ROOT / "docs/examples/dspace.values.dev.yaml",
        ROOT / f"docs/examples/dspace.values.{environment}.yaml",
    ]
    repository = "ghcr.io/democratizedspace/dspace"
    inputs = app_chart.ReleaseInputs(
        app="dspace",
        env=environment,
        release="dspace",
        namespace="dspace",
        chart=str(chart),
        version=wanted["chartVersion"],
        values=tuple(str(item) for item in values),
        tag=wanted["imageTag"],
        pull_policy="Always",
    )
    command = inputs.helm_template_command()
    command += ["--set", f"image.repository={repository}", "--set", "replicaCount=2"]
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        detail = (
            re.sub(r"\s+", " ", completed.stderr).strip().replace(str(ROOT), "<repo>")
        )
        detail = detail[:240] if detail else "no stderr"
        raise PlanError(f"offline Helm render failed: {detail}")
    errors = app_chart.validate_rendered_manifest(completed.stdout, inputs)
    errors += app_chart.validate_dspace_values(completed.stdout, inputs)
    if errors:
        raise PlanError("rendered manifest validation failed: " + "; ".join(errors))
    documents = app_chart.safe_yaml_documents(completed.stdout)
    deployments = [
        doc
        for doc in documents
        if isinstance(doc, dict)
        and doc.get("kind") == "Deployment"
        and app_chart.release_associated(doc, "dspace", allow_name=False)
    ]
    if len(deployments) != 1 or deployments[0].get("spec", {}).get("replicas") != 2:
        raise PlanError("render must contain exactly one two-replica Deployment")
    containers = deployments[0]["spec"]["template"]["spec"]["containers"]
    app = next((item for item in containers if item.get("name") == "dspace"), None)
    if (
        not app
        or app.get("imagePullPolicy") != "Always"
        or app.get("image") != f"{repository}:{wanted['imageTag']}"
    ):
        raise PlanError("rendered image coordinate or pull policy mismatch")


def plan(args: argparse.Namespace) -> dict[str, Any]:
    wanted = target()
    archive_digest = artifact_report(load(args.artifact_report), wanted)
    source_report(load(args.source_report), wanted)
    classifier_report(load(args.classifier_report))
    failed_reconciliation(args.failed_reconciliation)
    historical_staging_evidence(args.historical_staging_evidence, wanted)
    if args.staging_proof:
        staging_proof(load(args.staging_proof), wanted)
    render(args.chart_archive, wanted, archive_digest, "staging")
    render(args.chart_archive, wanted, archive_digest, "prod")
    return {
        "schemaVersion": 1,
        "mode": "read-only-offline-plan",
        "target": wanted,
        "historicalStagingEvidenceAuthorizesTarget": False,
        "freshStagingProofValidated": bool(args.staging_proof),
        "productionProvider": "openai",
        "mutationCommands": [],
        "productionPromotionImplemented": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--artifact-report", type=Path, required=True)
    result.add_argument("--source-report", type=Path, required=True)
    result.add_argument("--classifier-report", type=Path, required=True)
    result.add_argument("--failed-reconciliation", type=Path, required=True)
    result.add_argument("--historical-staging-evidence", type=Path, required=True)
    result.add_argument("--chart-archive", type=Path, required=True)
    result.add_argument("--staging-proof", type=Path)
    return result


def main() -> int:
    try:
        print(json.dumps(plan(parser().parse_args()), indent=2, sort_keys=True))
    except (
        PlanError,
        release.ManifestError,
        rollback.RollbackError,
        OSError,
        KeyError,
        TypeError,
    ) as exc:
        print(f"ERROR: DSPACE promotion plan rejected: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
