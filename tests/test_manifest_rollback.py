"""Focused fail-closed tests for DSPACE manifest rollback."""

from __future__ import annotations

import copy
import hashlib
import json
from argparse import Namespace
from pathlib import Path
from typing import Callable

import pytest

from scripts import dspace_manifest_rollback as rollback
from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
PROD_BASELINE = Path("deployment-evidence/dspace/prod/main-1a31a56-20260801T093443Z.json")
PROD_MAINTENANCE_TARGET = Path("docs/apps/dspace.prod-metrics-chart-target.json")


def test_failed_reconciliation_accepts_only_exact_authorized_incident(tmp_path: Path) -> None:
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    selected = rollback.chart_maintenance_target(baseline, PROD_MAINTENANCE_TARGET)
    evidence = {
        "schemaVersion": rollback.SCHEMA_VERSION,
        "environment": "prod",
        "release": "dspace",
        "namespace": "dspace",
        "operation": "dspaceProductionMetricsReconciliation",
        "state": "failed",
        "failedStage": "ownership-and-finalization-proof",
        "failureCode": "ownership-and-finalization-proof-failed",
        "clusterMayHaveChanged": True,
        "invocationId": "a" * 32,
        "targetManifestFingerprint": hashlib.sha256(
            manifest._canonical(selected).encode()
        ).hexdigest(),
        "before": {"helmRevision": 9, "chartName": "dspace", "chartVersion": "3.0.2"},
        "target": {
            field: selected[field]
            for field in (
                "applicationVersion",
                "sourceRevision",
                "imageTag",
                "imageDigest",
                "chartSourceRevision",
                "chartVersion",
                "chartDigest",
                "expectedDefaultChatProvider",
            )
        },
    }
    path = tmp_path / "failed.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert rollback.failed_reconciliation(path, selected)["invocationId"] == "a" * 32

    for field, wrong in (
        ("schemaVersion", 2),
        ("environment", "staging"),
        ("release", "other"),
        ("namespace", "other"),
        ("operation", "other"),
        ("state", "succeeded"),
        ("failedStage", "runtime-verification"),
        ("failureCode", "runtime-verification-failed"),
        ("invocationId", "wrong"),
        ("clusterMayHaveChanged", False),
    ):
        path.write_text(json.dumps({**evidence, field: wrong}), encoding="utf-8")
        with pytest.raises(rollback.RollbackError):
            rollback.failed_reconciliation(path, selected)

    changed = json.loads(json.dumps(evidence))
    changed["before"]["helmRevision"] = 10
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(rollback.RollbackError, match="revision 9"):
        rollback.failed_reconciliation(path, selected)

    for target_change in ("missing", "extra"):
        changed = json.loads(json.dumps(evidence))
        if target_change == "missing":
            changed["target"].pop("imageDigest")
        else:
            changed["target"]["ignored"] = "must-not-be-accepted"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(rollback.RollbackError, match="reviewed target"):
            rollback.failed_reconciliation(path, selected)


def target(environment: str = "staging", schema_version: int = 1) -> dict[str, object]:
    value = {
        "schemaVersion": schema_version,
        "app": "dspace",
        "applicationVersion": "3.2.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.0",
        "chartDigest": "sha256:" + "2" * 64,
        "semanticTag": "v3.2.0",
        "recordType": "final",
        "environment": environment,
        "expectedDefaultChatProvider": "token-place",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": "test-approver",
        "helmRevision": 7,
        "pods": [
            {
                "name": "dspace-old",
                "startTime": "2026-07-26T12:01:00Z",
                "imageID": f"{manifest.IMAGE_REF}@{DIGEST}",
            }
        ],
        "runtimeSourceRevision": SHA,
        "runtimeSourceRevisionMethod": manifest.RUNTIME_METHOD,
        "verificationResults": [],
    }
    if schema_version == 2:
        value["chartSourceRevision"] = "1234567890abcdef1234567890abcdef12345678"
    checks = sorted(manifest.required_final_checks(value)) + ["imagePlatformSourceRevision[0]"]
    value["verificationResults"] = [
        {"check": check, "passed": True, "details": "observed"} for check in checks
    ]
    return manifest.validate(value, True)


def test_chart_pin_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    pin = tmp_path / "dspace.prod.version"
    pin.write_text(
        "# application remains at 3.0.1\n\n  3.0.3  # reviewed chart\n", encoding="utf-8"
    )

    assert rollback.chart_pin(pin) == "3.0.3"


def test_chart_pin_failure_is_redacted(tmp_path: Path) -> None:
    missing = tmp_path / "sensitive" / "dspace.prod.version"

    with pytest.raises(rollback.RollbackError, match="unreadable or invalid") as error:
        rollback.chart_pin(missing)

    assert str(missing) not in str(error.value)


def test_chart_maintenance_target_preserves_application_and_changes_only_chart() -> None:
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    selected = rollback.chart_maintenance_target(baseline, PROD_MAINTENANCE_TARGET)

    changed = {field for field in baseline if baseline[field] != selected[field]}
    assert changed == {"chartSourceRevision", "chartVersion", "chartDigest"}
    assert selected["chartVersion"] == "3.0.3"
    assert selected["chartDigest"] == (
        "sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c"
    )


@pytest.mark.parametrize("drift", ("applicationVersion", "unknown"))
def test_chart_maintenance_target_rejects_drift_and_unknown_fields(
    tmp_path: Path, drift: str
) -> None:
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    reviewed = manifest._object(PROD_MAINTENANCE_TARGET)
    reviewed[drift] = "unexpected"
    path = tmp_path / "target.json"
    path.write_text(json.dumps(reviewed), encoding="utf-8")

    with pytest.raises(rollback.RollbackError, match="application or image|schema mismatch"):
        rollback.chart_maintenance_target(baseline, path)


def test_chart_maintenance_target_rejects_matching_but_unapproved_application(
    tmp_path: Path,
) -> None:
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    reviewed = manifest._object(PROD_MAINTENANCE_TARGET)
    baseline["applicationVersion"] = reviewed["applicationVersion"] = "3.0.0"
    baseline["semanticTag"] = reviewed["semanticTag"] = "v3.0.0"
    path = tmp_path / "target.json"
    path.write_text(json.dumps(reviewed), encoding="utf-8")

    with pytest.raises(rollback.RollbackError, match="approved application tuple"):
        rollback.chart_maintenance_target(baseline, path)


def test_chart_maintenance_target_rejects_unapproved_baseline_tuple() -> None:
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    baseline["chartVersion"] = "3.0.1"

    with pytest.raises(rollback.RollbackError, match="approved finalized production chart tuple"):
        rollback.chart_maintenance_target(baseline, PROD_MAINTENANCE_TARGET)


@pytest.mark.parametrize(
    ("contents", "message"),
    (
        ("not JSON", "chart maintenance target is invalid"),
        (
            json.dumps(
                {
                    **manifest._object(PROD_MAINTENANCE_TARGET),
                    "schemaVersion": 1,
                }
            ),
            "schema 2 for dspace",
        ),
    ),
)
def test_chart_maintenance_target_rejects_invalid_records(
    tmp_path: Path, contents: str, message: str
) -> None:
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    path = tmp_path / "maintenance-target.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(rollback.RollbackError, match=message):
        rollback.chart_maintenance_target(baseline, path)


@pytest.mark.parametrize("field", ("chartSourceRevision", "chartDigest"))
def test_chart_maintenance_target_drift_fails_before_reservation_or_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.manifest.write_text(PROD_BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    reviewed = manifest._object(PROD_MAINTENANCE_TARGET)
    reviewed[field] = "sha256:" + "0" * 64 if field == "chartDigest" else "0" * 40
    maintenance_target = tmp_path / "maintenance-target.json"
    maintenance_target.write_text(json.dumps(reviewed), encoding="utf-8")
    args.configuration_reconciliation = True
    args.maintenance_target = maintenance_target
    staged = tmp_path / "staged"
    staged.mkdir()

    with pytest.raises(rollback.RollbackError, match="reviewed production chart tuple"):
        rollback._rollback(args, lambda command: commands.append(command) or "", staged)

    assert not evidence.exists()
    assert commands == []


def test_configuration_reconciliation_rejects_mismatched_production_pin_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.manifest.write_text(PROD_BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    version_file = tmp_path / "dspace.prod.version"
    version_file.write_text("3.0.2\n", encoding="utf-8")
    monkeypatch.setattr(
        rollback.app_config,
        "load_config",
        lambda *_args: {
            "SUGARKUBE_CHART": f"oci://{manifest.CHART_REF}",
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VERSION_FILE": version_file.name,
        },
    )
    args.configuration_reconciliation = True
    args.maintenance_target = PROD_MAINTENANCE_TARGET
    staged = tmp_path / "staged"
    staged.mkdir()

    with pytest.raises(rollback.RollbackError, match="production chart pin differs"):
        rollback._rollback(args, lambda command: commands.append(command) or "", staged)

    assert not evidence.exists()
    assert commands == []


def test_schema_v2_final_target_projects_split_provenance_for_rollback() -> None:
    validated = target(schema_version=2)
    projected = {field: validated[field] for field in manifest.candidate_fields(validated)}
    projected["recordType"] = "candidate"

    assert manifest.validate(projected, False)["chartSourceRevision"] != projected["sourceRevision"]


def verifier_result(**changes: object) -> dict[str, object]:
    value = {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": "3.2.0",
        "runtimeSourceRevision": SHA,
        "frontendSourceRevision": SHA,
        "defaultProvider": "token-place",
        "journeys": [{"name": "/"}, {"name": "/chat"}],
    }
    value["journeys"] = [{"name": item["name"], "passed": True} for item in value["journeys"]]
    value.update(changes)
    return value


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"runtimeSourceRevision": "0" * 40}, "runtimeSourceRevision"),
        ({"frontendSourceRevision": "0" * 40}, "frontendSourceRevision"),
        ({"defaultProvider": "openai"}, "defaultProvider"),
        ({"journeys": [{"name": "/chat", "passed": False}]}, "failed public journey"),
        ({"journeys": [{"name": "/", "passed": True}]}, "required /chat"),
        ({"secret": "must-not-be-accepted"}, "schema mismatch"),
    ],
)
def test_verifier_result_fails_closed(changes: dict[str, object], message: str) -> None:
    with pytest.raises(rollback.RollbackError, match=message):
        rollback.validate_verifier_result(verifier_result(**changes), target(), "staging")


def test_verifier_result_accepts_exact_identity_and_journeys() -> None:
    assert rollback.validate_verifier_result(verifier_result(), target(), "staging")["journeys"][
        1
    ] == {
        "name": "/chat",
        "passed": True,
    }


def test_verifier_schema_version_rejects_boolean() -> None:
    with pytest.raises(rollback.RollbackError, match="schemaVersion"):
        rollback.validate_verifier_result(verifier_result(schemaVersion=True), target(), "staging")


def test_capability_probe_is_argv_only_and_exact(tmp_path: Path) -> None:
    executable = tmp_path / "verifier"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    calls = []

    def runner(command: list[str]) -> str:
        calls.append(command)
        return json.dumps(
            {
                "schemaVersion": 1,
                "environment": "staging",
                "release": "dspace",
                "namespace": "dspace",
                "capabilities": list(rollback.REQUIRED_CAPABILITIES),
            }
        )

    rollback.verifier_capabilities(executable, "staging", "dspace", "dspace", runner)
    assert calls == [
        [
            str(executable),
            "capabilities",
            "--environment",
            "staging",
            "--release",
            "dspace",
            "--namespace",
            "dspace",
        ]
    ]


def test_missing_or_incompatible_verifier_fails(tmp_path: Path) -> None:
    with pytest.raises(rollback.RollbackError, match="existing executable"):
        rollback.verifier_capabilities(tmp_path / "missing", "staging", "dspace", "dspace")
    executable = tmp_path / "verifier"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    with pytest.raises(rollback.RollbackError, match="incompatible"):
        rollback.verifier_capabilities(
            executable,
            "staging",
            "dspace",
            "dspace",
            lambda _command: json.dumps(
                {
                    "schemaVersion": 1,
                    "environment": "staging",
                    "release": "dspace",
                    "namespace": "dspace",
                    "capabilities": ["health"],
                }
            ),
        )


def test_production_confirmation_is_bound_to_full_target_sha() -> None:
    for invalid in ("", "yes", "dspace:prod:deadbee", f"dspace:staging:{SHA}"):
        with pytest.raises(rollback.RollbackError, match="exactly equal"):
            rollback.confirmation("prod", invalid, target("prod"))
    rollback.confirmation("prod", f"dspace:prod:{SHA}", target("prod"))
    rollback.confirmation("staging", "", target())


def test_configuration_baselines_accept_only_canonical_repository_omission() -> None:
    image = {"tag": "main-abcdef0", "pullPolicy": "Always"}
    desired = {"replicaCount": 2, "image": {**image, "repository": manifest.IMAGE_REF}}

    omitted, expected = rollback.configuration_comparison_baselines(
        {"replicaCount": 2, "image": image}, desired
    )
    explicit, _ = rollback.configuration_comparison_baselines(desired, desired)

    assert omitted == expected == explicit
    assert "repository" not in image


@pytest.mark.parametrize(
    ("live_image", "desired_repository", "extra_live_value"),
    [
        (
            {
                "repository": "example.invalid/dspace",
                "tag": "main-abcdef0",
                "pullPolicy": "Always",
            },
            manifest.IMAGE_REF,
            None,
        ),
        ({"tag": "main-abcdef0", "pullPolicy": "Always"}, manifest.IMAGE_REF, True),
        ("not-a-mapping", manifest.IMAGE_REF, None),
        ({"tag": "main-abcdef0", "pullPolicy": "Always"}, None, None),
        ({"tag": "main-abcdef0", "pullPolicy": "Always"}, "", None),
        ({"tag": "main-abcdef0", "pullPolicy": "Always"}, "example.invalid/dspace", None),
    ],
)
def test_configuration_baselines_keep_all_other_drift_fail_closed(
    live_image: object, desired_repository: object, extra_live_value: object
) -> None:
    live = {"image": live_image}
    if extra_live_value is not None:
        live["unrelated"] = extra_live_value
    desired = {
        "image": {
            "repository": desired_repository,
            "tag": "main-abcdef0",
            "pullPolicy": "Always",
        }
    }

    with pytest.raises(rollback.RollbackError, match="unrelated Helm values drift"):
        live_baseline, desired_baseline = rollback.configuration_comparison_baselines(live, desired)
        if live_baseline != desired_baseline:
            raise rollback.RollbackError(
                "unrelated Helm values drift blocks configuration reconciliation"
            )


def test_missing_or_candidate_target_fails_before_any_external_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = []
    monkeypatch.setattr(rollback, "run", lambda command: called.append(command) or "")
    common = [
        "--environment",
        "staging",
        "--evidence",
        str(tmp_path / "rollback.json"),
        "--verifier",
        str(tmp_path / "verifier"),
    ]
    assert rollback.main(["--manifest", str(tmp_path / "missing.json"), *common]) == 2
    candidate = {field: target()[field] for field in manifest.CANDIDATE_FIELDS}
    candidate["recordType"] = "candidate"
    source = tmp_path / "candidate.json"
    source.write_text(manifest._canonical(candidate), encoding="utf-8")
    assert rollback.main(["--manifest", str(source), *common]) == 2
    assert called == []
    assert not (tmp_path / "rollback.json").exists()


@pytest.mark.parametrize(
    "coordinates",
    (
        ("--manifest", "baseline.json", "--configuration-reconciliation"),
        ("--baseline-manifest", "baseline.json"),
        ("--manifest", "baseline.json", "--maintenance-target", "target.json"),
    ),
)
def test_main_rejects_mixed_or_incomplete_maintenance_coordinates(
    tmp_path: Path, coordinates: tuple[str, ...]
) -> None:
    common = (
        "--environment",
        "prod",
        "--evidence",
        str(tmp_path / "evidence.json"),
        "--verifier",
        str(tmp_path / "verifier"),
    )

    with pytest.raises(SystemExit, match="2"):
        rollback.main([*coordinates, *common])


def test_main_forwards_complete_maintenance_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = tmp_path / "baseline.json"
    maintenance_target = tmp_path / "target.json"
    captured: list[Namespace] = []
    monkeypatch.setattr(rollback, "rollback", lambda args: captured.append(args) or {})

    result = rollback.main(
        [
            "--baseline-manifest",
            str(baseline),
            "--maintenance-target",
            str(maintenance_target),
            "--configuration-reconciliation",
            "--environment",
            "prod",
            "--evidence",
            str(tmp_path / "evidence.json"),
            "--verifier",
            str(tmp_path / "verifier"),
        ]
    )

    assert result == 0
    assert len(captured) == 1
    assert captured[0].manifest == baseline
    assert captured[0].maintenance_target == maintenance_target


@pytest.mark.parametrize(
    "mismatch",
    ("image digest", "chart digest", "chart source revision", "image platform revision"),
)
def test_oci_preflight_mismatch_is_controlled_before_reservation_or_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mismatch: str,
) -> None:
    manifest_path = tmp_path / "target.json"
    evidence_path = tmp_path / "rollback.json"
    verifier = tmp_path / "verifier"
    values = tmp_path / "values.yaml"
    manifest_path.write_text(manifest._canonical(target()), encoding="utf-8")
    verifier.write_text("#!/bin/sh\n", encoding="utf-8")
    verifier.chmod(0o755)
    values.write_text("staging: true\n", encoding="utf-8")
    monkeypatch.setattr(
        rollback.app_config,
        "load_config",
        lambda *_args: {
            "SUGARKUBE_CHART": f"oci://{manifest.CHART_REF}",
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VALUES": str(values),
        },
    )
    monkeypatch.setattr(rollback, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rollback, "cluster_environment", lambda *_args: "staging")
    monkeypatch.setattr(rollback, "verifier_capabilities", lambda *_args: {})
    monkeypatch.setattr(
        rollback,
        "helm_status",
        lambda *_args: {
            "name": "dspace",
            "namespace": "dspace",
            "version": 7,
            "info": {"status": "deployed"},
            "chart": {"metadata": {"name": "dspace", "version": "3.1.0"}},
        },
    )
    monkeypatch.setattr(rollback, "pods", lambda *_args, **_kwargs: [])
    sentinel = "TOP-SECRET-oci-output"
    monkeypatch.setattr(
        rollback.release,
        "preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            manifest.ManifestError(f"{mismatch}: {sentinel}")
        ),
    )
    commands: list[list[str]] = []

    def runner(command: list[str]) -> str:
        commands.append(command)
        return "rendered"

    original_rollback = rollback.rollback
    monkeypatch.setattr(rollback, "rollback", lambda args: original_rollback(args, runner))
    status = rollback.main(
        [
            "--environment",
            "staging",
            "--manifest",
            str(manifest_path),
            "--evidence",
            str(evidence_path),
            "--verifier",
            str(verifier),
        ]
    )

    assert status == 2
    stderr = capsys.readouterr().err
    assert stderr == "error: OCI preflight validation failed\n"
    assert sentinel not in stderr
    assert not evidence_path.exists()
    assert not any("upgrade" in command or "rollout" in command for command in commands)


def test_values_chain_is_ordered_hashed_and_never_contains_contents(tmp_path: Path) -> None:
    first = tmp_path / "base.yaml"
    second = tmp_path / "prod.yaml"
    first.write_text("privateSetting: do-not-log\n", encoding="utf-8")
    second.write_text("provider: token-place\n", encoding="utf-8")
    paths, proof = rollback.values_evidence({"SUGARKUBE_VALUES": "base.yaml,prod.yaml"}, tmp_path)
    assert paths == [first, second]
    assert [item["path"] for item in proof] == ["base.yaml", "prod.yaml"]
    assert "do-not-log" not in json.dumps(proof)
    with pytest.raises(rollback.RollbackError, match="missing or unreadable"):
        rollback.values_evidence({"SUGARKUBE_VALUES": "missing.yaml"}, tmp_path)


def pod(uid: str, *, digest: str = DIGEST, terminating: bool = False) -> dict[str, object]:
    return {
        "name": f"dspace-{uid}",
        "uid": uid,
        "startTime": f"2026-07-27T12:00:0{uid[-1]}Z",
        "phase": "Running",
        "ready": True,
        "terminating": terminating,
        "images": {"dspace": f"{manifest.IMAGE_REF}:main-abcdef0@{DIGEST}"},
        "imageIDs": {"dspace": f"{manifest.IMAGE_REF}@{digest}"},
        "ownerReferences": [],
    }


def test_post_pod_proof_rejects_unchanged_lingering_and_digest_mismatch() -> None:
    before = [pod("1")]
    with pytest.raises(rollback.RollbackError, match="replacement"):
        rollback.verify_post_pods(before, before, target(), True)
    with pytest.raises(rollback.RollbackError, match="terminating"):
        rollback.verify_post_pods([pod("2", terminating=True)], before, target(), True)
    with pytest.raises(rollback.RollbackError, match="resolved image ID"):
        rollback.verify_post_pods([pod("2", digest="sha256:" + "9" * 64)], before, target(), True)
    rollback.verify_post_pods([pod("2")], before, target(), True)


def test_post_pod_proof_ignores_regular_sidecars() -> None:
    after = pod("2")
    after["images"]["metrics"] = "example.invalid/metrics:1"
    after["imageIDs"]["metrics"] = "example.invalid/metrics@sha256:" + "9" * 64
    # pods() filters these before proof, mirroring release finalization's named container contract.
    after["images"] = {"dspace": after["images"]["dspace"]}
    after["imageIDs"] = {"dspace": after["imageIDs"]["dspace"]}
    rollback.verify_post_pods([after], [pod("1")], target(), True)


def test_cluster_environment_rejects_partially_labeled_nodes() -> None:
    nodes = {
        "items": [
            {"metadata": {"labels": {"sugarkube.env": "staging"}}},
            {"metadata": {"labels": {}}},
        ]
    }
    with pytest.raises(rollback.RollbackError, match="do not prove"):
        rollback.cluster_environment(lambda _command: json.dumps(nodes), "kubeconfig")


def test_pre_state_pods_may_be_empty() -> None:
    response = json.dumps({"items": []})
    assert (
        rollback.pods(
            lambda _command: response, "kubeconfig", "dspace", "dspace", require_any=False
        )
        == []
    )
    with pytest.raises(rollback.RollbackError, match="no release-owned"):
        rollback.pods(lambda _command: response, "kubeconfig", "dspace", "dspace")


def test_summary_never_invents_current_chart_digest() -> None:
    current = {
        "version": 8,
        "chart": {"metadata": {"name": "dspace", "version": "3.1.0"}},
    }
    text = rollback.summary(
        current,
        ("dspace", "3.1.0", 8),
        [pod("1")],
        target(),
        [{"path": "values.yaml", "sha256": "3" * 64}],
    )
    assert text == "\n".join(
        [
            "DSPACE manifest rollback preflight:",
            "  current: release=dspace namespace=dspace helmStatus=unknown "
            "helmRevision=8 chartName=dspace chartVersion=3.1.0 chartDigest=unknown",
            f"           images={manifest.IMAGE_REF}:main-abcdef0@{DIGEST} "
            f"imageIDs={manifest.IMAGE_REF}@{DIGEST}",
            f"  target:  release=dspace namespace=dspace sourceRevision={SHA} "
            "applicationVersion=3.2.0",
            f"           chartVersion=3.2.0 chartDigest={'sha256:' + '2' * 64}",
            f"           imageTag=main-abcdef0 imageDigest={DIGEST}",
            f"           imageCoordinate={manifest.IMAGE_REF}:main-abcdef0@{DIGEST}",
            "           provider=token-place",
            f"  values:  values.yaml={'3' * 64}",
        ]
    )


def helm_319_status(**changes: object) -> dict[str, object]:
    value = {
        "config": {},
        "info": {"status": "deployed"},
        "manifest": "must-not-be-reported",
        "name": "dspace",
        "namespace": "dspace",
        "version": 9,
    }
    value.update(changes)
    return value


def test_helm_319_snapshot_resolves_exact_current_history_without_leaking_raw_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def runner(command: list[str]) -> str:
        commands.append(command)
        return json.dumps(
            [
                {"revision": 8, "chart": "dspace-3.0.1"},
                {"revision": 9, "chart": "dspace-3.0.2"},
            ]
        )

    status = helm_319_status()
    monkeypatch.setattr(rollback, "helm_status", lambda *_args: status)
    observed, history, identity = rollback.helm_snapshot(runner, "kubeconfig", "dspace", "dspace")

    assert identity == ("dspace", "3.0.2", 9)
    assert observed is status
    assert history is not None
    assert len(commands) == 1 and "history" in commands[0]
    rendered = rollback.summary(
        observed,
        identity,
        [],
        {**target(), "chartVersion": "3.0.2"},
        [{"path": "values.yaml", "sha256": "3" * 64}],
    )
    assert "chartName=dspace chartVersion=3.0.2" in rendered
    assert "must-not-be-reported" not in rendered


def test_helm_snapshot_uses_status_metadata_without_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = helm_319_status(chart={"metadata": {"name": "dspace", "version": "3.0.2"}})
    monkeypatch.setattr(rollback, "helm_status", lambda *_args: status)
    _status, history, identity = rollback.helm_snapshot(
        lambda _command: pytest.fail("history must not be queried"),
        "kubeconfig",
        "dspace",
        "dspace",
    )
    assert history is None
    assert identity == ("dspace", "3.0.2", 9)


@pytest.mark.parametrize("metadata", ["dspace-3.0.2", ["dspace", "3.0.2"]])
def test_helm_snapshot_rejects_non_object_status_metadata(
    monkeypatch: pytest.MonkeyPatch, metadata: object
) -> None:
    status = helm_319_status(chart={"metadata": metadata})
    monkeypatch.setattr(rollback, "helm_status", lambda *_args: status)

    with pytest.raises(rollback.RollbackError, match="identity") as exc_info:
        rollback.helm_snapshot(
            lambda _command: pytest.fail("history must not be queried"),
            "kubeconfig",
            "dspace",
            "dspace",
        )
    assert "must-not-be-reported" not in str(exc_info.value)


def test_helm_history_rejects_invalid_json() -> None:
    with pytest.raises(rollback.RollbackError, match="valid JSON"):
        rollback.helm_history(lambda _command: "not-json", "kubeconfig", "dspace", "dspace")


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "other"},
        {"info": {"status": "failed"}},
    ],
)
def test_helm_snapshot_rejects_status_identity_or_state(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, object]
) -> None:
    status = helm_319_status(chart={"metadata": {"name": "dspace", "version": "3.0.2"}}, **changes)
    monkeypatch.setattr(rollback, "helm_status", lambda *_args: status)

    with pytest.raises(rollback.RollbackError, match="identity"):
        rollback.helm_snapshot(
            lambda _command: pytest.fail("history must not be queried"),
            "kubeconfig",
            "dspace",
            "dspace",
        )


@pytest.mark.parametrize(
    "history",
    [
        [],
        ["not-an-object"],
        [{"revision": 8, "chart": "dspace-3.0.2"}],
        [
            {"revision": 9, "chart": "dspace-3.0.2"},
            {"revision": 9, "chart": "dspace-3.0.2"},
        ],
        [{"revision": "9", "chart": "dspace-3.0.2"}],
        [{"revision": 9, "chart": "other-3.0.2"}],
        [{"revision": 9, "chart": "dspace-not-semver"}],
        [
            {"revision": 9, "chart": "dspace-3.0.2"},
            {"revision": 10, "chart": "dspace-3.0.2"},
        ],
    ],
)
def test_helm_snapshot_rejects_missing_malformed_ambiguous_or_drifting_history(
    monkeypatch: pytest.MonkeyPatch, history: object
) -> None:
    monkeypatch.setattr(rollback, "helm_status", lambda *_args: helm_319_status())
    with pytest.raises(rollback.RollbackError, match="identity"):
        rollback.helm_snapshot(
            lambda _command: json.dumps(history), "kubeconfig", "dspace", "dspace"
        )


def pre_reservation_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str = "staging",
) -> tuple[Namespace, list[list[str]], Path, Path]:
    manifest_path = tmp_path / "target.json"
    evidence_path = tmp_path / "rollback.json"
    verifier = tmp_path / "verifier"
    values = tmp_path / "values.yaml"
    manifest_path.write_text(manifest._canonical(target(environment)), encoding="utf-8")
    verifier.write_text("#!/bin/sh\n", encoding="utf-8")
    verifier.chmod(0o755)
    values.write_text("environment: test\n", encoding="utf-8")
    monkeypatch.setattr(
        rollback.app_config,
        "load_config",
        lambda *_args: {
            "SUGARKUBE_CHART": f"oci://{manifest.CHART_REF}",
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VALUES": str(values),
        },
    )
    monkeypatch.setattr(rollback, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rollback, "cluster_environment", lambda *_args: environment)
    monkeypatch.setattr(rollback, "verifier_capabilities", lambda *_args: {})
    monkeypatch.setattr(
        rollback.release,
        "preflight",
        lambda *_args, **_kwargs: [{"check": "oci", "passed": True}],
    )
    monkeypatch.setattr(
        rollback,
        "helm_status",
        lambda *_args: {
            "name": "dspace",
            "namespace": "dspace",
            "version": 7,
            "info": {"status": "deployed"},
            "chart": {"metadata": {"name": "dspace", "version": "3.1.0"}},
        },
    )
    monkeypatch.setattr(rollback, "pods", lambda *_args, **_kwargs: [])
    commands: list[list[str]] = []

    args = Namespace(
        environment=environment,
        manifest=manifest_path,
        evidence=evidence_path,
        verifier=verifier,
        confirm="",
        config="",
        kubeconfig="kubeconfig",
        oras="oras",
        timeout="10m",
    )
    return args, commands, evidence_path, verifier


def assert_no_mutation(commands: list[list[str]]) -> None:
    assert not any("upgrade" in command or "rollout" in command for command in commands)


def test_render_failure_precedes_reservation_and_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(tmp_path, monkeypatch)

    def runner(command: list[str]) -> str:
        commands.append(command)
        if "template" in command:
            raise rollback.RollbackError("render failed")
        return ""

    with pytest.raises(rollback.RollbackError, match="render failed"):
        rollback.rollback(args, runner)
    assert not evidence.exists()
    assert_no_mutation(commands)


def test_recovery_initial_production_assertion_failure_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    args.kubeconfig = str(kubeconfig)
    args.configuration_reconciliation = True
    args.production_metrics_recovery = True

    def runner(command: list[str]) -> str:
        commands.append(command)
        return "unexpected-context" if "current-context" in command else ""

    with pytest.raises(rollback.RollbackError, match="requires sugar-prod"):
        rollback.rollback(args, runner)

    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written.pop("failedAt")
    assert written == {
        "schemaVersion": rollback.SCHEMA_VERSION,
        "operation": rollback.RECOVERY_OPERATION,
        "state": "failed",
        "failedStage": "kubeconfig-and-cluster-identity",
        "failureCode": "kubeconfig-and-cluster-identity-failed",
        "clusterMayHaveChanged": False,
        "diagnostics": {"failureType": "RollbackError"},
    }
    assert_no_mutation(commands)


@pytest.mark.parametrize(
    "failed_stage",
    (
        "failed-evidence-authorization",
        "live-state-and-provenance",
        "runtime-and-metrics-preflight",
        "confirmation",
        "reservation",
    ),
)
def test_linked_recovery_pre_reservation_failures_preserve_precise_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_stage: str,
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    args.kubeconfig = str(kubeconfig)
    args.configuration_reconciliation = True
    args.production_metrics_recovery = True
    original = {
        "invocationId": "a" * 32,
        "targetManifestFingerprint": "b" * 64,
    }
    monkeypatch.setattr(rollback, "assert_production_target", lambda *_args: None)

    def reject(_args: Namespace, _runner: object, _staged: Path) -> dict[str, object]:
        _args._recovery_failed_stage = failed_stage
        _args._recovery_original_failure = original
        raise rollback.RollbackError("sensitive diagnostic must not be persisted")

    monkeypatch.setattr(rollback, "_rollback", reject)

    with pytest.raises(rollback.RollbackError, match="sensitive diagnostic"):
        rollback.rollback(args, commands.append)

    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written["failedStage"] == failed_stage
    assert written["failureCode"] == f"{failed_stage}-failed"
    assert written["clusterMayHaveChanged"] is False
    assert written["originalFailure"] == original
    assert written["diagnostics"] == {"failureType": "RollbackError"}
    assert "sensitive" not in evidence.read_text(encoding="utf-8")
    assert_no_mutation(commands)


def test_exact_no_op_is_rejected_before_reservation_and_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(tmp_path, monkeypatch)
    monkeypatch.setattr(rollback, "pods", lambda *_args, **_kwargs: [pod("1")])

    def runner(command: list[str]) -> str:
        commands.append(command)
        if "template" in command or ("get" in command and "manifest" in command):
            return "exact rendered manifest"
        return ""

    with pytest.raises(rollback.RollbackError, match="already the exact approved target"):
        rollback.rollback(args, runner)
    assert not evidence.exists()
    assert_no_mutation(commands)


@pytest.mark.parametrize("gate", ("confirmation", "verifier"))
def test_confirmation_and_verifier_gates_precede_reservation_and_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    environment = "prod" if gate == "confirmation" else "staging"
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment=environment
    )
    if gate == "verifier":
        monkeypatch.setattr(
            rollback,
            "verifier_capabilities",
            lambda *_args: (_ for _ in ()).throw(
                rollback.RollbackError("verifier capabilities are incompatible")
            ),
        )

    def runner(command: list[str]) -> str:
        commands.append(command)
        return "target render" if "template" in command else "installed render"

    message = "confirmation" if gate == "confirmation" else "incompatible"
    with pytest.raises(rollback.RollbackError, match=message):
        rollback.rollback(args, runner)
    assert not evidence.exists()
    assert_no_mutation(commands)
    if gate == "verifier":
        assert not any("template" in command for command in commands)


def test_configuration_reconciliation_invalid_render_fails_before_reservation_and_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.configuration_reconciliation = True
    args.kubeconfig = str(tmp_path / "kubeconfig")
    args.confirm = f"dspace:prod:{SHA}"
    desired = {
        "image": {
            "repository": manifest.IMAGE_REF,
            "tag": "main-abcdef0",
            "pullPolicy": "Always",
        },
        "metrics": {"enabled": True},
        "serviceMonitor": {"enabled": True},
    }
    monkeypatch.setattr(rollback.app_chart, "merged_values_document", lambda _paths: desired)
    monkeypatch.setattr(rollback.app_chart, "validate_rendered_manifest", lambda *_args: ["bad"])
    monkeypatch.setattr(rollback.release, "verify_helm_stored_values", lambda *_args: None)
    monkeypatch.setattr(
        rollback,
        "pods",
        lambda *_args, **_kwargs: [
            {
                "ready": True,
                "applicationImage": f"{manifest.IMAGE_REF}:main-abcdef0",
                "applicationImageID": f"{manifest.IMAGE_REF}@{DIGEST}",
            },
            {
                "ready": True,
                "applicationImage": f"{manifest.IMAGE_REF}:main-abcdef0",
                "applicationImageID": f"{manifest.IMAGE_REF}@{DIGEST}",
            },
        ],
    )
    monkeypatch.setattr(
        rollback,
        "helm_status",
        lambda *_args: {
            "name": "dspace",
            "namespace": "dspace",
            "version": 7,
            "info": {"status": "deployed"},
            "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
        },
    )

    template_calls = 0

    def runner(command: list[str]) -> str:
        nonlocal template_calls
        commands.append(command)
        if "values" in command and "get" in command:
            return json.dumps({"image": desired["image"]})
        if "template" in command:
            template_calls += 1
            return "invalid target render" if template_calls == 1 else "live render"
        if "get" in command and "manifest" in command:
            return "live render"
        return ""

    staged = tmp_path / "staged"
    staged.mkdir()
    with pytest.raises(
        rollback.RollbackError, match="strict application chart render validation failed"
    ):
        rollback._rollback(args, runner, staged)
    assert not evidence.exists()
    assert_no_mutation(commands)


@pytest.mark.parametrize("kubeconfig", ("", "relative/kubeconfig", "/tmp/one:/tmp/two"))
def test_configuration_reconciliation_requires_one_absolute_kubeconfig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kubeconfig: str
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.configuration_reconciliation = True
    args.kubeconfig = kubeconfig

    with pytest.raises(rollback.RollbackError, match="one explicit absolute kubeconfig"):
        rollback.rollback(args, lambda command: commands.append(command) or "")
    assert commands == []
    assert not evidence.exists()


@pytest.mark.parametrize(
    ("failure", "message"),
    (
        ("revision", "live Helm revision differs"),
        ("chart", "live chart coordinate differs"),
        ("pods", "exactly two Ready"),
        ("desired", "desired values are structurally invalid"),
        ("manifest", "live manifest does not match"),
        ("contract", "desired production metrics contract is invalid"),
        ("baseline", "approved disabled baseline"),
        ("monitor", "approved disabled baseline"),
        ("drift", "unrelated Helm values drift"),
        ("image", "live image coordinate differs"),
    ),
)
def test_configuration_reconciliation_preconditions_fail_before_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    message: str,
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.configuration_reconciliation = True
    args.confirm = f"dspace:prod:{SHA}"
    image = {
        "repository": manifest.IMAGE_REF,
        "tag": "main-abcdef0",
        "pullPolicy": "Always",
    }
    desired: object = {
        "image": image,
        "metrics": {"enabled": True},
        "serviceMonitor": {"enabled": True},
    }
    live = {"image": image}
    if failure == "desired":
        desired = []
    elif failure == "baseline":
        live["metrics"] = {"enabled": True}
    elif failure == "monitor":
        live["serviceMonitor"] = {"enabled": True}
    elif failure == "drift":
        live["unrelated"] = True

    monkeypatch.setattr(rollback.app_chart, "merged_values_document", lambda _paths: desired)
    monkeypatch.setattr(rollback.app_chart, "validate_rendered_manifest", lambda *_args: [])

    def verify_stored(*_args: object) -> None:
        if failure == "contract":
            raise manifest.ManifestError("sensitive details must be redacted")

    monkeypatch.setattr(rollback.release, "verify_helm_stored_values", verify_stored)
    ready = {
        "ready": True,
        "applicationImage": f"{manifest.IMAGE_REF}:main-abcdef0",
        "applicationImageID": f"{manifest.IMAGE_REF}@{DIGEST}",
    }
    observed = [ready, ready]
    if failure == "pods":
        observed = [ready]
    elif failure == "image":
        observed = [{**ready, "applicationImageID": f"{manifest.IMAGE_REF}@sha256:{'9' * 64}"}] * 2
    monkeypatch.setattr(rollback, "pods", lambda *_args, **_kwargs: observed)
    monkeypatch.setattr(
        rollback,
        "helm_status",
        lambda *_args: {
            "name": "dspace",
            "namespace": "dspace",
            "version": 8 if failure == "revision" else 7,
            "info": {"status": "deployed"},
            "chart": {
                "metadata": {
                    "name": "dspace",
                    "version": "0.0.0" if failure == "chart" else "3.2.0",
                }
            },
        },
    )
    template_calls = 0

    def runner(command: list[str]) -> str:
        nonlocal template_calls
        commands.append(command)
        if "values" in command and "get" in command:
            return json.dumps(live)
        if "template" in command:
            template_calls += 1
            if template_calls == 1:
                return "target render"
            return "different render" if failure == "manifest" else "live render"
        if "get" in command and "manifest" in command:
            return "live render"
        return ""

    staged = tmp_path / "staged"
    staged.mkdir()
    with pytest.raises(rollback.RollbackError, match=message):
        rollback._rollback(args, runner, staged)
    assert not evidence.exists()
    assert_no_mutation(commands)


@pytest.mark.parametrize("drift", ("context", "identity"))
def test_configuration_reconciliation_reasserts_trusted_target_after_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.configuration_reconciliation = True
    args.confirm = f"dspace:prod:{SHA}"
    desired = {
        "image": {
            "repository": manifest.IMAGE_REF,
            "tag": "main-abcdef0",
            "pullPolicy": "Always",
        },
        "metrics": {"enabled": True},
        "serviceMonitor": {"enabled": True},
    }
    live = {"image": desired["image"]}
    ready_pods = [
        {
            "ready": True,
            "applicationImage": f"{manifest.IMAGE_REF}:main-abcdef0",
            "applicationImageID": f"{manifest.IMAGE_REF}@{DIGEST}",
        }
    ] * 2
    monkeypatch.setattr(rollback.app_chart, "merged_values_document", lambda _paths: desired)
    monkeypatch.setattr(rollback.app_chart, "validate_rendered_manifest", lambda *_args: [])
    monkeypatch.setattr(rollback.release, "verify_helm_stored_values", lambda *_args: None)
    helm_reads = []
    pod_reads = []

    def status(*args: object) -> dict[str, object]:
        helm_reads.append(args)
        return {
            "name": "dspace",
            "namespace": "dspace",
            "version": 7,
            "info": {"status": "deployed"},
            "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
        }

    def pod_read(*args: object, **kwargs: object) -> list[dict[str, object]]:
        pod_reads.append((args, kwargs))
        return ready_pods

    monkeypatch.setattr(rollback, "helm_status", status)
    monkeypatch.setattr(rollback, "pods", pod_read)
    reserved_at = []
    real_reserve = rollback.reserve

    def reserve(path: Path, record: dict[str, object]) -> None:
        real_reserve(path, record)
        reserved_at.append((len(commands), len(helm_reads), len(pod_reads)))

    monkeypatch.setattr(rollback, "reserve", reserve)
    sentinel = "TOP-SECRET-drift-diagnostic"
    template_calls = 0

    def runner(command: list[str]) -> str:
        nonlocal template_calls
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "f" * 40
        if "current-context" in command:
            if drift == "context" and reserved_at:
                return "sugar-staging"
            return "sugar-prod"
        if any("cluster_identity.py" in part for part in command):
            if drift == "identity" and reserved_at:
                raise rollback.RollbackError(sentinel)
            return ""
        if "get" in command and "values" in command:
            return json.dumps(live)
        if "template" in command:
            template_calls += 1
            return "target render" if template_calls == 1 else "live render"
        if "get" in command and "manifest" in command:
            return "live render"
        return ""

    staged = tmp_path / "staged"
    staged.mkdir()
    with pytest.raises(rollback.RollbackError, match="preserved evidence"):
        rollback._rollback(args, runner, staged)

    command_count, helm_count, pod_count = reserved_at[0]
    after_reservation = commands[command_count:]
    assert "current-context" in after_reservation[0]
    assert not any("secret-check" in command for command in after_reservation)
    assert_no_mutation(after_reservation)
    assert len(helm_reads) == helm_count
    assert len(pod_reads) == pod_count
    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written["state"] == "failed"
    assert written["failedStage"] == "pre-mutation-revalidation"
    assert written["clusterMayHaveChanged"] is False
    assert written["diagnostics"] == {}
    assert sentinel not in evidence.read_text(encoding="utf-8")
    original = evidence.read_bytes()
    with pytest.raises(rollback.RollbackError, match="overwrite"):
        rollback.reserve(evidence, {"state": "reserved"})
    assert evidence.read_bytes() == original


@pytest.mark.parametrize(
    ("diagnostic_failure", "state_drift"),
    (
        (None, None),
        ("helm", None),
        ("pods", None),
        (None, "helm"),
        (None, "pods"),
        (None, "values"),
    ),
)
def test_configuration_reconciliation_reasserts_target_immediately_before_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diagnostic_failure: str | None,
    state_drift: str | None,
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    args.configuration_reconciliation = True
    args.confirm = f"dspace:prod:{SHA}"
    image = {
        "repository": manifest.IMAGE_REF,
        "tag": "main-abcdef0",
        "pullPolicy": "Always",
    }
    desired = {
        "image": image,
        "metrics": {"enabled": True},
        "serviceMonitor": {"enabled": True},
    }
    monkeypatch.setattr(rollback.app_chart, "merged_values_document", lambda _paths: desired)
    monkeypatch.setattr(rollback.app_chart, "validate_rendered_manifest", lambda *_args: [])
    monkeypatch.setattr(rollback.release, "verify_helm_stored_values", lambda *_args: None)
    upgrade_attempted = False

    def status(*_args: object) -> dict[str, object]:
        if upgrade_attempted and diagnostic_failure == "helm":
            raise RuntimeError("bounded diagnostic failure")
        observed: dict[str, object] = {
            "name": "dspace",
            "namespace": "dspace",
            "version": 8 if state_drift == "helm" and evidence.exists() else 7,
            "info": {"status": "deployed"},
            "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
        }
        if state_drift == "helm":
            observed.pop("chart")
        return observed

    def observed_pods(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        if upgrade_attempted and diagnostic_failure == "pods":
            raise RuntimeError("bounded diagnostic failure")
        result = [
            {
                "ready": True,
                "applicationImage": f"{manifest.IMAGE_REF}:main-abcdef0",
                "applicationImageID": f"{manifest.IMAGE_REF}@{DIGEST}",
            }
        ] * 2
        if state_drift == "pods" and evidence.exists():
            result[0] = {**result[0], "ready": False}
        return result

    monkeypatch.setattr(rollback, "helm_status", status)
    monkeypatch.setattr(rollback, "pods", observed_pods)
    template_calls = 0

    def runner(command: list[str]) -> str:
        nonlocal template_calls, upgrade_attempted
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "f" * 40
        if "current-context" in command:
            return "sugar-prod"
        if "get" in command and "values" in command:
            values = {"image": image}
            if state_drift == "values" and evidence.exists():
                values["unexpected"] = True
            return json.dumps(values)
        if command[0] == "helm" and "history" in command:
            history = [{"revision": 7, "chart": "dspace-3.2.0"}]
            if evidence.exists():
                history.append({"revision": 8, "chart": "dspace-3.2.0"})
            return json.dumps(history)
        if "template" in command:
            template_calls += 1
            return "target render" if template_calls == 1 else "live render"
        if "get" in command and "manifest" in command:
            return "live render"
        if "upgrade" in command:
            upgrade_attempted = True
            raise rollback.RollbackError("bounded failure")
        return ""

    staged = tmp_path / "staged"
    staged.mkdir()
    with pytest.raises(rollback.RollbackError, match="preserved evidence"):
        rollback._rollback(args, runner, staged)

    written = json.loads(evidence.read_text(encoding="utf-8"))
    if state_drift:
        assert_no_mutation(commands)
        assert written["failedStage"] == "pre-mutation-revalidation"
        assert written["clusterMayHaveChanged"] is False
        return

    upgrade_index = next(i for i, command in enumerate(commands) if "upgrade" in command)
    secret_index = max(i for i, command in enumerate(commands) if "secret-check" in command)
    final_context = max(i for i, command in enumerate(commands) if "current-context" in command)
    final_identity = max(
        i
        for i, command in enumerate(commands)
        if any("cluster_identity.py" in part for part in command)
    )
    assert secret_index < final_context < final_identity < upgrade_index
    assert not any("rollout" in command for command in commands)
    assert written["failedStage"] == "helm-upgrade"
    assert written["clusterMayHaveChanged"] is True
    if diagnostic_failure:
        assert written["diagnostics"][diagnostic_failure] == "unavailable"


@pytest.mark.parametrize("after_revision", (10, 11))
def test_configuration_reconciliation_completes_all_production_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_revision: int
) -> None:
    args, commands, evidence, verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    selected = rollback.chart_maintenance_target(baseline, PROD_MAINTENANCE_TARGET)
    args.manifest.write_text(manifest._canonical(baseline), encoding="utf-8")
    maintenance_target = tmp_path / "maintenance-target.json"
    maintenance_target.write_text(
        PROD_MAINTENANCE_TARGET.read_text(encoding="utf-8"), encoding="utf-8"
    )
    version_file = tmp_path / "dspace.prod.version"
    version_file.write_text("# application remains 3.0.1\n3.0.3\n", encoding="utf-8")
    values_file = tmp_path / "values.yaml"
    monkeypatch.setattr(
        rollback.app_config,
        "load_config",
        lambda *_args: {
            "SUGARKUBE_CHART": f"oci://{manifest.CHART_REF}",
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VALUES": str(values_file),
            "SUGARKUBE_VERSION_FILE": version_file.name,
        },
    )
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    args.configuration_reconciliation = True
    args.maintenance_target = maintenance_target
    args.kubeconfig = str(kubeconfig)
    args.confirm = f"dspace:prod:{selected['sourceRevision']}"
    image = {
        "repository": manifest.IMAGE_REF,
        "tag": selected["imageTag"],
        "pullPolicy": "Always",
    }
    desired = {
        "replicaCount": 2,
        "image": image,
        "metrics": {
            "enabled": True,
            "path": "/metrics",
            "auth": {
                "existingSecret": "dspace-prod-metrics-token",
                "secretKey": "token",
            },
        },
        "serviceMonitor": {
            "enabled": True,
            "interval": "30s",
            "scrapeTimeout": "10s",
            "additionalLabels": {"release": "kube-prometheus-stack"},
            "cluster": "sugarkube-prod",
        },
    }
    live = {
        "replicaCount": 2,
        "image": {"tag": selected["imageTag"], "pullPolicy": "Always"},
    }
    stored_proof = [{"check": "helmStoredValues", "passed": True, "details": "safe"}]
    finalized: dict[str, object] = {}
    monkeypatch.setattr(rollback.app_chart, "merged_values_document", lambda _paths: desired)
    monkeypatch.setattr(rollback.app_chart, "validate_rendered_manifest", lambda *_args: [])

    def verify_stored(_approved: object, values: object, _environment: str) -> object:
        assert values == desired
        return stored_proof

    def finalize(*_args: object, **kwargs: object) -> dict[str, object]:
        finalized.update(kwargs)
        return {"verificationResults": [{"check": "finalized", "passed": True}]}

    monkeypatch.setattr(rollback.release, "verify_helm_stored_values", verify_stored)
    monkeypatch.setattr(rollback.release, "finalize", finalize)
    monkeypatch.setattr(rollback, "verifier_accepts_runtime_arguments", lambda *_args: True)

    def ready(uid: str) -> dict[str, object]:
        return {
            **pod(uid),
            "applicationImage": f"{manifest.IMAGE_REF}:{selected['imageTag']}",
            "applicationImageID": f"{manifest.IMAGE_REF}@{selected['imageDigest']}",
        }

    before_pods = [ready("1"), ready("2")]
    after_pods = [ready("3"), ready("4")]
    terminating_pods = [{**ready("2"), "terminating": True}, *after_pods]
    state = {"upgraded": False, "description": "", "post_upgrade_pod_reads": 0}
    staged_target: dict[str, object] = {}
    monkeypatch.setattr(rollback.time, "sleep", lambda _seconds: None)

    def status(*_args: object) -> dict[str, object]:
        return {
            "name": "dspace",
            "namespace": "dspace",
            "version": after_revision if state["upgraded"] else 9,
            "info": {
                "status": "deployed",
                "description": state["description"] if state["upgraded"] else "previous",
            },
        }

    monkeypatch.setattr(rollback, "helm_status", status)

    def observed_pods(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        if not state["upgraded"]:
            observed = before_pods
        else:
            state["post_upgrade_pod_reads"] += 1
            observed = terminating_pods if state["post_upgrade_pod_reads"] == 1 else after_pods
        return json.loads(json.dumps(observed))

    monkeypatch.setattr(rollback, "pods", observed_pods)

    def runner(command: list[str]) -> str:
        commands.append(command)
        if "current-context" in command:
            return "sugar-prod"
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "f" * 40
        if command[0] == "helm" and "upgrade" in command:
            state["description"] = command[command.index("--description") + 1]
            state["upgraded"] = True
        elif command[0] == "helm" and "history" in command:
            return json.dumps(
                [
                    {
                        "revision": after_revision if state["upgraded"] else 9,
                        "chart": "dspace-"
                        + (
                            selected["chartVersion"]
                            if state["upgraded"]
                            else baseline["chartVersion"]
                        ),
                    }
                ]
            )
        elif command[0] == "helm" and "values" in command and "get" in command:
            return json.dumps(desired if "--all" in command else live)
        elif command[0] == "helm" and "template" in command:
            return "live render" if "live-values.json" in " ".join(command) else "target render"
        elif command[0] == "helm" and "manifest" in command:
            return "live render"
        elif command[:2] == [str(verifier), "verify"]:
            staged_target.update(
                json.loads(
                    Path(command[command.index("--manifest") + 1]).read_text(encoding="utf-8")
                )
            )
            return json.dumps(
                verifier_result(
                    environment="prod",
                    applicationVersion=selected["applicationVersion"],
                    runtimeSourceRevision=selected["sourceRevision"],
                    frontendSourceRevision=selected["sourceRevision"],
                    defaultProvider=selected["expectedDefaultChatProvider"],
                )
            )
        elif command[0] == "kubectl" and (
            "replicasets,deployments" in command or "pods" in command
        ):
            return '{"items": []}'
        return ""

    if after_revision == 11:
        with pytest.raises(rollback.RollbackError, match="preserved evidence"):
            rollback.rollback(args, runner)
        written = json.loads(evidence.read_text(encoding="utf-8"))
        assert written["state"] == "failed"
        assert written["failedStage"] == "pod-settling-and-proof"
        assert written["clusterMayHaveChanged"] is True
        assert sum("upgrade" in command for command in commands) == 1
        assert not any("rollback" in command or "uninstall" in command for command in commands)
        return

    result = rollback.rollback(args, runner)

    upgrade = next(command for command in commands if "upgrade" in command)
    templates = [command for command in commands if "template" in command]
    assert "image.pullPolicy=Always" in templates[0]
    assert "image.pullPolicy=Always" in upgrade
    assert sum("upgrade" in command for command in commands) == 1
    assert upgrade[upgrade.index("--kubeconfig") + 1] == str(kubeconfig)
    assert f"oci://{manifest.CHART_REF}@{selected['chartDigest']}" in upgrade
    assert f"image.tag={selected['imageTag']}" in upgrade
    assert "image.pullPolicy=Always" in upgrade
    rendered = next(command for command in commands if "template" in command)
    assert "image.pullPolicy=Always" in rendered
    forbidden = ("--reuse-values", "--version", selected["semanticTag"], "rollback")
    assert not any(item in upgrade for item in forbidden)
    assert selected["imageDigest"] not in next(
        item for item in upgrade if item.startswith("image.tag=")
    )
    assert finalized["helm_stored_values_result"] is stored_proof
    assert finalized["helm_history"] == [
        {"revision": 10, "chart": f"dspace-{selected['chartVersion']}"}
    ]
    assert finalized["expected_image_coordinate"] == (
        f"{manifest.IMAGE_REF}:{selected['imageTag']}"
    )
    assert result["state"] == "succeeded"
    assert result["helm"]["beforeRevision"] == 9
    assert result["helm"]["afterRevision"] == 10
    assert result["verification"]["helmStoredValues"] == stored_proof
    assert result["verification"]["runtime"]["sourceRevision"] == selected["sourceRevision"]
    journeys = {item["name"] for item in result["verification"]["journeys"]}
    assert journeys == {"/", "/chat"}
    assert result["verification"]["productionMetrics"] == {
        "secretContract": True,
        "serviceMonitor": True,
        "healthyTargets": 2,
        "requiredFamilies": True,
        "unauthenticatedStatus": 401,
    }
    assert json.loads(evidence.read_text(encoding="utf-8")) == result
    assert "dspace-prod-metrics-token" not in evidence.read_text(encoding="utf-8")
    original = evidence.read_bytes()
    with pytest.raises(rollback.RollbackError, match="overwrite"):
        rollback.reserve(evidence, {"state": "reserved"})
    assert evidence.read_bytes() == original
    assert sum("secret-check" in command for command in commands) == 2
    metrics_verifications = [
        command
        for command in commands
        if "observability_app_metrics.py" in " ".join(command) and "verify" in command
    ]
    assert len(metrics_verifications) == 1
    assert state["post_upgrade_pod_reads"] == 2
    assert staged_target["recordType"] == "candidate"
    for field in manifest.candidate_fields(selected):
        if field == "recordType":
            continue
        assert staged_target[field] == selected[field]
    verifier_command = next(
        command for command in commands if command[:2] == [str(verifier), "verify"]
    )
    assert verifier_command[verifier_command.index("--manifest") + 1] != str(args.manifest)


def test_staging_is_non_interactive_and_reservation_collision_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, _verifier = pre_reservation_case(tmp_path, monkeypatch)
    original = b"pre-existing immutable evidence\n"
    evidence.write_bytes(original)

    def runner(command: list[str]) -> str:
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "f" * 40 + "\n"
        return "target render" if "template" in command else "installed render"

    with pytest.raises(rollback.RollbackError, match="refusing to overwrite"):
        rollback.rollback(args, runner)
    assert evidence.read_bytes() == original
    assert any("template" in command for command in commands)
    assert any("get" in command and "manifest" in command for command in commands)
    assert_no_mutation(commands)


def test_reservation_collision_and_failure_record_are_non_secret(tmp_path: Path) -> None:
    evidence = tmp_path / "rollback.json"
    reservation = {"schemaVersion": 1, "state": "reserved", "invocationId": "safe"}
    rollback.reserve(evidence, reservation)
    with pytest.raises(rollback.RollbackError, match="overwrite"):
        rollback.reserve(evidence, reservation)
    failed = {**reservation, "state": "failed", "diagnostic": "RollbackError"}
    rollback.replace_reserved(evidence, failed)
    assert json.loads(evidence.read_text(encoding="utf-8")) == failed
    assert "token" not in evidence.read_text(encoding="utf-8").lower()


def test_just_recipe_has_no_revision_rollback_or_reuse_values() -> None:
    recipe = (Path(__file__).parents[1] / "justfile").read_text(encoding="utf-8")
    block = recipe.split("dspace-manifest-rollback", 1)[1].split("\n# Generic", 1)[0]
    assert "dspace_manifest_rollback.py" in block
    assert "--reuse-values" not in block
    assert "helm rollback" not in block


def test_recovery_recipe_strips_only_the_matching_argument_prefix_once() -> None:
    recipe = (Path(__file__).parents[1] / "justfile").read_text(encoding="utf-8")
    block = recipe.split("dspace-prod-metrics-pull-policy-recover", 1)[1].split(
        "\n# Read-only DSPACE", 1
    )[0]
    for prefix in (
        "failed_evidence",
        "maintenance_target",
        "recovery_evidence",
        "smoke_runner",
        "kubeconfig",
        "verifier",
        "confirm",
        "config",
    ):
        assert f"#{prefix}=" in block
    assert "while [[" not in block
    assert "${value#*=}" not in block


@pytest.mark.parametrize(
    ("failure", "failed_stage", "may_have_changed"),
    [
        (None, None, None),
        ("pre-mutation", "pre-mutation-revalidation", False),
        ("helm", "helm-upgrade", True),
        ("rollout", "rollout-wait", True),
        ("verifier", "runtime-verification", True),
        ("revision", "revision-stability-collection", True),
        ("unchanged-revision", "pod-settling-and-proof", True),
        ("lower-revision", "pod-settling-and-proof", True),
    ],
)
def test_orchestration_preserves_complete_success_and_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    failed_stage: str | None,
    may_have_changed: bool | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "target.json"
    evidence_path = tmp_path / "rollback.json"
    verifier = tmp_path / "verifier"
    verifier.write_text("#!/bin/sh\n", encoding="utf-8")
    verifier.chmod(0o755)
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "staging.yaml"
    base.write_text("base: true\n", encoding="utf-8")
    overlay.write_text("staging: true\n", encoding="utf-8")
    selected_target = target()
    manifest_path.write_text(manifest._canonical(selected_target), encoding="utf-8")
    config = {
        "SUGARKUBE_CHART": f"oci://{manifest.CHART_REF}",
        "SUGARKUBE_RELEASE": "dspace",
        "SUGARKUBE_NAMESPACE": "dspace",
        "SUGARKUBE_VALUES": f"{base},{overlay}",
    }
    monkeypatch.setattr(rollback.app_config, "load_config", lambda *_args: config)
    monkeypatch.setattr(rollback, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rollback, "cluster_environment", lambda *_args: "staging")
    monkeypatch.setattr(
        rollback,
        "verifier_capabilities",
        lambda *_args: {
            "schemaVersion": 1,
            "capabilities": list(rollback.REQUIRED_CAPABILITIES),
        },
    )
    monkeypatch.setattr(
        rollback.release,
        "preflight",
        lambda *_args, **_kwargs: [{"check": "imageDigest", "passed": True, "details": "observed"}],
    )
    monkeypatch.setattr(rollback.release, "finalize", lambda *_args, **_kwargs: {})
    upgrade_attempted = [False]
    post_status_calls = [0]

    def status(*_args: object) -> dict[str, object]:
        if not upgrade_attempted[0]:
            return {
                "name": "dspace",
                "namespace": "dspace",
                "version": 7,
                "info": {"status": "deployed", "description": "old"},
                "chart": {"metadata": {"name": "dspace", "version": "3.1.0"}},
            }
        post_status_calls[0] += 1
        revision = 9 if failure == "revision" and post_status_calls[0] >= 2 else 8
        if failure == "unchanged-revision":
            revision = 7
        elif failure == "lower-revision":
            revision = 6
        observed: dict[str, object] = {
            "name": "dspace",
            "namespace": "dspace",
            "version": revision,
            "info": {
                "status": "failed" if failure == "helm" else "deployed",
                "description": description[0],
            },
            "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
        }
        if failure == "helm":
            observed.pop("chart")
        return observed

    description = [""]
    monkeypatch.setattr(rollback, "helm_status", status)
    pod_states = iter([[pod("1", digest="sha256:" + "9" * 64)], [pod("2")]])
    latest = [pod("2")]

    def pods_stub(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        try:
            latest[:] = next(pod_states)
        except StopIteration:
            pass
        return json.loads(json.dumps(latest))

    monkeypatch.setattr(rollback, "pods", pods_stub)
    commands: list[list[str]] = []
    git_calls = [0]
    sentinel = "TOP-SECRET-verifier-output"

    def runner(command: list[str]) -> str:
        commands.append(command)
        if command[0] == "helm" and "upgrade" in command:
            upgrade_attempted[0] = True
            description[0] = command[command.index("--description") + 1]
            if failure == "helm":
                raise rollback.RollbackError(sentinel)
        if command[0] == "helm" and "history" in command:
            revision = {"unchanged-revision": 7, "lower-revision": 6}.get(failure, 8)
            return json.dumps([{"revision": revision, "chart": "dspace-3.2.0"}])
        if command[0] == "kubectl" and "rollout" in command and failure == "rollout":
            raise rollback.RollbackError(sentinel)
        if command[:2] == [str(verifier), "verify"]:
            if failure == "verifier":
                raise rollback.RollbackError(sentinel)
            return json.dumps(verifier_result())
        if command[:2] == ["git", "rev-parse"]:
            git_calls[0] += 1
            if failure == "pre-mutation" and git_calls[0] == 2:
                return "e" * 40 + "\n"
            return "f" * 40 + "\n"
        if command[0] == "kubectl" and "replicasets,deployments" in command:
            return '{"items": []}'
        if command[0] == "kubectl" and "pods" in command:
            return '{"items": []}'
        return "rendered"

    args = Namespace(
        environment="staging",
        manifest=manifest_path,
        evidence=evidence_path,
        verifier=verifier,
        confirm="",
        config="",
        kubeconfig="kubeconfig",
        oras="oras",
        timeout="10m",
    )
    if failure is not None:
        with pytest.raises(rollback.RollbackError, match="preserved evidence"):
            rollback.rollback(args, runner)
        written = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert written["state"] == "failed"
        assert written["failedStage"] == failed_stage
        assert written["failureCode"] == f"{failed_stage}-failed"
        assert written["failureType"] == "rollback"
        assert written["clusterMayHaveChanged"] is may_have_changed
        assert written["sugarkubeRevision"] == "f" * 40
        assert sentinel not in evidence_path.read_text(encoding="utf-8")
        assert sentinel not in capsys.readouterr().err
        observed = written["diagnostics"]
        assert observed["helm"] == {
            "release": "dspace",
            "namespace": "dspace",
            "revision": (
                7
                if failure in ("pre-mutation", "unchanged-revision")
                else 6 if failure == "lower-revision" else 9 if failure == "revision" else 8
            ),
            "status": "failed" if failure == "helm" else "deployed",
            "chartName": "dspace",
            "chartVersion": "3.1.0" if failure == "pre-mutation" else "3.2.0",
            "invocationDescriptionMatches": failure != "pre-mutation",
        }
        assert observed["pods"][0]["uid"] == "2"
        assert observed["pods"][0]["startTime"]
        assert observed["pods"][0]["images"]["dspace"]
        assert observed["pods"][0]["imageIDs"]["dspace"]
        assert "ownerReferences" in observed["pods"][0]
        if failure in ("unchanged-revision", "lower-revision"):
            assert sum("upgrade" in command for command in commands) == 1
            assert not any("rollback" in command or "uninstall" in command for command in commands)
        return

    result = rollback.rollback(args, runner)
    upgrade = next(command for command in commands if "upgrade" in command)
    assert f"oci://{manifest.CHART_REF}@{'sha256:' + '2' * 64}" in upgrade
    assert f"image.tag=main-abcdef0@{DIGEST}" in upgrade
    assert upgrade.count("--values") == 2
    template = next(command for command in commands if "template" in command)
    assert [upgrade[i + 1] for i, item in enumerate(upgrade) if item == "--values"] == [
        template[i + 1] for i, item in enumerate(template) if item == "--values"
    ]
    assert "--reuse-values" not in upgrade
    assert result["state"] == "succeeded"
    written = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert written["targetManifestFingerprint"] == result["targetManifestFingerprint"]
    assert written["helm"]["beforeRevision"] == 7
    assert written["helm"]["afterRevision"] == 8


def recovery_execution_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_after_upgrade: bool = False,
    fault: str | None = None,
) -> tuple[Namespace, list[list[str]], Path, Path, dict[str, object]]:
    """Build the reviewed revision-10 incident around the real recovery lifecycle."""
    baseline = manifest.validate(manifest._object(PROD_BASELINE), True)
    selected = rollback.chart_maintenance_target(baseline, PROD_MAINTENANCE_TARGET)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(manifest._canonical(baseline), encoding="utf-8")
    target_path = tmp_path / "target.json"
    target_path.write_bytes(PROD_MAINTENANCE_TARGET.read_bytes())
    failed_path = tmp_path / "failed.json"
    fingerprint = hashlib.sha256(manifest._canonical(selected).encode()).hexdigest()
    original = {
        "schemaVersion": rollback.SCHEMA_VERSION,
        "environment": "prod",
        "release": "dspace",
        "namespace": "dspace",
        "operation": "dspaceProductionMetricsReconciliation",
        "state": "failed",
        "failedStage": "ownership-and-finalization-proof",
        "failureCode": "ownership-and-finalization-proof-failed",
        "clusterMayHaveChanged": True,
        "invocationId": "a" * 32,
        "targetManifestFingerprint": fingerprint,
        "before": {"helmRevision": 9, "chartName": "dspace", "chartVersion": "3.0.2"},
        "target": {
            key: selected[key]
            for key in (
                "applicationVersion",
                "sourceRevision",
                "imageTag",
                "imageDigest",
                "chartSourceRevision",
                "chartVersion",
                "chartDigest",
                "expectedDefaultChatProvider",
            )
        },
    }
    failed_path.write_text(json.dumps(original), encoding="utf-8")
    evidence = tmp_path / "recovery.json"
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    smoke = tmp_path / "smoke"
    smoke.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    smoke.chmod(0o700)
    values = tmp_path / "values.yaml"
    values.write_text("replicaCount: 2\n", encoding="utf-8")
    production_values = tmp_path / "prod-values.yaml"
    production_values.write_text("metrics:\n  enabled: true\n", encoding="utf-8")
    version = tmp_path / "version"
    version.write_text("3.0.3\n", encoding="utf-8")
    args = Namespace(
        environment="prod",
        manifest=baseline_path,
        baseline_manifest=baseline_path,
        maintenance_target=target_path,
        failed_evidence=failed_path,
        evidence=evidence,
        verifier=rollback.REPO_ROOT / "scripts/dspace_runtime_verifier.py",
        smoke_runner=smoke,
        confirm=rollback.RECOVERY_CONFIRMATION,
        config="",
        kubeconfig=str(kubeconfig),
        oras="oras",
        timeout="7m",
        configuration_reconciliation=True,
        production_metrics_recovery=True,
    )
    desired = {
        "replicaCount": 2,
        "image": {
            "repository": manifest.IMAGE_REF,
            "tag": selected["imageTag"],
            "pullPolicy": "Always",
        },
        "metrics": {"enabled": True},
        "serviceMonitor": {"enabled": True},
    }
    user_values = json.loads(json.dumps(desired))
    user_values["image"].pop("pullPolicy")
    computed_before = json.loads(json.dumps(desired))
    computed_before["image"]["pullPolicy"] = "IfNotPresent"
    state = {
        "upgraded": False,
        "description": "",
        "pod_reads": 0,
        "all_reads": 0,
        "status_reads": 0,
        "user_reads": 0,
        "strict_calls": [],
        "finalize_calls": [],
        "render_calls": [],
        "preflight_calls": [],
        "raw_workload_reads": 0,
    }
    commands: list[list[str]] = []

    monkeypatch.setattr(rollback, "assert_production_target", lambda *_args: None)
    monkeypatch.setattr(rollback, "cluster_environment", lambda *_args: "prod")
    monkeypatch.setattr(
        rollback, "verifier_capabilities", lambda *_args: {"contract": "repository"}
    )
    monkeypatch.setattr(rollback, "verifier_accepts_runtime_arguments", lambda *_args: True)
    def preflight(*call_args: object, **call_kwargs: object) -> dict[str, bool]:
        state["preflight_calls"].append((call_args, call_kwargs))
        if fault == "provenance":
            raise manifest.ManifestError("SENTINEL missing immutable provenance")
        return {"image": True, "chart": True}

    monkeypatch.setattr(rollback.release, "preflight", preflight)

    def verify_stored(*call_args: object) -> list[dict[str, object]]:
        state["strict_calls"].append(call_args)
        if (fault == "stored-contract" and len(state["strict_calls"]) == 2) or (
            fault == "post-stored-contract" and state["upgraded"]
        ):
            raise manifest.ManifestError("SENTINEL invalid stored values")
        return [{"check": "helmStoredValues", "passed": True}]

    monkeypatch.setattr(rollback.release, "verify_helm_stored_values", verify_stored)
    monkeypatch.setattr(
        rollback.release,
        "finalize",
        lambda *call_args, **call_kwargs: state["finalize_calls"].append(
            (call_args, call_kwargs)
        )
        or {"verificationResults": [{"check": "ownership", "passed": True}]},
    )
    monkeypatch.setattr(
        rollback.app_chart,
        "validate_rendered_manifest",
        lambda *call_args: state["render_calls"].append(call_args) or [],
    )
    monkeypatch.setattr(rollback.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(rollback, "chart_pin", lambda _path: "3.0.3")
    monkeypatch.setattr(
        rollback,
        "stage_values",
        lambda _config, _root, _staged: (
            [values, production_values],
            [
                {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in (values, production_values)
            ],
        ),
    )
    monkeypatch.setattr(
        rollback.app_config,
        "load_config",
        lambda *_args: {
            "SUGARKUBE_CHART": f"oci://{manifest.CHART_REF}",
            "SUGARKUBE_RELEASE": "dspace",
            "SUGARKUBE_NAMESPACE": "dspace",
            "SUGARKUBE_VALUES": str(values),
            "SUGARKUBE_VERSION_FILE": str(version),
        },
    )

    def merged(paths: object) -> dict[str, object]:
        if any("chart-defaults" in str(p) for p in paths):
            if fault == "invalid-chart-defaults":
                return []  # type: ignore[return-value]
            if fault == "missing-default-image":
                return {"replicaCount": 2}
        return json.loads(
            json.dumps(
                computed_before if any("chart-defaults" in str(p) for p in paths) else desired
            )
        )

    monkeypatch.setattr(rollback.app_chart, "merged_values_document", merged)

    def ready(uid: str) -> dict[str, object]:
        return {
            **pod(uid),
            "applicationImage": f"{manifest.IMAGE_REF}:{selected['imageTag']}",
            "applicationImageID": f"{manifest.IMAGE_REF}@{selected['imageDigest']}",
        }

    before_pods, after_pods = [ready("old-1"), ready("old-2")], [ready("new-1"), ready("new-2")]
    monkeypatch.setattr(
        rollback,
        "pods",
        lambda *_args, **_kwargs: _recovery_pods(state, fault, before_pods, after_pods),
    )
    monkeypatch.setattr(
        rollback,
        "helm_status",
        lambda *_args: _recovery_helm_status(state, fault, original),
    )

    def runner(command: list[str]) -> str:
        commands.append(command)
        joined = " ".join(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "f" * 40
        if command[0] == "helm" and "history" in command:
            return json.dumps(
                [{"revision": 11 if state["upgraded"] else 10, "chart": "dspace-3.0.3"}]
            )
        if command[0] == "helm" and "upgrade" in command:
            state["description"] = command[command.index("--description") + 1]
            state["upgraded"] = True
            if fail_after_upgrade:
                raise rollback.RollbackError("credential=secret SENTINEL raw command output")
            return ""
        if command[0] == "helm" and "get" in command and "values" in command:
            if "--all" in command:
                state["all_reads"] += 1
                result = desired if state["upgraded"] else computed_before
                if fault == "post-computed" and state["upgraded"]:
                    result = {**desired, "unrelated": True}
                if fault == "computed-drift" and state["all_reads"] == 1:
                    result = {**computed_before, "unrelated": True}
                if fault == "concurrent-computed" and state["all_reads"] == 2:
                    result = {**computed_before, "unrelated": True}
                return json.dumps(result)
            state["user_reads"] += 1
            result = user_values
            if fault == "user-drift" and state["user_reads"] == 1:
                result = {**user_values, "unrelated": True}
            if fault == "concurrent-user" and state["user_reads"] == 2:
                result = {**user_values, "unrelated": True}
            return json.dumps(result)
        if command[0] == "helm" and "show" in command:
            return "image:\n  pullPolicy: IfNotPresent\n"
        def deployment(policy: str) -> dict[str, object]:
            return {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "dspace"},
                "spec": {
                    "replicas": 2,
                    "selector": {"matchLabels": {"app": "dspace"}},
                    "template": {
                        "metadata": {"labels": {"app": "dspace"}},
                        "spec": {
                            "containers": [
                                {
                                    "name": "dspace",
                                    "image": f"{manifest.IMAGE_REF}:{selected['imageTag']}",
                                    "imagePullPolicy": policy,
                                }
                            ]
                        },
                    },
                },
            }

        if command[0] == "helm" and "manifest" in command:
            return "different render" if fault == "render" else json.dumps(deployment("IfNotPresent"))
        if command[0] == "helm" and "template" in command:
            policy = "IfNotPresent" if "live-values.json" in joined else "Always"
            return json.dumps(deployment(policy))
        if command[:2] == [str(args.verifier), "verify"]:
            if fault == "runtime":
                raise rollback.RollbackError("runtime ownership failed")
            expected = command[command.index("--expected-helm-revision") + 1]
            assert expected == ("11" if state["upgraded"] else "10")
            return json.dumps(
                verifier_result(
                    environment="prod",
                    applicationVersion=selected["applicationVersion"],
                    runtimeSourceRevision=selected["sourceRevision"],
                    frontendSourceRevision=selected["sourceRevision"],
                    defaultProvider=selected["expectedDefaultChatProvider"],
                )
            )
        if (
            "observability_app_metrics.py" in joined
            and "secret-check" in command
            and fault == "secret"
        ):
            raise rollback.RollbackError("Secret contract failed")
        if "observability_app_metrics.py" in joined and "verify" in command and fault == "metrics":
            raise rollback.RollbackError("metrics verification failed")
        if command[0] == "kubectl" and "get" in command:
            policy = "Always" if state["upgraded"] else "IfNotPresent"
            if "replicasets,deployments" in command:
                state["raw_workload_reads"] += 1
                live = deployment(policy)
                if fault == "concurrent-workload" and state["raw_workload_reads"] == 2:
                    live["spec"]["replicas"] = 3  # type: ignore[index]
                if fault == "post-workload" and state["upgraded"]:
                    live["spec"]["template"]["metadata"]["annotations"] = {"drift": "yes"}  # type: ignore[index]
                return json.dumps({"items": [live]})
            raw_pods = {
                "items": [
                    {
                        "spec": {
                            "containers": [
                                {"name": "dspace", "imagePullPolicy": policy}
                            ]
                        },
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                        },
                    }
                    for _ in range(2)
                ]
            }
            if fault == "post-policy" and state["upgraded"]:
                raw_pods["items"][0]["spec"]["containers"][0]["imagePullPolicy"] = "IfNotPresent"
            return json.dumps(raw_pods)
        return ""

    args._test_state = state
    args._test_values = [values, production_values]
    args._test_runner = runner
    return args, commands, failed_path, baseline_path, selected


def _recovery_helm_status(
    state: dict[str, object], fault: str | None, original: dict[str, object]
) -> dict[str, object]:
    state["status_reads"] += 1
    revision = 11 if state["upgraded"] else 10
    if not state["upgraded"] and state["status_reads"] == 1:
        if fault == "revision":
            revision = 9
        elif fault == "already-recovered":
            revision = 11
    if fault == "concurrent-revision" and state["status_reads"] == 3:
        revision = 12
    return {
            "name": "dspace",
            "namespace": "dspace",
            "version": revision,
            "chart": {
                "metadata": {
                    "name": "dspace",
                    "version": "3.0.2" if fault == "chart" else "3.0.3",
                }
            },
            "info": {
                "status": "deployed",
                "description": (
                    state["description"]
                    if state["upgraded"]
                    else (
                        "wrong-description"
                        if fault == "description"
                        else f"sugarkube-dspace-metrics-reconciliation:{original['invocationId']}"
                    )
                ),
            },
    }


def _recovery_pods(
    state: dict[str, object],
    fault: str | None,
    before_pods: list[dict[str, object]],
    after_pods: list[dict[str, object]],
) -> list[dict[str, object]]:
    state["pod_reads"] += 1
    result = json.loads(json.dumps(after_pods if state["upgraded"] else before_pods))
    if not state["upgraded"] and state["pod_reads"] == 1:
        if fault == "pod-count":
            result.pop()
        elif fault == "pod-readiness":
            result[0]["ready"] = False
        elif fault == "image-digest":
            result[0]["applicationImageID"] = f"{manifest.IMAGE_REF}@sha256:{'0' * 64}"
        elif fault == "image-tag":
            result[0]["applicationImage"] = f"{manifest.IMAGE_REF}:wrong-tag"
    if fault == "concurrent-pod" and state["pod_reads"] == 2:
        result[0]["uid"] = "drifted"
    return result


def test_production_metrics_recovery_completes_revision_10_to_11(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, failed, baseline, selected = recovery_execution_case(tmp_path, monkeypatch)
    source_bytes = (failed.read_bytes(), baseline.read_bytes())
    result = rollback.rollback(args, args._test_runner)
    upgrades = [command for command in commands if command[0] == "helm" and "upgrade" in command]
    assert len(upgrades) == 1
    upgrade = upgrades[0]
    assert f"oci://{manifest.CHART_REF}@{selected['chartDigest']}" in upgrade
    assert [upgrade[i + 1] for i, value in enumerate(upgrade) if value == "--values"] == [
        str(path) for path in args._test_values
    ]
    assert f"image.repository={manifest.IMAGE_REF}" in upgrade
    assert f"image.tag={selected['imageTag']}" in upgrade
    assert "image.pullPolicy=Always" in upgrade
    assert "--wait" in upgrade and upgrade[upgrade.index("--timeout") + 1] == "7m"
    assert "--reuse-values" not in upgrade
    assert not any("rollback" in command or "uninstall" in command for command in commands)
    assert result["helm"]["beforeRevision"] == 10
    assert result["helm"]["afterRevision"] == 11
    assert result["originalFailure"] == {
        "invocationId": "a" * 32,
        "targetManifestFingerprint": hashlib.sha256(
            manifest._canonical(selected).encode()
        ).hexdigest(),
    }
    verifier_revisions = [
        command[command.index("--expected-helm-revision") + 1]
        for command in commands
        if command[:2] == [str(args.verifier), "verify"]
    ]
    assert verifier_revisions == ["10", "11"]
    assert (
        sum("observability_app_metrics.py" in " ".join(c) and "verify" in c for c in commands) == 2
    )
    assert (failed.read_bytes(), baseline.read_bytes()) == source_bytes
    assert len(args._test_state["preflight_calls"]) == 1
    assert len(args._test_state["render_calls"]) == 1
    assert len(args._test_state["strict_calls"]) == 3
    assert len(args._test_state["finalize_calls"]) == 1
    assert args._test_state["all_reads"] == 3
    assert args._test_state["raw_workload_reads"] == 3
    assert args._test_state["status_reads"] >= 4


def test_production_metrics_recovery_post_upgrade_failure_is_single_shot_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, failed, baseline, _selected = recovery_execution_case(
        tmp_path, monkeypatch, fail_after_upgrade=True
    )
    source_bytes = (failed.read_bytes(), baseline.read_bytes())
    with pytest.raises(rollback.RollbackError, match="preserved evidence"):
        rollback.rollback(args, args._test_runner)
    written = json.loads(args.evidence.read_text(encoding="utf-8"))
    assert written["failedStage"] == "helm-upgrade"
    assert written["clusterMayHaveChanged"] is True
    assert written["originalFailure"]["invocationId"] == "a" * 32
    serialized = args.evidence.read_text(encoding="utf-8")
    assert not any(
        secret in serialized
        for secret in ("SENTINEL", "credential", "secret", "raw command output")
    )
    assert sum(command[0] == "helm" and "upgrade" in command for command in commands) == 1
    assert not any("rollback" in command or "uninstall" in command for command in commands)
    assert not any(command[0] == "kubectl" and "secret" in command for command in commands)
    assert (failed.read_bytes(), baseline.read_bytes()) == source_bytes


@pytest.mark.parametrize(
    ("field", "wrong"),
    (
        ("failedStage", "runtime-verification"),
        ("invocationId", "not-an-invocation"),
        ("targetManifestFingerprint", "not-a-fingerprint"),
        ("targetManifestFingerprint", "0" * 64),
    ),
)
def test_production_metrics_recovery_rejects_bad_original_evidence_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, wrong: object
) -> None:
    args, commands, failed, baseline, _selected = recovery_execution_case(tmp_path, monkeypatch)
    changed = json.loads(failed.read_text(encoding="utf-8"))
    changed[field] = wrong
    failed.write_text(json.dumps(changed), encoding="utf-8")
    source_bytes = (failed.read_bytes(), baseline.read_bytes())
    with pytest.raises(rollback.RollbackError):
        rollback.rollback(args, args._test_runner)
    assert not any(
        command[0] == "helm"
        and any(action in command for action in ("upgrade", "rollback", "uninstall"))
        for command in commands
    )
    assert not any(command[0] == "kubectl" and "secret" in command for command in commands)
    assert (failed.read_bytes(), baseline.read_bytes()) == source_bytes
    assert (
        json.loads(args.evidence.read_text(encoding="utf-8"))["failedStage"]
        == "failed-evidence-authorization"
    )


def test_production_metrics_recovery_output_collision_is_byte_immutable_and_non_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, failed, baseline, _selected = recovery_execution_case(tmp_path, monkeypatch)
    collision = b"existing recovery evidence = immutable\n"
    args.evidence.write_bytes(collision)
    source_bytes = (failed.read_bytes(), baseline.read_bytes())
    with pytest.raises(rollback.RollbackError, match="overwrite"):
        rollback.rollback(args, args._test_runner)
    assert args.evidence.read_bytes() == collision
    assert (failed.read_bytes(), baseline.read_bytes()) == source_bytes
    assert not any(
        command[0] == "helm"
        and any(action in command for action in ("upgrade", "rollback", "uninstall"))
        for command in commands
    )


@pytest.mark.parametrize(
    ("fault", "failed_stage"),
    (
        ("revision", "live-state-and-provenance"),
        ("already-recovered", "live-state-and-provenance"),
        ("chart", "live-state-and-provenance"),
        ("description", "live-state-and-provenance"),
        ("image-tag", "live-state-and-provenance"),
        ("image-digest", "live-state-and-provenance"),
        ("pod-count", "live-state-and-provenance"),
        ("pod-readiness", "live-state-and-provenance"),
        ("secret", "live-state-and-provenance"),
        ("render", "live-state-and-provenance"),
        ("user-drift", "live-state-and-provenance"),
        ("computed-drift", "live-state-and-provenance"),
        ("invalid-chart-defaults", "live-state-and-provenance"),
        ("missing-default-image", "live-state-and-provenance"),
        ("stored-contract", "live-state-and-provenance"),
        ("runtime", "runtime-and-metrics-preflight"),
        ("metrics", "runtime-and-metrics-preflight"),
        ("provenance", "immutable-oci-provenance"),
        ("concurrent-revision", "pre-mutation-revalidation"),
        ("concurrent-pod", "pre-mutation-revalidation"),
        ("concurrent-user", "pre-mutation-revalidation"),
        ("concurrent-computed", "pre-mutation-revalidation"),
        ("concurrent-workload", "pre-mutation-revalidation"),
    ),
)
def test_production_metrics_recovery_real_path_rejections_are_linked_and_non_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    failed_stage: str,
) -> None:
    args, commands, failed, baseline, selected = recovery_execution_case(
        tmp_path, monkeypatch, fault=fault
    )
    source_bytes = (failed.read_bytes(), baseline.read_bytes())
    with pytest.raises(rollback.RollbackError):
        rollback.rollback(args, args._test_runner)
    assert not any(
        command[0] == "helm"
        and any(action in command for action in ("upgrade", "rollback", "uninstall"))
        for command in commands
    )
    assert not any(command[0] == "kubectl" and "secret" in command for command in commands)
    written = json.loads(args.evidence.read_text(encoding="utf-8"))
    assert written["failedStage"] == failed_stage
    assert written["clusterMayHaveChanged"] is False
    assert written["originalFailure"] == {
        "invocationId": "a" * 32,
        "targetManifestFingerprint": hashlib.sha256(
            manifest._canonical(selected).encode()
        ).hexdigest(),
    }
    assert "SENTINEL" not in args.evidence.read_text(encoding="utf-8")
    assert (failed.read_bytes(), baseline.read_bytes()) == source_bytes


@pytest.mark.parametrize("fault", ("post-workload", "post-policy"))
def test_production_metrics_recovery_post_upgrade_workload_drift_is_single_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    args, commands, _failed, _baseline, _selected = recovery_execution_case(
        tmp_path, monkeypatch, fault=fault
    )
    with pytest.raises(rollback.RollbackError, match="preserved evidence"):
        rollback.rollback(args, args._test_runner)
    written = json.loads(args.evidence.read_text(encoding="utf-8"))
    assert written["failedStage"] == "ownership-and-finalization-proof"
    assert written["clusterMayHaveChanged"] is True
    assert sum(command[0] == "helm" and "upgrade" in command for command in commands) == 1
    assert not any("rollback" in command or "uninstall" in command for command in commands)


@pytest.mark.parametrize(
    ("fault", "failed_stage"),
    (
        ("post-computed", "ownership-and-finalization-proof"),
        ("post-stored-contract", "ownership-and-finalization-proof"),
    ),
)
def test_production_metrics_recovery_postflight_value_failures_are_single_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    failed_stage: str,
) -> None:
    args, commands, failed, baseline, _selected = recovery_execution_case(
        tmp_path, monkeypatch, fault=fault
    )
    source_bytes = (failed.read_bytes(), baseline.read_bytes())
    with pytest.raises(rollback.RollbackError, match="preserved evidence"):
        rollback.rollback(args, args._test_runner)
    written = json.loads(args.evidence.read_text(encoding="utf-8"))
    assert written["failedStage"] == failed_stage
    assert written["clusterMayHaveChanged"] is True
    assert written["originalFailure"]["invocationId"] == "a" * 32
    assert "SENTINEL" not in args.evidence.read_text(encoding="utf-8")
    assert sum(command[0] == "helm" and "upgrade" in command for command in commands) == 1
    assert not any("rollback" in command or "uninstall" in command for command in commands)
    assert (failed.read_bytes(), baseline.read_bytes()) == source_bytes


def test_recovery_helpers_cover_optional_and_rejected_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = target()
    with pytest.raises(rollback.RollbackError, match="recovery confirmation"):
        rollback.recovery_confirmation("wrong")

    args = Namespace(
        verifier=Path("verifier"),
        environment="prod",
        smoke_runner=Path("smoke"),
        kubeconfig=Path("kubeconfig"),
        config="runtime.json",
    )
    command = rollback.runtime_verifier_command(args, selected, Path("manifest.json"))
    assert command[-2:] == ["--config", "runtime.json"]

    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("not-json", encoding="utf-8")
    with pytest.raises(rollback.RollbackError, match="unreadable"):
        rollback.failed_reconciliation(unreadable, selected)
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text("{}", encoding="utf-8")
    with pytest.raises(rollback.RollbackError, match="schema is incomplete"):
        rollback.failed_reconciliation(incomplete, selected)

    recovery_dir = tmp_path / "recovery"
    recovery_dir.mkdir()
    args, commands, _failed, _baseline, _selected = recovery_execution_case(
        recovery_dir, monkeypatch
    )
    args.verifier = tmp_path / "third-party-verifier"
    with pytest.raises(rollback.RollbackError, match="repository runtime verifier"):
        rollback.rollback(args, args._test_runner)
    assert not any("upgrade" in command for command in commands)


def test_main_validates_and_normalizes_production_recovery_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = [
        "--environment",
        "prod",
        "--evidence",
        str(tmp_path / "out.json"),
        "--verifier",
        str(tmp_path / "verifier"),
        "--production-metrics-recovery",
    ]
    with pytest.raises(SystemExit):
        rollback.main([*common, "--manifest", str(tmp_path / "manifest.json")])
    with pytest.raises(SystemExit):
        rollback.main(common)

    observed: list[Namespace] = []
    monkeypatch.setattr(rollback, "rollback", lambda args: observed.append(args) or {})
    assert rollback.main(
        [
            *common,
            "--failed-evidence", str(tmp_path / "failed.json"),
            "--maintenance-target", str(tmp_path / "target.json"),
        ]
    ) == 0
    assert observed[0].configuration_reconciliation is True
    assert observed[0].baseline_manifest == rollback.PRODUCTION_BASELINE
