#!/usr/bin/env python3
"""Fail-closed, read-only planning for the DSPACE 3.1.1 promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from scripts import app_chart
from scripts import dspace_release_manifest as release

TARGET = Path("docs/apps/dspace.promotion-target.json")
FAMILIES = (
    "dspace_build_info",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "dspace_http_request_duration_seconds_bucket",
    "dspace_http_requests_total",
    "dspace_instrumentation_up",
)
CLASSIFIER_FIELDS = {
    "schemaVersion",
    "classification",
    "healthyTargets",
    "targetScrapeErrors",
    "publicMetricsStatus",
    "secretContractExists",
    "secretValueRead",
    "defaultNodeMetricSampleCounts",
    "applicationFamilySampleCounts",
    "clusterMutationPerformed",
    "rawMetricsIncluded",
}
SOURCE_FIELDS = {
    "schemaVersion",
    "sourceRevision",
    "metricFamilies",
    "privacySafe",
    "clusterMutationPerformed",
    "rawSourceIncluded",
}


class PlanError(ValueError):
    """A planning input is unsafe, incomplete, or not the reviewed target."""


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read bounded report: {path}") from exc
    if not isinstance(value, dict):
        raise PlanError("bounded report must be an object")
    return value


def target(path: Path = TARGET) -> dict[str, Any]:
    value = load(path)
    release._exact_fields(value, release.UPSTREAM_FIELDS_V2)
    release._validate_upstream(value)
    expected = load(TARGET) if path != TARGET else value
    if value != expected:
        raise PlanError("promotion coordinates differ from the reviewed target")
    return value


def validate_classifier(value: dict[str, Any]) -> None:
    if set(value) != CLASSIFIER_FIELDS:
        raise PlanError("classifier report fields are incomplete or unsafe")
    expected_counts = {name: 0 for name in FAMILIES}
    if (
        value["schemaVersion"] != 1
        or value["classification"] != "IMMUTABLE_APP_LACKS_REQUIRED_DSPACE_METRICS"
        or value["healthyTargets"] != 2
        or value["targetScrapeErrors"] != 0
        or value["publicMetricsStatus"] != 401
        or value["secretContractExists"] is not True
        or value["secretValueRead"] is not False
        or value["clusterMutationPerformed"] is not False
        or value["rawMetricsIncluded"] is not False
        or value["applicationFamilySampleCounts"] != expected_counts
        or not isinstance(value["defaultNodeMetricSampleCounts"], dict)
        or not value["defaultNodeMetricSampleCounts"]
        or any(count != 2 for count in value["defaultNodeMetricSampleCounts"].values())
    ):
        raise PlanError("classifier report does not prove the bounded incident classification")


def validate_source(value: dict[str, Any], promotion: dict[str, Any]) -> None:
    if set(value) != SOURCE_FIELDS:
        raise PlanError("source report fields are incomplete or unsafe")
    if (
        value["schemaVersion"] != 1
        or value["sourceRevision"] != promotion["sourceRevision"]
        or value["metricFamilies"] != list(FAMILIES)
        or value["privacySafe"] is not True
        or value["clusterMutationPerformed"] is not False
        or value["rawSourceIncluded"] is not False
    ):
        raise PlanError("source report does not prove the reviewed privacy-safe metric definitions")


def validate_failed(value: dict[str, Any]) -> None:
    required = {
        "schemaVersion": 1,
        "environment": "prod",
        "release": "dspace",
        "namespace": "dspace",
        "operation": "dspaceProductionMetricsReconciliation",
        "state": "failed",
        "failedStage": "ownership-and-finalization-proof",
        "failureCode": "ownership-and-finalization-proof-failed",
        "clusterMayHaveChanged": True,
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise PlanError("preserved reconciliation is not the immutable failed operation")
    before = value.get("before")
    if not isinstance(before, dict) or before.get("helmRevision") != 9:
        raise PlanError("preserved reconciliation has an invalid before-state")


def validate_staging(evidence: dict[str, Any], promotion: dict[str, Any]) -> None:
    metrics_results = [
        item
        for item in evidence.get("verificationResults", [])
        if isinstance(item, dict) and item.get("check") == "metrics"
    ]
    lifecycle = dict(evidence)
    lifecycle["verificationResults"] = [
        item
        for item in evidence.get("verificationResults", [])
        if not isinstance(item, dict) or item.get("check") != "metrics"
    ]
    try:
        release.validate(lifecycle, True)
    except release.ManifestError as exc:
        raise PlanError(f"staging evidence is invalid: {exc}") from exc
    fields = release.UPSTREAM_FIELDS_V2
    if any(evidence[field] != promotion[field] for field in fields):
        raise PlanError("historical staging evidence cannot authorize these coordinates")
    if evidence["environment"] != "staging" or evidence["expectedDefaultChatProvider"] != "openai":
        raise PlanError("staging evidence must prove the intended production provider openai")
    checks = {item["check"]: item["passed"] for item in lifecycle["verificationResults"]}
    if (
        len(metrics_results) != 1
        or metrics_results[0].get("passed") is not True
        or any(checks.get(name) is not True for name in release.RUNTIME_VERIFICATION_CHECKS)
    ):
        raise PlanError("staging evidence lacks runtime, smoke, or metrics success")


def render(
    chart: Path,
    promotion: dict[str, Any],
    environment: str,
    runner: Callable[[list[str]], str] | None = None,
) -> str:
    digest = "sha256:" + hashlib.sha256(chart.read_bytes()).hexdigest()
    if digest != promotion["chartDigest"]:
        raise PlanError("chart archive digest differs from reviewed immutable digest")
    values = Path(f"docs/examples/dspace.values.{environment}.yaml")
    command = [
        "helm",
        "template",
        "dspace",
        str(chart),
        "--namespace",
        "dspace",
        "-f",
        str(values),
        "--set",
        "replicaCount=2",
        "--set",
        f"image.repository={release.IMAGE_REF}",
        "--set",
        f"image.tag={promotion['imageTag']}",
        "--set",
        "image.pullPolicy=Always",
    ]
    if "--reuse-values" in command:
        raise PlanError("--reuse-values is forbidden")
    output = (
        runner(command)
        if runner
        else subprocess.run(command, check=True, text=True, capture_output=True).stdout
    )
    docs = [doc for doc in app_chart.safe_yaml_documents(output) if isinstance(doc, dict)]
    if any(doc.get("kind") == "Secret" for doc in docs):
        raise PlanError("rendered Secret resources are forbidden")
    if environment == "prod" and release.contains_staging_reference(docs):
        raise PlanError("production render contains staging-only configuration")
    inputs = app_chart.ReleaseInputs(
        app="dspace",
        env=environment,
        release="dspace",
        namespace="dspace",
        chart=str(chart),
        version=promotion["chartVersion"],
        values=(str(values),),
        tag=promotion["imageTag"],
        host="democratized.space" if environment == "prod" else "staging.democratized.space",
    )
    errors = app_chart.validate_rendered_manifest(output, inputs)
    if errors:
        raise PlanError("render validation failed: " + "; ".join(errors))
    return output


def plan(args: argparse.Namespace) -> dict[str, Any]:
    promotion = target(args.target)
    validate_classifier(load(args.classifier))
    validate_source(load(args.source), promotion)
    validate_failed(load(args.failed_reconciliation))
    validate_staging(load(args.staging_evidence), promotion)
    release.preflight(
        release.candidate(promotion, "staging", "openai", args.approved_at, args.approved_by),
        release.IMAGE_REF,
        release.CHART_REF,
        args.oras_command,
    )
    render(args.chart_archive, promotion, "staging")
    render(args.chart_archive, promotion, "prod")
    return {
        "schemaVersion": 1,
        "mode": "plan",
        "mutationPerformed": False,
        "target": promotion,
        "renders": ["staging", "prod"],
        "authorization": "future-operator-action-required",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--classifier", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--failed-reconciliation", type=Path, required=True)
    parser.add_argument("--staging-evidence", type=Path, required=True)
    parser.add_argument("--chart-archive", type=Path, required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--oras-command", default="oras")
    args = parser.parse_args(argv)
    print(json.dumps(plan(args), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
