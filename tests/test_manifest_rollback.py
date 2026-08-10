"""Focused fail-closed tests for DSPACE manifest rollback."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import dspace_manifest_rollback as rollback
from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64


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
    checks = sorted(manifest.required_final_checks(value)) + [
        "imagePlatformSourceRevision[0]"
    ]
    value["verificationResults"] = [
        {"check": check, "passed": True, "details": "observed"} for check in checks
    ]
    return manifest.validate(value, True)


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
        current, [pod("1")], target(), [{"path": "values.yaml", "sha256": "3" * 64}]
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
        return {
            "name": "dspace",
            "namespace": "dspace",
            "version": 8 if state_drift == "helm" and evidence.exists() else 7,
            "info": {"status": "deployed"},
            "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
        }

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


def test_configuration_reconciliation_completes_all_production_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, commands, evidence, verifier = pre_reservation_case(
        tmp_path, monkeypatch, environment="prod"
    )
    selected = target("prod", schema_version=2)
    args.manifest.write_text(manifest._canonical(selected), encoding="utf-8")
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    args.configuration_reconciliation = True
    args.kubeconfig = str(kubeconfig)
    args.confirm = f"dspace:prod:{SHA}"
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
    live = {"replicaCount": 2, "image": image}
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
            "applicationImageID": f"{manifest.IMAGE_REF}@{DIGEST}",
        }

    before_pods = [ready("1"), ready("2")]
    after_pods = [ready("3"), ready("4")]
    terminating_pods = [{**ready("2"), "terminating": True}, *after_pods]
    state = {"upgraded": False, "description": "", "post_upgrade_pod_reads": 0}
    monkeypatch.setattr(rollback.time, "sleep", lambda _seconds: None)

    def status(*_args: object) -> dict[str, object]:
        return {
            "name": "dspace",
            "namespace": "dspace",
            "version": 8 if state["upgraded"] else 7,
            "info": {
                "status": "deployed",
                "description": state["description"] if state["upgraded"] else "previous",
            },
            "chart": {"metadata": {"name": "dspace", "version": selected["chartVersion"]}},
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
        elif command[0] == "helm" and "values" in command and "get" in command:
            return json.dumps(desired if "--all" in command else live)
        elif command[0] == "helm" and "template" in command:
            return "live render" if "live-values.json" in " ".join(command) else "target render"
        elif command[0] == "helm" and "manifest" in command:
            return "live render"
        elif command[:2] == [str(verifier), "verify"]:
            return json.dumps(verifier_result(environment="prod"))
        elif command[0] == "kubectl" and (
            "replicasets,deployments" in command or "pods" in command
        ):
            return '{"items": []}'
        return ""

    result = rollback.rollback(args, runner)

    upgrade = next(command for command in commands if "upgrade" in command)
    assert upgrade[upgrade.index("--kubeconfig") + 1] == str(kubeconfig)
    assert f"oci://{manifest.CHART_REF}@{selected['chartDigest']}" in upgrade
    assert f"image.tag={selected['imageTag']}" in upgrade
    forbidden = ("--reuse-values", "--version", selected["semanticTag"], "rollback")
    assert not any(item in upgrade for item in forbidden)
    assert DIGEST not in next(item for item in upgrade if item.startswith("image.tag="))
    assert finalized["helm_stored_values_result"] is stored_proof
    assert finalized["expected_image_coordinate"] == (
        f"{manifest.IMAGE_REF}:{selected['imageTag']}"
    )
    assert result["state"] == "succeeded"
    assert result["helm"]["beforeRevision"] == 7
    assert result["helm"]["afterRevision"] == 8
    assert result["verification"]["helmStoredValues"] == stored_proof
    assert result["verification"]["runtime"]["sourceRevision"] == SHA
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


@pytest.mark.parametrize(
    ("failure", "failed_stage", "may_have_changed"),
    [
        (None, None, None),
        ("pre-mutation", "pre-mutation-revalidation", False),
        ("helm", "helm-upgrade", True),
        ("rollout", "rollout-wait", True),
        ("verifier", "runtime-verification", True),
        ("revision", "revision-stability-collection", True),
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
        return {
            "name": "dspace",
            "namespace": "dspace",
            "version": revision,
            "info": {"status": "deployed", "description": description[0]},
            "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
        }

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
            "revision": 7 if failure == "pre-mutation" else (9 if failure == "revision" else 8),
            "status": "deployed",
            "chartName": "dspace",
            "chartVersion": "3.1.0" if failure == "pre-mutation" else "3.2.0",
            "invocationDescriptionMatches": failure != "pre-mutation",
        }
        assert observed["pods"][0]["uid"] == "2"
        assert observed["pods"][0]["startTime"]
        assert observed["pods"][0]["images"]["dspace"]
        assert observed["pods"][0]["imageIDs"]["dspace"]
        assert "ownerReferences" in observed["pods"][0]
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
