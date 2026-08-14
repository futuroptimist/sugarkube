from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "dspace_promotion_plan", ROOT / "scripts/dspace_promotion_plan.py"
)
assert SPEC and SPEC.loader
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)


def artifact() -> dict:
    return {
        "schemaVersion": 1,
        "image": {
            "tag": plan.TARGET["imageTag"],
            "digest": plan.TARGET["imageDigest"],
            "revisionAnnotation": plan.TARGET["sourceRevision"],
            "platforms": ["linux/amd64", "linux/arm64"],
        },
        "chart": {
            "version": plan.TARGET["chartVersion"],
            "digest": plan.TARGET["chartDigest"],
            "sourceRevision": plan.TARGET["chartSourceRevision"],
            "name": "dspace",
            "appVersion": plan.TARGET["applicationVersion"],
        },
        "releaseTags": {"application": "v3.1.1", "chart": "chart-v3.1.2"},
    }


def classifier() -> dict:
    return {
        "schemaVersion": 1,
        "reportType": "boundedDspaceMetricsClassifier",
        "release": "dspace",
        "namespace": "dspace",
        "clusterMutationPerformed": False,
        "prometheusTargets": {"total": 2, "healthy": 2, "scrapeErrors": 0},
        "publicMetricsStatus": 401,
        "secretContract": {"exists": True, "valueRead": False},
        "metricSamples": {name: 2 for name in plan.DEFAULT_FAMILIES}
        | {name: 0 for name in plan.FAMILIES},
        "classification": "IMMUTABLE_APP_LACKS_REQUIRED_DSPACE_METRICS",
    }


def test_reviewed_target_has_exact_schema_and_coordinates():
    assert plan.target() == {"schemaVersion": 2, "app": "dspace", **plan.TARGET}


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("image", "revisionAnnotation"),
        ("image", "digest"),
        ("chart", "sourceRevision"),
        ("chart", "digest"),
    ],
)
def test_artifact_report_rejects_coordinate_changes(section: str, field: str):
    report = artifact()
    report[section][field] = "altered"
    with pytest.raises(plan.PlanError, match="provenance"):
        plan.artifact_report(report, {"schemaVersion": 2, "app": "dspace", **plan.TARGET})


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("prometheusTargets", "healthy"), 1),
        (("prometheusTargets", "scrapeErrors"), 1),
        (("secretContract", "valueRead"), True),
        (("clusterMutationPerformed",), True),
    ],
)
def test_classifier_rejects_unsafe_or_unhealthy_reports(path: tuple[str, ...], value: object):
    report = classifier()
    cursor = report
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(plan.PlanError, match="classifier"):
        plan.classifier_report(report)


def test_classifier_rejects_partial_families_and_secret_value_fields():
    partial = classifier()
    partial["metricSamples"].pop(plan.FAMILIES[0])
    with pytest.raises(plan.PlanError):
        plan.classifier_report(partial)
    leaked = classifier()
    leaked["secretContract"]["value"] = "forbidden"
    with pytest.raises(plan.PlanError, match="schema"):
        plan.classifier_report(leaked)


def test_historical_staging_evidence_cannot_authorize_target():
    old = json.loads(
        (ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json").read_text()
    )
    wrapper = {
        "schemaVersion": 1,
        "evidence": old,
        "metricsResult": {
            "targets": 2,
            "healthyTargets": 2,
            "scrapeErrors": 0,
            "families": list(plan.FAMILIES),
            "serverObservedJourney": True,
        },
        "smokeResult": {"remoteChat": True, "runtimeFrontendPublicDirectAgreement": True},
    }
    with pytest.raises(plan.PlanError, match="cannot authorize"):
        plan.staging_proof(wrapper, {"schemaVersion": 2, "app": "dspace", **plan.TARGET})


def test_synthetic_exact_finalized_staging_proof_is_accepted():
    old = json.loads(
        (ROOT / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json").read_text()
    )
    evidence = copy.deepcopy(old)
    for key, value in plan.TARGET.items():
        evidence[key] = value
    evidence["expectedDefaultChatProvider"] = "openai"
    evidence["runtimeSourceRevision"] = plan.TARGET["sourceRevision"]
    for pod in evidence["pods"]:
        pod["imageID"] = "ghcr.io/democratizedspace/dspace@" + plan.TARGET["imageDigest"]
    proof = evidence["runtimeVerification"]
    proof.update(
        applicationVersion="3.1.1",
        runtimeSourceRevision=plan.TARGET["sourceRevision"],
        frontendSourceRevision=plan.TARGET["sourceRevision"],
        defaultProvider="openai",
    )
    wrapper = {
        "schemaVersion": 1,
        "evidence": evidence,
        "metricsResult": {
            "targets": 2,
            "healthyTargets": 2,
            "scrapeErrors": 0,
            "families": list(plan.FAMILIES),
            "serverObservedJourney": True,
        },
        "smokeResult": {"remoteChat": True, "runtimeFrontendPublicDirectAgreement": True},
    }
    plan.staging_proof(wrapper, {"schemaVersion": 2, "app": "dspace", **plan.TARGET})


def test_offline_render_requires_two_replicas_always_and_rejects_prod_leaks(monkeypatch, tmp_path):
    archive = tmp_path / "dspace.tgz"
    archive.write_bytes(b"offline chart")
    wanted = dict(plan.TARGET)
    wanted["chartDigest"] = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = """
kind: Deployment
metadata: {name: dspace}
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: dspace
          image: ghcr.io/democratizedspace/dspace:main-22f506e
          imagePullPolicy: Always
"""
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, manifest, "")

    monkeypatch.setattr(plan.subprocess, "run", run)
    monkeypatch.setattr(
        plan.app_chart,
        "safe_yaml_documents",
        lambda text: [
            {
                "kind": "Deployment",
                "spec": {
                    "replicas": 2,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "dspace",
                                    "image": "ghcr.io/democratizedspace/dspace:main-22f506e",
                                    "imagePullPolicy": "Always",
                                }
                            ]
                        }
                    },
                },
            }
        ],
    )
    plan.render(archive, wanted, "staging")
    plan.render(archive, wanted, "prod")
    assert all("helm" == command[0] and "template" in command for command in calls)
    assert all("upgrade" not in command and "--reuse-values" not in command for command in calls)
    assert all("image.pullPolicy=Always" in command for command in calls)

    manifest += "\n# staging.token.place\n"
    with pytest.raises(plan.PlanError, match="staging-only"):
        plan.render(archive, wanted, "prod")


def test_render_rejects_secret_objects(monkeypatch, tmp_path):
    archive = tmp_path / "chart"
    archive.write_bytes(b"x")
    wanted = dict(plan.TARGET)
    wanted["chartDigest"] = "sha256:" + hashlib.sha256(b"x").hexdigest()
    monkeypatch.setattr(
        plan.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "kind: Secret\nmetadata: {name: bad}\n", ""
        ),
    )
    monkeypatch.setattr(
        plan.app_chart,
        "safe_yaml_documents",
        lambda text: [{"kind": "Secret", "metadata": {"name": "bad"}}],
    )
    with pytest.raises(plan.PlanError, match="Secret"):
        plan.render(archive, wanted, "prod")


def test_planner_contains_no_mutation_or_finalization_commands():
    source = (ROOT / "scripts/dspace_promotion_plan.py").read_text()
    for forbidden in (
        "helm upgrade",
        "kubectl apply",
        "kubectl delete",
        "kubectl patch",
        "kubectl rollout",
        "create secret",
        "dspace_release_manifest.py finalize",
    ):
        assert forbidden not in source
    recipe = (ROOT / "justfile").read_text()
    recovery = recipe.split("dspace-prod-metrics-pull-policy-recover", 1)[1].split(
        "dspace-release-verify", 1
    )[0]
    assert "--production-metrics-recovery" in recovery
    assert "dspace_promotion_plan" not in recovery
