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
ARCHIVE_DIGEST = "sha256:cb35bcb01eeb668771fe6670fed64f7b79bb56e5f927910abc5362ec46a4879f"


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
            "archiveDigest": ARCHIVE_DIGEST,
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
    reviewed = plan.target()
    assert reviewed == {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
    assert set(reviewed) == set(plan.release.UPSTREAM_FIELDS_V2)


def test_reviewed_target_rejects_archive_digest_extension(monkeypatch, tmp_path):
    extended = {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
    extended["chartArchiveDigest"] = ARCHIVE_DIGEST
    path = tmp_path / "target.json"
    path.write_text(json.dumps(extended))
    monkeypatch.setattr(plan, "TARGET_PATH", path)
    with pytest.raises(plan.release.ManifestError, match="fields"):
        plan.target()


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("image", "tag"),
        ("image", "digest"),
        ("image", "revisionAnnotation"),
        ("chart", "name"),
        ("chart", "version"),
        ("chart", "digest"),
        ("chart", "archiveDigest"),
        ("chart", "sourceRevision"),
        ("chart", "appVersion"),
        ("releaseTags", "application"),
        ("releaseTags", "chart"),
    ],
)
def test_artifact_report_rejects_coordinate_changes(section: str, field: str):
    report = artifact()
    report[section][field] = "altered"
    with pytest.raises(plan.PlanError):
        plan.artifact_report(
            report, {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
        )


def test_artifact_report_accepts_platform_order_and_derives_release_tags():
    report = artifact()
    report["image"]["platforms"].reverse()
    wanted = {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
    wanted["semanticTag"] = "release-3.1.1"
    report["releaseTags"]["application"] = wanted["semanticTag"]
    assert plan.artifact_report(report, wanted) == ARCHIVE_DIGEST


def test_artifact_archive_digest_is_independent_of_oci_manifest_digest():
    report = artifact()
    report["chart"]["archiveDigest"] = "sha256:" + "a" * 64
    wanted = {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
    assert report["chart"]["archiveDigest"] != wanted["chartDigest"]
    assert plan.artifact_report(report, wanted) == report["chart"]["archiveDigest"]


@pytest.mark.parametrize("archive_digest", [None, "SHA256:" + "a" * 64, "sha256:abc"])
def test_artifact_report_rejects_missing_or_malformed_archive_digest(archive_digest):
    report = artifact()
    if archive_digest is None:
        del report["chart"]["archiveDigest"]
    else:
        report["chart"]["archiveDigest"] = archive_digest
    with pytest.raises(plan.PlanError):
        plan.artifact_report(
            report, {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
        )


def test_artifact_report_rejects_duplicate_platforms():
    report = artifact()
    report["image"]["platforms"] = ["linux/amd64", "linux/amd64"]
    with pytest.raises(plan.PlanError, match="provenance"):
        plan.artifact_report(
            report, {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
        )


def test_source_report_accepts_definition_order_but_rejects_duplicates():
    report = {
        "schemaVersion": 1,
        "sourceRevision": plan.TARGET["sourceRevision"],
        "privacySafe": True,
        "rawMetricsIncluded": False,
        "metricDefinitions": list(reversed(plan.FAMILIES)),
    }
    wanted = {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
    plan.source_report(report, wanted)
    report["metricDefinitions"][0] = report["metricDefinitions"][1]
    with pytest.raises(plan.PlanError, match="source report"):
        plan.source_report(report, wanted)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("prometheusTargets", "healthy"), 1),
        (("prometheusTargets", "scrapeErrors"), 1),
        (("secretContract", "valueRead"), True),
        (("clusterMutationPerformed",), True),
    ],
)
def test_classifier_rejects_unsafe_or_unhealthy_reports(
    path: tuple[str, ...], value: object
):
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
        (
            ROOT
            / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
        ).read_text()
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
        "smokeResult": {
            "remoteChat": True,
            "runtimeFrontendPublicDirectAgreement": True,
        },
    }
    with pytest.raises(plan.PlanError, match="cannot authorize"):
        plan.staging_proof(
            wrapper, {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
        )


def test_synthetic_exact_finalized_staging_proof_is_accepted():
    old = json.loads(
        (
            ROOT
            / "deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json"
        ).read_text()
    )
    evidence = copy.deepcopy(old)
    for key, value in plan.TARGET.items():
        evidence[key] = value
    evidence["expectedDefaultChatProvider"] = "openai"
    evidence["runtimeSourceRevision"] = plan.TARGET["sourceRevision"]
    for pod in evidence["pods"]:
        pod["imageID"] = (
            "ghcr.io/democratizedspace/dspace@" + plan.TARGET["imageDigest"]
        )
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
        "smokeResult": {
            "remoteChat": True,
            "runtimeFrontendPublicDirectAgreement": True,
        },
    }
    plan.staging_proof(wrapper, {"schemaVersion": 2, "app": "dspace", **plan.TARGET})


def test_offline_render_requires_two_replicas_always_and_rejects_prod_leaks(
    monkeypatch, tmp_path
):
    archive = tmp_path / "dspace.tgz"
    archive.write_bytes(b"offline chart")
    wanted = dict(plan.TARGET)
    archive_digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
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
    validated = []
    monkeypatch.setattr(
        plan.app_chart,
        "validate_rendered_manifest",
        lambda text, inputs: validated.append(inputs) or [],
    )
    monkeypatch.setattr(
        plan.app_chart, "validate_dspace_values", lambda text, inputs: []
    )
    monkeypatch.setattr(
        plan.app_chart,
        "safe_yaml_documents",
        lambda text: [
            {
                "kind": "Deployment",
                "metadata": {"labels": {"app.kubernetes.io/instance": "dspace"}},
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
    plan.render(archive, wanted, archive_digest, "staging")
    plan.render(archive, wanted, archive_digest, "prod")
    assert all("helm" == command[0] and "template" in command for command in calls)
    assert all(
        "upgrade" not in command and "--reuse-values" not in command
        for command in calls
    )
    assert all("image.pullPolicy=Always" in command for command in calls)
    assert all(
        "image.repository=ghcr.io/democratizedspace/dspace" in command
        for command in calls
    )
    assert all("replicaCount=2" in command for command in calls)
    assert [(item.env, item.values) for item in validated] == [
        (
            "staging",
            (
                str(plan.ROOT / "docs/examples/dspace.values.dev.yaml"),
                str(plan.ROOT / "docs/examples/dspace.values.staging.yaml"),
            ),
        ),
        (
            "prod",
            (
                str(plan.ROOT / "docs/examples/dspace.values.dev.yaml"),
                str(plan.ROOT / "docs/examples/dspace.values.prod.yaml"),
            ),
        ),
    ]


def test_render_rejects_secret_objects(monkeypatch, tmp_path):
    archive = tmp_path / "chart"
    archive.write_bytes(b"x")
    wanted = dict(plan.TARGET)
    archive_digest = "sha256:" + hashlib.sha256(b"x").hexdigest()
    monkeypatch.setattr(
        plan.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "kind: Secret\nmetadata: {name: bad}\n", ""
        ),
    )
    monkeypatch.setattr(
        plan.app_chart,
        "validate_rendered_manifest",
        lambda text, inputs: ["DSPACE rendered Secret bad"],
    )
    monkeypatch.setattr(
        plan.app_chart, "validate_dspace_values", lambda text, inputs: []
    )
    with pytest.raises(plan.PlanError, match="Secret"):
        plan.render(archive, wanted, archive_digest, "prod")


def test_render_failure_includes_sanitized_helm_stderr(monkeypatch, tmp_path):
    archive = tmp_path / "chart"
    archive.write_bytes(b"x")
    wanted = dict(plan.TARGET)
    archive_digest = "sha256:" + hashlib.sha256(b"x").hexdigest()
    monkeypatch.setattr(
        plan.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, "", f"Error: template failed in {plan.ROOT}/charts/bad.yaml\n"
        ),
    )
    with pytest.raises(plan.PlanError, match=r"<repo>/charts/bad.yaml"):
        plan.render(archive, wanted, archive_digest, "prod")


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


def source_report_fixture() -> dict:
    return {
        "schemaVersion": 1,
        "sourceRevision": plan.TARGET["sourceRevision"],
        "privacySafe": True,
        "rawMetricsIncluded": False,
        "metricDefinitions": list(plan.FAMILIES),
    }


def staging_fixture() -> dict:
    old = json.loads(plan.HISTORICAL_STAGING_PATH.read_text())
    evidence = copy.deepcopy(old)
    for key in set(plan.TARGET):
        evidence[key] = plan.TARGET[key]
    evidence["expectedDefaultChatProvider"] = "openai"
    evidence["runtimeSourceRevision"] = plan.TARGET["sourceRevision"]
    for pod in evidence["pods"]:
        pod["imageID"] = (
            "ghcr.io/democratizedspace/dspace@" + plan.TARGET["imageDigest"]
        )
    evidence["runtimeVerification"] = {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": plan.TARGET["applicationVersion"],
        "runtimeSourceRevision": plan.TARGET["sourceRevision"],
        "frontendSourceRevision": plan.TARGET["sourceRevision"],
        "defaultProvider": "openai",
        "journeys": [
            {"name": "/build-meta.json", "passed": True},
            {"name": "/", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }
    return {
        "schemaVersion": 1,
        "evidence": evidence,
        "metricsResult": {
            "targets": 2,
            "healthyTargets": 2,
            "scrapeErrors": 0,
            "families": list(plan.FAMILIES),
            "serverObservedJourney": True,
        },
        "smokeResult": {
            "remoteChat": True,
            "runtimeFrontendPublicDirectAgreement": True,
        },
    }


@pytest.mark.parametrize(
    ("operation",),
    [
        (lambda report: report.update(sourceRevision="wrong"),),
        (lambda report: report.update(privacySafe=False),),
        (lambda report: report["metricDefinitions"].pop(),),
        (lambda report: report["metricDefinitions"].append("extra_family"),),
        (lambda report: report.update(rawMetricsIncluded=True),),
        (lambda report: report.update(rawPayload={}),),
        (lambda report: report.update(unknown=True),),
    ],
)
def test_source_report_rejects_every_unsafe_or_drifted_field(operation):
    report = source_report_fixture()
    operation(report)
    with pytest.raises(plan.PlanError):
        plan.source_report(report, {"schemaVersion": 2, "app": "dspace", **plan.TARGET})


@pytest.mark.parametrize(
    ("operation",),
    [
        (lambda report: report["prometheusTargets"].update(total=3),),
        (lambda report: report["prometheusTargets"].update(healthy=1),),
        (lambda report: report["prometheusTargets"].update(scrapeErrors=1),),
        (lambda report: report.update(publicMetricsStatus=200),),
        (lambda report: report["secretContract"].update(exists=False),),
        (lambda report: report["secretContract"].update(valueRead=True),),
        (lambda report: report["metricSamples"].pop(plan.FAMILIES[0]),),
        (lambda report: report["metricSamples"].update(extra=0),),
        (lambda report: report["metricSamples"].update({plan.FAMILIES[0]: 1}),),
        (lambda report: report["secretContract"].update(value="raw"),),
        (lambda report: report.update(rawPayload={}),),
        (lambda report: report.update(clusterMutationPerformed=True),),
    ],
)
def test_classifier_rejects_each_contract_violation(operation):
    report = classifier()
    operation(report)
    with pytest.raises(plan.PlanError):
        plan.classifier_report(report)


def _leaf_paths(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaf_paths(item, prefix + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaf_paths(item, prefix + (index,))
    else:
        yield prefix


@pytest.mark.parametrize(
    "path", _leaf_paths(json.loads(plan.HISTORICAL_STAGING_PATH.read_text()))
)
def test_historical_evidence_rejects_any_changed_field(path, tmp_path):
    record = json.loads(plan.HISTORICAL_STAGING_PATH.read_text())
    cursor = record
    for component in path[:-1]:
        cursor = cursor[component]
    leaf = path[-1]
    cursor[leaf] = None
    supplied = tmp_path / "historical.json"
    supplied.write_text(json.dumps(record))
    with pytest.raises((plan.PlanError, plan.release.ManifestError)):
        plan.historical_staging_evidence(
            supplied, {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
        )


def test_historical_evidence_is_final_exact_and_has_different_full_coordinates():
    plan.historical_staging_evidence(
        plan.HISTORICAL_STAGING_PATH,
        {"schemaVersion": 2, "app": "dspace", **plan.TARGET},
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("evidence", "applicationVersion"), "3.1.2"),
        (("evidence", "sourceRevision"), "f" * 40),
        (("evidence", "chartSourceRevision"), "f" * 40),
        (("evidence", "imageTag"), "main-fffffff"),
        (("evidence", "imageDigest"), "sha256:" + "f" * 64),
        (("evidence", "chartVersion"), "3.1.3"),
        (("evidence", "chartDigest"), "sha256:" + "f" * 64),
        (("evidence", "semanticTag"), "v3.1.2"),
        (
            ("evidence", "pods", 0, "imageID"),
            "ghcr.io/democratizedspace/dspace@sha256:" + "f" * 64,
        ),
        (("evidence", "pods"), []),
        (("evidence", "expectedDefaultChatProvider"), "token-place"),
        (("evidence", "runtimeVerification", "runtimeSourceRevision"), "f" * 40),
        (("evidence", "runtimeVerification", "frontendSourceRevision"), "f" * 40),
        (("evidence", "runtimeVerification", "defaultProvider"), "token-place"),
        (("evidence", "runtimeVerification", "journeys", 2, "passed"), False),
        (("metricsResult", "targets"), 1),
        (("metricsResult", "families"), ["dspace_build_info"]),
        (("metricsResult", "serverObservedJourney"), False),
        (("smokeResult", "remoteChat"), False),
        (("smokeResult", "runtimeFrontendPublicDirectAgreement"), False),
    ],
)
def test_fresh_staging_proof_rejects_each_independent_drift(path, value):
    proof = staging_fixture()
    cursor = proof
    for component in path[:-1]:
        cursor = cursor[component]
    cursor[path[-1]] = value
    with pytest.raises((plan.PlanError, plan.release.ManifestError)):
        plan.staging_proof(proof, {"schemaVersion": 2, "app": "dspace", **plan.TARGET})


@pytest.mark.parametrize(
    "error",
    [
        "exact requested image tag",
        "production rendered staging-only metrics configuration",
        "production values do not match the authenticated metrics contract",
        "DSPACE rendered Secret forbidden",
    ],
)
def test_render_fails_on_structural_helper_drift(monkeypatch, tmp_path, error):
    archive = tmp_path / "chart"
    archive.write_bytes(b"chart")
    wanted = dict(plan.TARGET)
    archive_digest = "sha256:" + hashlib.sha256(b"chart").hexdigest()
    monkeypatch.setattr(
        plan.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "manifest", ""),
    )
    monkeypatch.setattr(
        plan.app_chart, "validate_rendered_manifest", lambda *_: [error]
    )
    monkeypatch.setattr(plan.app_chart, "validate_dspace_values", lambda *_: [])
    with pytest.raises(plan.PlanError, match="validation failed"):
        plan.render(archive, wanted, archive_digest, "prod")


def test_plan_end_to_end_is_two_templates_and_sanitized(monkeypatch, tmp_path):
    paths = {}
    for name, value in {
        "artifact_report": artifact(),
        "source_report": source_report_fixture(),
        "classifier_report": classifier(),
        "staging_proof": staging_fixture(),
    }.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(value))
    paths["failed_reconciliation"] = tmp_path / "failed.json"
    paths["failed_reconciliation"].write_text("{}")
    paths["historical_staging_evidence"] = plan.HISTORICAL_STAGING_PATH
    archive = tmp_path / "chart"
    archive.write_bytes(b"chart")
    wanted = {"schemaVersion": 2, "app": "dspace", **plan.TARGET}
    archive_digest = "sha256:" + hashlib.sha256(b"chart").hexdigest()
    artifact_value = json.loads(paths["artifact_report"].read_text())
    artifact_value["chart"]["archiveDigest"] = archive_digest
    paths["artifact_report"].write_text(json.dumps(artifact_value))
    monkeypatch.setattr(plan, "target", lambda: wanted)
    monkeypatch.setattr(plan, "failed_reconciliation", lambda path: None)
    monkeypatch.setattr(plan.app_chart, "validate_rendered_manifest", lambda *_: [])
    monkeypatch.setattr(plan.app_chart, "validate_dspace_values", lambda *_: [])
    documents = [
        {
            "kind": "Deployment",
            "metadata": {"labels": {"app.kubernetes.io/instance": "dspace"}},
            "spec": {
                "replicas": 2,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "dspace",
                                "image": f"ghcr.io/democratizedspace/dspace:{wanted['imageTag']}",
                                "imagePullPolicy": "Always",
                            }
                        ]
                    }
                },
            },
        }
    ]
    monkeypatch.setattr(plan.app_chart, "safe_yaml_documents", lambda _: documents)
    calls = []
    monkeypatch.setattr(
        plan.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append(command) or subprocess.CompletedProcess(command, 0, "safe", "")
        ),
    )
    args = type("Args", (), {**paths, "chart_archive": archive})()
    result = plan.plan(args)
    output = json.dumps(result)
    assert len(calls) == 2
    assert all(call[:2] == ["helm", "template"] for call in calls)
    assert "rawMetricsIncluded" not in output
    assert "metricSamples" not in output
    assert result["mutationCommands"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image", "wrong.example/dspace:main-22f506e"),
        ("image", "ghcr.io/democratizedspace/dspace:v3.1.1"),
        ("imagePullPolicy", "IfNotPresent"),
        ("replicas", 1),
    ],
)
def test_render_rejects_wrong_repository_semantic_tag_pull_policy_or_replicas(
    monkeypatch, tmp_path, field, value
):
    archive = tmp_path / "chart"
    archive.write_bytes(b"chart")
    wanted = dict(plan.TARGET)
    archive_digest = "sha256:" + hashlib.sha256(b"chart").hexdigest()
    deployment = {
        "kind": "Deployment",
        "metadata": {"labels": {"app.kubernetes.io/instance": "dspace"}},
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
    if field == "replicas":
        deployment["spec"]["replicas"] = value
    else:
        deployment["spec"]["template"]["spec"]["containers"][0][field] = value
    monkeypatch.setattr(
        plan.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "manifest", ""),
    )
    monkeypatch.setattr(plan.app_chart, "validate_rendered_manifest", lambda *_: [])
    monkeypatch.setattr(plan.app_chart, "validate_dspace_values", lambda *_: [])
    monkeypatch.setattr(plan.app_chart, "safe_yaml_documents", lambda _: [deployment])
    with pytest.raises(plan.PlanError):
        plan.render(archive, wanted, archive_digest, "staging")
