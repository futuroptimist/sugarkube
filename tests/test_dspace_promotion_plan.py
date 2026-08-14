"""Preparation-only DSPACE 3.1.1 promotion policy tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import dspace_promotion_plan as plan


def reviewed() -> dict[str, object]:
    return json.loads(plan.TARGET.read_text(encoding="utf-8"))


def test_reviewed_target_has_exact_coordinates_and_separate_revisions() -> None:
    assert reviewed() == {
        "schemaVersion": 2,
        "app": "dspace",
        "applicationVersion": "3.1.1",
        "sourceRevision": "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2",
        "chartSourceRevision": "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2",
        "imageTag": "main-22f506e",
        "imageDigest": "sha256:467890df969cc7938cb760f965fd8f90a8912b1dcb1f8425bc808216b7e1512b",
        "chartVersion": "3.1.2",
        "chartDigest": "sha256:544a3e31ab827e6d2bf28754a19d8af17b0402b75159c2a40c1b3dfe5eb60161",
        "semanticTag": "v3.1.1",
    }
    assert Path("docs/apps/dspace.staging.version").read_text().splitlines()[-1] == "3.1.2"


@pytest.mark.parametrize(
    "field",
    [
        "sourceRevision",
        "imageTag",
        "imageDigest",
        "chartSourceRevision",
        "chartVersion",
        "chartDigest",
    ],
)
def test_altered_reviewed_coordinate_is_rejected(tmp_path: Path, field: str) -> None:
    changed = reviewed()
    changed[field] = "changed"
    path = tmp_path / "target.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(plan.PlanError):
        plan.target(path)


def classifier() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "classification": "IMMUTABLE_APP_LACKS_REQUIRED_DSPACE_METRICS",
        "healthyTargets": 2,
        "scrapeErrors": [],
        "publicMetricsStatus": 401,
        "secretContractExists": True,
        "defaultMetricSamples": {"process_cpu_user_seconds_total": 2},
        "requiredFamilySamples": {family: 0 for family in plan.FAMILIES},
        "clusterMutationPerformed": False,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x["requiredFamilySamples"].pop(plan.FAMILIES[0]),
        lambda x: x.update(healthyTargets=1),
        lambda x: x.update(scrapeErrors=["timeout"]),
        lambda x: x.update(secretValue="forbidden"),
        lambda x: x.update(clusterMutationPerformed=True),
    ],
)
def test_classifier_is_strict_and_never_accepts_secret_values(mutation) -> None:
    value = classifier()
    mutation(value)
    with pytest.raises(plan.PlanError):
        plan.classifier(value)


def test_historical_staging_evidence_cannot_authorize_successor() -> None:
    old = json.loads(
        Path("deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json").read_text()
    )
    with pytest.raises(plan.PlanError, match="historical"):
        plan.staging_evidence(old, reviewed())


def test_exact_synthetic_final_staging_evidence_is_accepted() -> None:
    value = json.loads(
        Path("deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json").read_text()
    )
    selected = reviewed()
    for key in (
        "applicationVersion",
        "sourceRevision",
        "chartSourceRevision",
        "imageTag",
        "imageDigest",
        "chartVersion",
        "chartDigest",
        "semanticTag",
    ):
        value[key] = selected[key]
    value["expectedDefaultChatProvider"] = "openai"
    value["runtimeSourceRevision"] = selected["sourceRevision"]
    for pod in value["pods"]:
        pod["imageID"] = f"ghcr.io/democratizedspace/dspace@{selected['imageDigest']}"
    runtime = value["runtimeVerification"]
    runtime.update(
        applicationVersion="3.1.1",
        runtimeSourceRevision=selected["sourceRevision"],
        frontendSourceRevision=selected["sourceRevision"],
        defaultProvider="openai",
    )
    for check in value["verificationResults"]:
        if check["check"] in {"defaultProvider", "remoteChatSmoke"}:
            check["passed"] = True
    value["verificationResults"].extend(
        [
            {
                "check": "prometheusTargets",
                "passed": True,
                "details": "exactly two healthy authenticated targets; no scrape errors",
            },
            {
                "check": "applicationMetrics",
                "passed": True,
                "details": "all six required families including server-observed journeys",
            },
        ]
    )
    plan.staging_evidence(value, selected)
    for path, wrong in (("expectedDefaultChatProvider", "token-place"),):
        changed = copy.deepcopy(value)
        changed[path] = wrong
        with pytest.raises(plan.PlanError):
            plan.staging_evidence(changed, selected)


def fake_helm(tmp_path: Path, body: str) -> Path:
    command = tmp_path / "helm"
    command.write_text("#!/bin/sh\nprintf '%b\\n' " + repr(body) + "\n", encoding="utf-8")
    command.chmod(0o755)
    return command


def test_offline_render_is_exact_and_contains_no_mutation_command(tmp_path: Path) -> None:
    body = "kind: Deployment\nspec:\n  replicas: 2\n  template:\n    spec:\n      containers:\n      - image: ghcr.io/democratizedspace/dspace:main-22f506e\n        imagePullPolicy: Always\n"
    output = plan.render(str(fake_helm(tmp_path, body)), reviewed(), "prod")
    assert "replicas: 2" in output
    source = Path("scripts/dspace_promotion_plan.py").read_text(encoding="utf-8")
    for forbidden in (
        "helm upgrade",
        "kubectl apply",
        "kubectl delete",
        "kubectl patch",
        "rollout restart",
    ):
        assert forbidden not in source
    assert 'sub.add_parser("finalize")' not in source


@pytest.mark.parametrize("unsafe", ["kind: Secret\n", "staging.token.place\n"])
def test_production_render_rejects_secret_and_staging_data(tmp_path: Path, unsafe: str) -> None:
    body = (
        "kind: Deployment\nspec:\n  replicas: 2\nimage: main-22f506e\nimagePullPolicy: Always\n"
        + unsafe
    )
    with pytest.raises(plan.PlanError):
        plan.render(str(fake_helm(tmp_path, body)), reviewed(), "prod")


def test_old_pull_policy_recovery_remains_fail_closed() -> None:
    source = Path("scripts/dspace_manifest_rollback.py").read_text(encoding="utf-8")
    assert "runtime-and-metrics-preflight" in source
    assert "recovery runtime preflight" in source
    assert "live values have drift beyond the sole recoverable pull policy" in source
