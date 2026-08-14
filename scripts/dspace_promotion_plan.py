#!/usr/bin/env python3
"""Fail-closed, offline-only planning for the DSPACE 3.1.1 promotion."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts import dspace_manifest_rollback as rollback
from scripts import dspace_release_manifest as release

TARGET = Path("docs/apps/dspace.promotion-target.json")
BASELINE = Path("deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json")
MAINTENANCE = Path("docs/apps/dspace.prod-metrics-chart-target.json")
CHART = "oci://ghcr.io/democratizedspace/charts/dspace"
FAMILIES = (
    "dspace_build_info",
    "dspace_dchat_requests_total",
    "dspace_dependency_requests_total",
    "dspace_http_request_duration_seconds_bucket",
    "dspace_http_requests_total",
    "dspace_instrumentation_up",
)


class PlanError(ValueError):
    """Planning input is incomplete, unsafe, or inconsistent."""


def obj(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read bounded JSON report {path}") from exc
    if not isinstance(value, dict):
        raise PlanError("bounded report must be an object")
    return value


def exact(value: dict[str, Any], fields: set[str], name: str) -> None:
    if set(value) != fields:
        raise PlanError(f"{name} schema fields are not exact")


def target(path: Path = TARGET) -> dict[str, Any]:
    value = obj(path)
    try:
        release.validate(value)
    except release.ManifestError as exc:
        raise PlanError(f"invalid promotion target: {exc}") from exc
    reviewed = obj(TARGET)
    if value != reviewed:
        raise PlanError("promotion target differs from the reviewed coordinates")
    if value["imageTag"] != f"main-{value['sourceRevision'][:7]}":
        raise PlanError("deployment coordinate must be the immutable branch image tag")
    return value


def artifact_report(value: dict[str, Any], selected: dict[str, Any]) -> None:
    fields = {
        "schemaVersion",
        "applicationVersion",
        "sourceRevision",
        "imageTag",
        "imageDigest",
        "imagePlatforms",
        "imageSourceRevision",
        "chartVersion",
        "chartDigest",
        "chartSourceRevision",
        "chartAppVersion",
        "applicationReleaseTag",
        "chartTag",
    }
    exact(value, fields, "artifact provenance report")
    expected = {
        key: selected[key]
        for key in (
            "applicationVersion",
            "sourceRevision",
            "imageTag",
            "imageDigest",
            "chartVersion",
            "chartDigest",
            "chartSourceRevision",
        )
    }
    expected.update(
        {
            "schemaVersion": 1,
            "imagePlatforms": ["linux/amd64", "linux/arm64"],
            "imageSourceRevision": selected["sourceRevision"],
            "chartAppVersion": selected["applicationVersion"],
            "applicationReleaseTag": selected["semanticTag"],
            "chartTag": f"chart-v{selected['chartVersion']}",
        }
    )
    if value != expected:
        raise PlanError("artifact provenance does not match every reviewed coordinate")


def source_report(value: dict[str, Any], selected: dict[str, Any]) -> None:
    exact(
        value,
        {"schemaVersion", "sourceRevision", "privacySafe", "metricDefinitions"},
        "source report",
    )
    definitions = value.get("metricDefinitions")
    if (
        value.get("schemaVersion") != 1
        or value.get("sourceRevision") != selected["sourceRevision"]
        or value.get("privacySafe") is not True
        or not isinstance(definitions, dict)
        or set(definitions) != set(FAMILIES)
        or any(flag is not True for flag in definitions.values())
    ):
        raise PlanError("source report does not prove all privacy-safe metric definitions")


def classifier(value: dict[str, Any]) -> None:
    fields = {
        "schemaVersion",
        "classification",
        "healthyTargets",
        "scrapeErrors",
        "publicMetricsStatus",
        "secretContractExists",
        "defaultMetricSamples",
        "requiredFamilySamples",
        "clusterMutationPerformed",
    }
    exact(value, fields, "classifier report")
    samples = value.get("requiredFamilySamples")
    defaults = value.get("defaultMetricSamples")
    if (
        value.get("schemaVersion") != 1
        or value.get("classification") != "IMMUTABLE_APP_LACKS_REQUIRED_DSPACE_METRICS"
        or value.get("healthyTargets") != 2
        or value.get("scrapeErrors") != []
        or value.get("publicMetricsStatus") != 401
        or value.get("secretContractExists") is not True
        or value.get("clusterMutationPerformed") is not False
        or not isinstance(defaults, dict)
        or not defaults
        or any(count != 2 for count in defaults.values())
        or not isinstance(samples, dict)
        or set(samples) != set(FAMILIES)
        or any(count != 0 for count in samples.values())
    ):
        raise PlanError("classifier report is incomplete, unsafe, or inconsistent")


def failed(path: Path) -> None:
    baseline = release.validate(release._object(BASELINE), True)
    maintenance = rollback.chart_maintenance_target(baseline, MAINTENANCE)
    try:
        rollback.failed_reconciliation(path, maintenance)
    except (rollback.RollbackError, release.ManifestError) as exc:
        raise PlanError(f"failed reconciliation is not the preserved incident: {exc}") from exc


def staging_evidence(value: dict[str, Any], selected: dict[str, Any]) -> None:
    coordinates = (
        "applicationVersion",
        "sourceRevision",
        "chartSourceRevision",
        "imageTag",
        "imageDigest",
        "chartVersion",
        "chartDigest",
        "semanticTag",
    )
    if value.get("environment") != "staging" or any(
        value.get(k) != selected[k] for k in coordinates
    ):
        raise PlanError("historical staging evidence cannot authorize these coordinates")
    standard = dict(value)
    standard["verificationResults"] = [
        item
        for item in value.get("verificationResults", [])
        if isinstance(item, dict)
        and item.get("check") not in {"prometheusTargets", "applicationMetrics"}
    ]
    try:
        release.validate(standard, True)
    except release.ManifestError as exc:
        raise PlanError(f"staging evidence is not finalized: {exc}") from exc
    if value.get("expectedDefaultChatProvider") != "openai":
        raise PlanError("staging evidence must prove the intended openai provider")
    runtime = value.get("runtimeVerification", {})
    if (
        any(
            runtime.get(k) != selected[v]
            for k, v in (
                ("applicationVersion", "applicationVersion"),
                ("runtimeSourceRevision", "sourceRevision"),
                ("frontendSourceRevision", "sourceRevision"),
            )
        )
        or runtime.get("defaultProvider") != "openai"
    ):
        raise PlanError("staging runtime and frontend identity do not match")
    journeys = {
        item.get("name"): item.get("passed")
        for item in runtime.get("journeys", [])
        if isinstance(item, dict)
    }
    checks = {
        item.get("check"): item.get("passed")
        for item in value.get("verificationResults", [])
        if isinstance(item, dict)
    }
    if (
        journeys.get("/chat") is not True
        or checks.get("remoteChatSmoke") is not True
        or checks.get("prometheusTargets") is not True
        or checks.get("applicationMetrics") is not True
    ):
        raise PlanError("staging smoke and metrics results are mandatory")


def render(helm: str, selected: dict[str, Any], environment: str) -> str:
    values = [
        "docs/examples/dspace.values.dev.yaml",
        f"docs/examples/dspace.values.{environment}.yaml",
    ]
    command = [
        helm,
        "template",
        "dspace",
        f"{CHART}@{selected['chartDigest']}",
        "--namespace",
        "dspace",
    ]
    for path in values:
        command.extend(["-f", path])
    command.extend(
        [
            "--set-string",
            f"image.repository={release.IMAGE_REF}",
            "--set-string",
            f"image.tag={selected['imageTag']}",
            "--set",
            "image.pullPolicy=Always",
            "--set",
            "replicaCount=2",
        ]
    )
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise PlanError(f"offline Helm render failed for {environment}: {result.stderr.strip()}")
    output = result.stdout
    if re.search(r"(?m)^kind:\s*Secret\s*$", output):
        raise PlanError("rendered Secret resources are forbidden")
    if (
        selected["imageTag"] not in output
        or "imagePullPolicy: Always" not in output
        or not re.search(r"(?m)^\s*replicas:\s*2\s*$", output)
    ):
        raise PlanError("render does not pin the exact image, Always policy, and two replicas")
    if environment == "prod" and (
        "staging.democratized.space" in output
        or "staging.token.place" in output
        or "sugarkube-int" in output
    ):
        raise PlanError("production render contains staging-only configuration")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--artifact-report", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--classifier-report", type=Path, required=True)
    parser.add_argument("--failed-reconciliation", type=Path, required=True)
    parser.add_argument("--staging-evidence", type=Path)
    parser.add_argument("--helm-command", default="helm")
    args = parser.parse_args(argv)
    selected = target(args.target)
    artifact_report(obj(args.artifact_report), selected)
    source_report(obj(args.source_report), selected)
    classifier(obj(args.classifier_report))
    failed(args.failed_reconciliation)
    if args.staging_evidence:
        staging_evidence(obj(args.staging_evidence), selected)
    renders = {env: render(args.helm_command, selected, env) for env in ("staging", "prod")}
    plan = {
        "schemaVersion": 1,
        "operation": "dspacePromotionPreparation",
        "mutationPerformed": False,
        "target": selected,
        "stagingEvidenceStatus": "exact-finalized" if args.staging_evidence else "required",
        "renders": {
            env: {"sha256": __import__("hashlib").sha256(text.encode()).hexdigest()}
            for env, text in renders.items()
        },
        "nextAction": "obtain genuine approval and create an exact fresh staging candidate",
    }
    print(json.dumps(plan, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
