"""Preparation-only DSPACE promotion planner policy tests."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts import dspace_promotion_plan as planner


def reviewed():
    return json.loads(Path("docs/apps/dspace.promotion-target.json").read_text())


def classifier():
    return {
        "schemaVersion": 1,
        "classification": "IMMUTABLE_APP_LACKS_REQUIRED_DSPACE_METRICS",
        "healthyTargets": 2,
        "targetScrapeErrors": 0,
        "publicMetricsStatus": 401,
        "secretContractExists": True,
        "secretValueRead": False,
        "defaultNodeMetricSampleCounts": {"process_cpu_seconds_total": 2},
        "applicationFamilySampleCounts": {name: 0 for name in planner.FAMILIES},
        "clusterMutationPerformed": False,
        "rawMetricsIncluded": False,
    }


def successor_evidence():
    value = json.loads(
        Path("deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json").read_text()
    )
    target = reviewed()
    for field in planner.release.UPSTREAM_FIELDS_V2:
        value[field] = target[field]
    value["expectedDefaultChatProvider"] = "openai"
    value["runtimeSourceRevision"] = target["sourceRevision"]
    for pod in value["pods"]:
        pod["imageID"] = "docker-pullable://dspace@" + target["imageDigest"]
    proof = value["runtimeVerification"]
    proof.update(
        applicationVersion=target["applicationVersion"],
        runtimeSourceRevision=target["sourceRevision"],
        frontendSourceRevision=target["sourceRevision"],
        defaultProvider="openai",
    )
    value["verificationResults"].append(
        {"check": "metrics", "passed": True, "details": "six bounded families passed"}
    )
    return value


def test_reviewed_target_is_exact_and_staging_pin_only_advanced():
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
    assert planner.target() == reviewed()
    assert Path("docs/apps/dspace.staging.version").read_text().splitlines()[-1] == "3.1.2"


@pytest.mark.parametrize(
    "field", ["sourceRevision", "imageTag", "imageDigest", "chartVersion", "chartDigest"]
)
def test_altered_target_is_rejected(tmp_path, field):
    value = reviewed()
    value[field] = "altered"
    path = tmp_path / "target.json"
    path.write_text(json.dumps(value))
    with pytest.raises((planner.PlanError, planner.release.ManifestError)):
        planner.target(path)


def test_historical_310_evidence_is_explicitly_ineligible():
    old = json.loads(
        Path("deployment-evidence/dspace/staging/main-018687f-20260805T035722Z.json").read_text()
    )
    with pytest.raises(planner.PlanError, match="historical"):
        planner.validate_staging(old, reviewed())


def test_exact_synthetic_successor_evidence_is_accepted_and_every_coordinate_is_bound():
    planner.validate_staging(successor_evidence(), reviewed())
    for field in (*planner.release.UPSTREAM_FIELDS_V2, "expectedDefaultChatProvider"):
        altered = successor_evidence()
        altered[field] = "token-place" if field == "expectedDefaultChatProvider" else "wrong"
        with pytest.raises((planner.PlanError, planner.release.ManifestError)):
            planner.validate_staging(altered, reviewed())


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x["applicationFamilySampleCounts"].pop(planner.FAMILIES[0]),
        lambda x: x.update(healthyTargets=1),
        lambda x: x.update(targetScrapeErrors=1),
        lambda x: x.update(secretValue="forbidden"),
        lambda x: x.update(secretValueRead=True),
        lambda x: x.update(clusterMutationPerformed=True),
        lambda x: x.update(rawMetricsIncluded=True),
    ],
)
def test_classifier_is_strict_bounded_and_read_only(change):
    value = classifier()
    change(value)
    with pytest.raises(planner.PlanError):
        planner.validate_classifier(value)


def test_source_report_requires_all_privacy_safe_definitions():
    report = {
        "schemaVersion": 1,
        "sourceRevision": reviewed()["sourceRevision"],
        "metricFamilies": list(planner.FAMILIES),
        "privacySafe": True,
        "clusterMutationPerformed": False,
        "rawSourceIncluded": False,
    }
    planner.validate_source(report, reviewed())
    report["metricFamilies"].pop()
    with pytest.raises(planner.PlanError):
        planner.validate_source(report, reviewed())


def test_offline_render_is_exact_read_only_and_rejects_secret_or_staging_leak(tmp_path):
    chart = tmp_path / "dspace.tgz"
    chart.write_bytes(b"fixture")
    target = reviewed()
    target["chartDigest"] = "sha256:" + hashlib.sha256(chart.read_bytes()).hexdigest()
    rendered = """apiVersion: apps/v1
kind: Deployment
metadata: {name: dspace, labels: {app.kubernetes.io/instance: dspace}}
spec:
  replicas: 2
  selector: {matchLabels: {app: dspace}}
  template:
    metadata: {labels: {app: dspace}}
    spec:
      containers:
      - name: dspace
        image: ghcr.io/democratizedspace/dspace:main-22f506e
        imagePullPolicy: Always
---
apiVersion: v1
kind: Service
metadata: {name: dspace, labels: {app.kubernetes.io/instance: dspace}}
spec: {selector: {app: dspace}, ports: [{port: 80}]}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: dspace, labels: {app.kubernetes.io/instance: dspace}}
spec: {rules: [{host: staging.democratized.space}]}
"""
    commands = []
    planner.render(chart, target, "staging", lambda command: commands.append(command) or rendered)
    joined = " ".join(commands[0])
    assert "replicaCount=2" in joined and "image.pullPolicy=Always" in joined
    assert "--reuse-values" not in joined
    assert not any(word in joined for word in ("upgrade", "kubectl", "rollout", "finalize"))
    with pytest.raises(planner.PlanError, match="Secret"):
        planner.render(chart, target, "staging", lambda _: rendered + "---\nkind: Secret\n")
    prod = rendered.replace("staging.democratized.space", "democratized.space")
    with pytest.raises(planner.PlanError, match="staging-only"):
        planner.render(
            chart,
            target,
            "prod",
            lambda _: prod + "---\nkind: ConfigMap\ndata: {x: sugarkube-int}\n",
        )


def test_planner_source_contains_no_mutation_or_evidence_finalization_path():
    source = Path("scripts/dspace_promotion_plan.py").read_text()
    for forbidden in (
        "helm upgrade",
        "kubectl apply",
        "kubectl delete",
        "kubectl patch",
        "rollout restart",
        "release.finalize",
    ):
        assert forbidden not in source
