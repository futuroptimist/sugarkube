#!/usr/bin/env python3
"""Fail-closed, offline-only planning for the DSPACE 3.1.1 promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import app_chart
import dspace_manifest_rollback as rollback
import dspace_release_manifest as release

ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = ROOT / "docs/apps/dspace.promotion-target.json"
BASELINE_PATH = ROOT / "deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json"
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


def artifact_report(value: dict[str, Any], wanted: dict[str, Any]) -> None:
    exact(value, {"schemaVersion", "image", "chart", "releaseTags"}, "artifact report")
    exact(value["image"], {"tag", "digest", "revisionAnnotation", "platforms"}, "image")
    exact(value["chart"], {"version", "digest", "sourceRevision", "name", "appVersion"}, "chart")
    exact(value["releaseTags"], {"application", "chart"}, "release tags")
    expected_image = {
        "tag": wanted["imageTag"],
        "digest": wanted["imageDigest"],
        "revisionAnnotation": wanted["sourceRevision"],
        "platforms": ["linux/amd64", "linux/arm64"],
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
        or value["image"] != expected_image
        or value["chart"] != expected_chart
    ):
        raise PlanError("artifact provenance does not match the reviewed target")
    if value["releaseTags"] != {"application": "v3.1.1", "chart": "chart-v3.1.2"}:
        raise PlanError("release tags do not match the reviewed target")


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
        or value["metricDefinitions"] != list(FAMILIES)
    ):
        raise PlanError("source report does not prove the privacy-safe required metric definitions")


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
    expected_samples = {name: 2 for name in DEFAULT_FAMILIES} | {name: 0 for name in FAMILIES}
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
    exact(value, {"schemaVersion", "evidence", "metricsResult", "smokeResult"}, "staging proof")
    evidence = release.validate(value["evidence"], finalized=True)
    coordinates = {key: evidence[key] for key in TARGET}
    if (
        value["schemaVersion"] != 1
        or evidence["environment"] != "staging"
        or evidence["expectedDefaultChatProvider"] != "openai"
        or coordinates != {key: wanted[key] for key in TARGET}
        or len(evidence["pods"]) != 2
        or "runtimeVerification" not in evidence
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


def render(chart: Path, wanted: dict[str, Any], environment: str) -> None:
    actual = "sha256:" + hashlib.sha256(chart.read_bytes()).hexdigest()
    if actual != wanted["chartDigest"]:
        raise PlanError("offline chart archive digest mismatch")
    values = [
        ROOT / "docs/examples/dspace.values.dev.yaml",
        ROOT / f"docs/examples/dspace.values.{environment}.yaml",
    ]
    command = ["helm", "template", "dspace", str(chart), "--namespace", "dspace"]
    for item in values:
        command += ["-f", str(item)]
    command += [
        "--set",
        f"image.tag={wanted['imageTag']}",
        "--set",
        "image.pullPolicy=Always",
        "--set",
        "replicaCount=2",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise PlanError("offline Helm render failed")
    documents = app_chart.safe_yaml_documents(completed.stdout)
    if any(isinstance(doc, dict) and doc.get("kind") == "Secret" for doc in documents):
        raise PlanError("rendered Secret resources are forbidden")
    deployments = [
        doc for doc in documents if isinstance(doc, dict) and doc.get("kind") == "Deployment"
    ]
    if len(deployments) != 1 or deployments[0].get("spec", {}).get("replicas") != 2:
        raise PlanError("render must contain exactly one two-replica Deployment")
    containers = deployments[0]["spec"]["template"]["spec"]["containers"]
    app = next((item for item in containers if item.get("name") == "dspace"), None)
    if (
        not app
        or app.get("imagePullPolicy") != "Always"
        or not app.get("image", "").endswith(":" + wanted["imageTag"])
    ):
        raise PlanError("rendered image coordinate or pull policy mismatch")
    text = completed.stdout
    if environment == "prod" and (
        "staging.token.place" in text
        or "dspace-staging-metrics-token" in text
        or "sugarkube-int" in text
    ):
        raise PlanError("staging-only configuration rendered in production")


def plan(args: argparse.Namespace) -> dict[str, Any]:
    wanted = target()
    artifact_report(load(args.artifact_report), wanted)
    source_report(load(args.source_report), wanted)
    classifier_report(load(args.classifier_report))
    failed_reconciliation(args.failed_reconciliation)
    historical = release.validate(load(args.historical_staging_evidence), finalized=True)
    if (
        historical["environment"] != "staging"
        or historical["applicationVersion"] != "3.1.0"
        or historical["chartVersion"] != "3.1.1"
    ):
        raise PlanError("historical staging evidence is not the preserved 3.1.0/3.1.1 record")
    if args.staging_proof:
        staging_proof(load(args.staging_proof), wanted)
    render(args.chart_archive, wanted, "staging")
    render(args.chart_archive, wanted, "prod")
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
