"""Focused tests for fail-closed DSPACE release evidence."""

from __future__ import annotations

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
CHART_DIGEST = "sha256:" + "2" * 64
PLATFORM_DIGEST = "sha256:" + "3" * 64
IMAGE_CONFIG_DIGEST = "sha256:" + "4" * 64
CHART_CONFIG_DIGEST = "sha256:" + "5" * 64
CHART_SHA = "1234567890abcdef1234567890abcdef12345678"


def upstream() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.2.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.0",
        "chartDigest": CHART_DIGEST,
        "semanticTag": "v3.2.0",
    }


def split_upstream() -> dict[str, object]:
    value = upstream()
    value["schemaVersion"] = 2
    value["chartSourceRevision"] = CHART_SHA
    return value


def split_candidate(environment: str = "staging") -> dict[str, object]:
    return manifest.candidate(
        split_upstream(), environment, "token-place", "2026-07-26T12:00:00Z", "operator"
    )


def candidate() -> dict[str, object]:
    return manifest.candidate(
        upstream(),
        "staging",
        "token-place",
        "2026-07-26T12:00:00Z",
        "synthetic-test-approver",
    )


def test_upstream_import_is_canonical_and_round_trips(tmp_path: Path) -> None:
    source = tmp_path / "upstream.json"
    output = tmp_path / "candidate.json"
    source.write_text(json.dumps(upstream()), encoding="utf-8")
    assert (
        manifest.main(
            [
                "candidate",
                "--upstream",
                str(source),
                "--output",
                str(output),
                "--environment",
                "staging",
                "--provider",
                "token-place",
                "--approved-at",
                "2026-07-26T12:00:00Z",
                "--approved-by",
                "operator",
            ]
        )
        == 0
    )
    loaded = json.loads(output.read_text())
    assert manifest.validate(loaded) == loaded
    assert output.read_text().endswith("\n")
    assert list(loaded) == list(manifest.CANDIDATE_FIELDS)


def test_schema_v2_split_provenance_is_canonical_and_preserved() -> None:
    value = split_candidate()
    assert value["chartSourceRevision"] == CHART_SHA
    assert list(value) == list(manifest.UPSTREAM_FIELDS_V2 + manifest.CANDIDATE_SUFFIX)
    assert manifest.validate(value) == value


def test_invalid_upstream_app_fails_closed() -> None:
    value = upstream()
    value["app"] = "another-app"
    with pytest.raises(manifest.ManifestError, match="app must be 'dspace'"):
        manifest.candidate(value, "staging", "token-place", "2026-07-26T12:00:00Z", "operator")


def test_versioned_recovery_coordinates_are_exact_and_candidate_consumable() -> None:
    path = Path("docs/apps/dspace.prod-recovery-coordinates.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value == {
        "schemaVersion": 2,
        "app": "dspace",
        "applicationVersion": "3.0.1",
        "sourceRevision": "1a31a569aff2dbeb238e8c2688b9e85140d2077d",
        "chartSourceRevision": "63063e287adb92a4158ce2c8e7d378b73f52c1c5",
        "imageTag": "main-1a31a56",
        "imageDigest": "sha256:23dbc573377549136c1f10b05706b3c176ffbabaf04a3194381a24752104a401",
        "chartVersion": "3.0.2",
        "chartDigest": "sha256:8b862135e52146f301a41259d6dabb053ed891d798fc1c8c95ca775b2b8e9575",
        "semanticTag": "v3.0.1",
    }
    made = manifest.candidate(value, "prod", "openai", "2026-07-31T12:00:00Z", "operator")
    assert made["imageTag"] == "main-1a31a56"
    assert made["semanticTag"] == "v3.0.1"


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.pop("chartSourceRevision"),
        lambda value: value.update(chartSourceRevision="short"),
        lambda value: value.update(chartSourceRevision=CHART_SHA.upper()),
        lambda value: value.update(applicationSourceRevision=SHA),
        lambda value: value.update(schemaVersion=3),
    ],
)
def test_schema_v2_rejects_missing_malformed_or_unknown_provenance(change) -> None:
    value = split_upstream()
    change(value)
    with pytest.raises(manifest.ManifestError):
        manifest.candidate(value, "staging", "token-place", "2026-07-26T12:00:00Z", "operator")


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.pop("chartDigest"),
        lambda x: x.update(extra="no"),
        lambda x: x.update(sourceRevision="abc1234"),
        lambda x: x.update(sourceRevision=SHA.upper()),
        lambda x: x.update(imageTag="latest"),
        lambda x: x.update(imageTag="staging-abcdef0"),
        lambda x: x.update(imageTag="prod-abcdef0"),
        lambda x: x.update(imageTag="production-abcdef0"),
        lambda x: x.update(imageTag="latest-abcdef0"),
        lambda x: x.update(imageTag="v3.2.0"),
        lambda x: x.update(imageTag="main"),
        lambda x: x.update(imageTag="v3"),
        lambda x: x.update(imageTag="main-deadbee"),
        lambda x: x.update(imageDigest="sha256:abc"),
        lambda x: x.update(chartDigest="2" * 64),
        lambda x: x.update(chartVersion="v3.2.0"),
        lambda x: x.pop("semanticTag"),
        lambda x: x.update(semanticTag=None),
        lambda x: x.update(semanticTag="v3.2.1"),
    ],
)
def test_rejects_invalid_upstream(change) -> None:
    value = upstream()
    change(value)
    with pytest.raises(manifest.ManifestError):
        manifest.candidate(value, "staging", "token-place", "2026-07-26T12:00:00Z", "operator")


@pytest.mark.parametrize(
    "version",
    ["3.2.0-01", "3.2.0-alpha.01", "03.2.0", "3.02.0", "3.2.00"],
)
def test_rejects_non_strict_semver(version: str) -> None:
    value = upstream()
    value["applicationVersion"] = version
    value["semanticTag"] = f"v{version}"
    with pytest.raises(manifest.ManifestError, match="strict SemVer"):
        manifest.candidate(value, "staging", "token-place", "2026-07-26T12:00:00Z", "operator")


@pytest.mark.parametrize(
    "version", ["3.2.0-alpha", "3.2.0-alpha.1", "3.2.0-0", "3.2.0-0A.01a+build.01"]
)
def test_accepts_strict_semver_prerelease_and_build(version: str) -> None:
    value = upstream()
    value["applicationVersion"] = version
    value["semanticTag"] = f"v{version}"
    assert (
        manifest.candidate(value, "staging", "token-place", "2026-07-26T12:00:00Z", "operator")[
            "applicationVersion"
        ]
        == version
    )


@pytest.mark.parametrize(
    ("environment", "provider", "approver"),
    [
        ("dev", "token-place", "operator"),
        ("staging", "tokenplace", "operator"),
        ("prod", "open-ai", "operator"),
        ("prod", "openai", ""),
    ],
)
def test_rejects_wrong_enrichment(environment: str, provider: str, approver: str) -> None:
    with pytest.raises(manifest.ManifestError):
        manifest.candidate(upstream(), environment, provider, "2026-07-26T12:00:00Z", approver)


def oras_runner(*, image_revision: str = SHA, chart_revision: str = SHA):
    responses = {
        ("manifest", "fetch", "--descriptor", f"{manifest.IMAGE_REF}:main-abcdef0"): {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "digest": DIGEST,
        },
        ("manifest", "fetch", f"{manifest.IMAGE_REF}@{DIGEST}"): {
            "schemaVersion": 2,
            "manifests": [
                {"digest": PLATFORM_DIGEST, "platform": {"os": "linux", "architecture": "amd64"}}
            ],
        },
        ("manifest", "fetch", f"{manifest.IMAGE_REF}@{PLATFORM_DIGEST}"): {
            "schemaVersion": 2,
            "config": {"digest": IMAGE_CONFIG_DIGEST},
            "layers": [],
        },
        ("blob", "fetch", "--output", "-", f"{manifest.IMAGE_REF}@{IMAGE_CONFIG_DIGEST}"): {
            "config": {"Labels": {manifest.REVISION_ANNOTATION: image_revision}}
        },
        ("manifest", "fetch", "--descriptor", f"{manifest.CHART_REF}:3.2.0"): {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": CHART_DIGEST,
        },
        ("manifest", "fetch", f"{manifest.CHART_REF}@{CHART_DIGEST}"): {
            "schemaVersion": 2,
            "config": {"digest": CHART_CONFIG_DIGEST},
            "layers": [],
        },
        ("blob", "fetch", "--output", "-", f"{manifest.CHART_REF}@{CHART_CONFIG_DIGEST}"): {
            "annotations": {manifest.REVISION_ANNOTATION: chart_revision}
        },
    }
    calls = []

    def run(command):
        calls.append(command)
        return json.dumps(responses[tuple(command[1:])])

    run.calls = calls
    return run


def test_preflight_checks_exact_descriptors_and_digest_qualified_metadata() -> None:
    runner = oras_runner()
    results = manifest.preflight(
        candidate(), manifest.IMAGE_REF, "oci://" + manifest.CHART_REF, "oras-stub", runner=runner
    )
    assert [item["check"] for item in results] == [
        "imageDigest",
        "chartDigest",
        "chartSourceRevision",
        "imagePlatformSourceRevision[0]",
    ]
    assert runner.calls[0][-1].endswith(":main-abcdef0")
    assert runner.calls[1][-1] == f"{manifest.IMAGE_REF}@{DIGEST}"
    assert all(":main-abcdef0" not in call[-1] for call in runner.calls[1:])
    blob_fetches = [call for call in runner.calls if call[1:3] == ["blob", "fetch"]]
    assert [call[1:5] for call in blob_fetches] == [
        ["blob", "fetch", "--output", "-"],
        ["blob", "fetch", "--output", "-"],
    ]
    assert {call[-1] for call in blob_fetches} == {
        f"{manifest.IMAGE_REF}@{IMAGE_CONFIG_DIGEST}",
        f"{manifest.CHART_REF}@{CHART_CONFIG_DIGEST}",
    }


def test_schema_v2_preflight_checks_image_and_chart_provenance_independently() -> None:
    results = manifest.preflight(
        split_candidate(),
        manifest.IMAGE_REF,
        manifest.CHART_REF,
        "oras",
        runner=oras_runner(image_revision=SHA, chart_revision=CHART_SHA),
    )
    assert next(item for item in results if item["check"] == "chartSourceRevision")["passed"]
    with pytest.raises(manifest.ManifestError, match="chartSourceRevision"):
        manifest.preflight(
            split_candidate(),
            manifest.IMAGE_REF,
            manifest.CHART_REF,
            "oras",
            runner=oras_runner(image_revision=CHART_SHA, chart_revision=SHA),
        )


@pytest.mark.parametrize(
    ("image_revision", "chart_revision"),
    [
        ("0" * 40, SHA),
        (SHA, "0" * 40),
    ],
)
def test_preflight_mismatch_fails(image_revision, chart_revision) -> None:
    with pytest.raises(manifest.ManifestError, match="mismatch"):
        manifest.preflight(
            candidate(),
            manifest.IMAGE_REF,
            manifest.CHART_REF,
            "oras",
            runner=oras_runner(image_revision=image_revision, chart_revision=chart_revision),
        )


def test_preflight_rejects_noncanonical_deployed_chart() -> None:
    with pytest.raises(manifest.ManifestError, match="chart reference"):
        manifest.preflight(
            candidate(),
            manifest.IMAGE_REF,
            "oci://example.invalid/dspace",
            "oras",
            runner=oras_runner(),
        )


def pod(name: str, digest: str = DIGEST) -> dict[str, object]:
    return {
        "metadata": {
            "name": name,
            "uid": f"{name}-uid",
            "labels": {
                "app.kubernetes.io/name": "dspace",
                "app.kubernetes.io/instance": "dspace",
            },
            "ownerReferences": [
                {"kind": "ReplicaSet", "name": "dspace-rs", "uid": "rs-uid", "controller": True}
            ],
        },
        "spec": {"containers": [{"name": "dspace", "image": f"{manifest.IMAGE_REF}:main-abcdef0"}]},
        "status": {
            "phase": "Running",
            "startTime": "2026-07-26T12:01:00Z",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [
                {
                    "name": "dspace",
                    "imageID": "ghcr.io/democratizedspace/dspace@" + digest,
                    "state": {"running": {"startedAt": "2026-07-26T12:01:00Z"}},
                }
            ],
        },
    }


def helm_status(**changes) -> dict[str, object]:
    value = {
        "name": "dspace",
        "namespace": "dspace",
        "version": 17,
        "info": {
            "status": "deployed",
            "description": "sugarkube-release-manifest:test-reservation",
        },
        "chart": {"metadata": {"name": "dspace", "version": "3.2.0"}},
    }
    value.update(changes)
    return value


def workloads() -> dict[str, object]:
    labels = {
        "app.kubernetes.io/name": "dspace",
        "app.kubernetes.io/instance": "dspace",
    }
    helm_labels = {**labels, "app.kubernetes.io/managed-by": "Helm"}
    return {
        "items": [
            {
                "kind": "ReplicaSet",
                "metadata": {
                    "name": "dspace-rs",
                    "uid": "rs-uid",
                    "labels": labels,
                    "ownerReferences": [
                        {
                            "kind": "Deployment",
                            "name": "dspace",
                            "uid": "deploy-uid",
                            "controller": True,
                        }
                    ],
                },
            },
            {
                "kind": "Deployment",
                "metadata": {
                    "name": "dspace",
                    "uid": "deploy-uid",
                    "labels": helm_labels,
                    "annotations": {
                        "meta.helm.sh/release-name": "dspace",
                        "meta.helm.sh/release-namespace": "dspace",
                    },
                },
            },
        ]
    }


def finalize(**changes):
    arguments = {
        "value": candidate(),
        "helm_json": helm_status(),
        "pods_json": {"items": [pod("dspace-b"), pod("dspace-a")]},
        "workloads_json": workloads(),
        "preflight_results": manifest.preflight(
            candidate(), manifest.IMAGE_REF, manifest.CHART_REF, "oras", runner=oras_runner()
        ),
        "environment": "staging",
        "image_tag": "main-abcdef0",
        "chart_version": "3.2.0",
        "release": "dspace",
        "namespace": "dspace",
        "cluster_environment": "staging",
        "invocation_description": "sugarkube-release-manifest:test-reservation",
    }
    arguments.update(changes)
    return manifest.finalize(**arguments)


def runtime_proof(**changes) -> dict[str, object]:
    proof = {
        "schemaVersion": 1,
        "environment": "staging",
        "release": "dspace",
        "namespace": "dspace",
        "applicationVersion": "3.2.0",
        "runtimeSourceRevision": SHA,
        "frontendSourceRevision": SHA,
        "defaultProvider": "token-place",
        "journeys": [
            {"name": "/build-info.json", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }
    proof.update(changes)
    return proof


def runtime_final(**proof_changes) -> dict[str, object]:
    return finalize(runtime_verification=runtime_proof(**proof_changes))


def test_finalize_collects_sorted_multi_pod_identity() -> None:
    final = finalize()
    assert final["helmRevision"] == 17
    assert [item["name"] for item in final["pods"]] == ["dspace-a", "dspace-b"]
    assert final["runtimeSourceRevision"] == SHA
    assert final["runtimeSourceRevisionMethod"] == "podImageID+ociRevisionAnnotation"
    assert {item["check"] for item in final["verificationResults"]} >= {
        "selectedCoordinates",
        "clusterEnvironment",
        "helmRelease",
        "installedChart",
        "releaseOwnershipAndReadiness",
        "podImageCoordinates",
        "podImageDigests",
    }


def test_finalize_optional_digest_coordinate_is_backward_compatible() -> None:
    assert finalize()["recordType"] == "final"
    coordinate = f"{manifest.IMAGE_REF}:main-abcdef0@{DIGEST}"
    selected_pods = {"items": [pod("dspace-a")]}
    selected_pods["items"][0]["spec"]["containers"][0]["image"] = coordinate
    assert (
        finalize(pods_json=selected_pods, expected_image_coordinate=coordinate)["recordType"]
        == "final"
    )


def test_generated_final_record_validates_through_cli(tmp_path: Path) -> None:
    output = tmp_path / "final.json"
    output.write_text(manifest._canonical(finalize()), encoding="utf-8")
    assert manifest.main(["validate", "--manifest", str(output), "--final"]) == 0


def test_runtime_proof_and_complete_runtime_checks_validate() -> None:
    value = runtime_final()
    assert manifest.validate(value, True) == value
    assert manifest.RUNTIME_VERIFICATION_CHECKS <= {
        result["check"] for result in value["verificationResults"]
    }


@pytest.mark.parametrize("schema_version", [True, False, 0, 2, "1"])
def test_runtime_proof_requires_exact_schema_version(schema_version) -> None:
    with pytest.raises(manifest.ManifestError, match="schemaVersion"):
        runtime_final(schemaVersion=schema_version)


@pytest.mark.parametrize("field", manifest.RUNTIME_VERIFICATION_FIELDS)
def test_runtime_proof_rejects_missing_fields(field: str) -> None:
    value = runtime_final()
    value["runtimeVerification"].pop(field)
    with pytest.raises(manifest.ManifestError, match="incompatible verifier schema"):
        manifest.validate(value, True)


def test_runtime_proof_rejects_unknown_fields() -> None:
    value = runtime_final()
    value["runtimeVerification"]["unexpected"] = "field"
    with pytest.raises(manifest.ManifestError, match="incompatible verifier schema"):
        manifest.validate(value, True)


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("environment", "prod"),
        ("release", "other"),
        ("namespace", "other"),
        ("applicationVersion", "3.2.1"),
        ("runtimeSourceRevision", "0" * 40),
        ("frontendSourceRevision", "0" * 40),
        ("defaultProvider", "openai"),
    ],
)
def test_runtime_proof_rejects_coordinate_mismatches(field: str, wrong: str) -> None:
    with pytest.raises(manifest.ManifestError, match="does not match approved release"):
        runtime_final(**{field: wrong})


@pytest.mark.parametrize(
    "journeys",
    [
        [],
        ["/chat"],
        [{"name": "/chat", "passed": True, "extra": True}],
        [{"name": "chat", "passed": True}],
        [{"name": "/bad path", "passed": True}],
        [{"name": "/chat", "passed": True}, {"name": "/chat", "passed": True}],
        [{"name": "/chat", "passed": False}],
        [{"name": "/", "passed": True}],
    ],
)
def test_runtime_proof_rejects_invalid_journeys(journeys) -> None:
    with pytest.raises(manifest.ManifestError, match="successful bounded journeys"):
        runtime_final(journeys=journeys)


def test_runtime_checks_require_corresponding_proof() -> None:
    value = finalize()
    value["verificationResults"].append(
        {"check": "runtimeIdentity", "passed": True, "details": "unproven"}
    )
    with pytest.raises(manifest.ManifestError, match="require runtimeVerification proof"):
        manifest.validate(value, True)


def test_runtime_proof_requires_every_runtime_check() -> None:
    value = runtime_final()
    value["verificationResults"] = [
        result for result in value["verificationResults"] if result["check"] != "remoteChatSmoke"
    ]
    with pytest.raises(manifest.ManifestError, match="missing runtime verification results"):
        manifest.validate(value, True)


def test_backward_compatible_historical_final_without_runtime_proof() -> None:
    value = finalize()
    assert "runtimeVerification" not in value
    assert manifest.validate(value, True) == value


def prod_candidate() -> dict[str, object]:
    value = candidate()
    value["environment"] = "prod"
    return value


def test_staging_gate_returns_revision_despite_approval_metadata_difference() -> None:
    production = prod_candidate()
    production.update(approvedAt="2026-07-27T12:00:00Z", approvedBy="production-approver")
    assert manifest.staging_gate(production, runtime_final()) == 17


def test_schema_v2_finalization_and_staging_gate_preserve_chart_provenance() -> None:
    staging = split_candidate()
    final = finalize(
        value=staging,
        preflight_results=manifest.preflight(
            staging,
            manifest.IMAGE_REF,
            manifest.CHART_REF,
            "oras",
            runner=oras_runner(image_revision=SHA, chart_revision=CHART_SHA),
        ),
        runtime_verification=runtime_proof(),
        helm_stored_values_result=manifest.verify_helm_stored_values(
            staging,
            {
                "image": {
                    "repository": manifest.IMAGE_REF,
                    "tag": staging["imageTag"],
                    "pullPolicy": "Always",
                }
            },
            "staging",
        ),
    )
    assert final["chartSourceRevision"] == CHART_SHA
    assert manifest.staging_gate(split_candidate("prod"), final) == 17
    production = split_candidate("prod")
    production["chartSourceRevision"] = "0" * 40
    with pytest.raises(manifest.ManifestError, match="coordinates differ"):
        manifest.staging_gate(production, final)


def test_schema_v2_requires_and_round_trips_helm_stored_values_check() -> None:
    value = split_candidate()
    with pytest.raises(manifest.ManifestError, match="Helm stored-values verification"):
        finalize(value=value)
    final = finalize(
        value=value,
        helm_stored_values_result=manifest.verify_helm_stored_values(
            value,
            {
                "image": {
                    "repository": manifest.IMAGE_REF,
                    "tag": value["imageTag"],
                    "pullPolicy": "Always",
                }
            },
            "staging",
        ),
    )
    assert manifest.validate(json.loads(manifest._canonical(final)), True) == final


@pytest.mark.parametrize("stored_values", [[], None, "not-an-object"])
def test_helm_stored_values_reject_non_object_values(stored_values: object) -> None:
    with pytest.raises(manifest.ManifestError, match="must be a JSON object"):
        manifest.verify_helm_stored_values(split_candidate("prod"), stored_values, "prod")


@pytest.mark.parametrize("image", [None, "not-an-object", []])
def test_helm_stored_values_reject_missing_or_non_object_image(image: object) -> None:
    stored_values = {} if image is None else {"image": image}
    with pytest.raises(manifest.ManifestError, match="stored image values"):
        manifest.verify_helm_stored_values(split_candidate("prod"), stored_values, "prod")


@pytest.mark.parametrize(
    ("field", "wrong"),
    [("repository", "example.invalid/dspace"), ("tag", "v3.2.0"), ("pullPolicy", "IfNotPresent")],
)
def test_helm_stored_values_reject_image_mismatch(field: str, wrong: str) -> None:
    value = split_candidate("prod")
    image = {"repository": manifest.IMAGE_REF, "tag": value["imageTag"], "pullPolicy": "Always"}
    image[field] = wrong
    with pytest.raises(manifest.ManifestError, match="stored image values"):
        manifest.verify_helm_stored_values(value, {"image": image}, "prod")


@pytest.mark.parametrize(
    "leak",
    [
        {"metrics": {"enabled": True}},
        {"serviceMonitor": {"enabled": True}},
        {"metrics": {"auth": {"existingSecret": "dspace-staging-metrics-token"}}},
        {"additionalEnv": [{"value": "dspace-staging-metrics-token"}]},
    ],
)
def test_helm_stored_values_reject_production_staging_leaks_secret_safely(
    leak: dict[str, object],
) -> None:
    value = split_candidate("prod")
    stored = {
        "image": {
            "repository": manifest.IMAGE_REF,
            "tag": value["imageTag"],
            "pullPolicy": "Always",
        },
        **leak,
    }
    with pytest.raises(manifest.ManifestError, match="staging-only settings") as raised:
        manifest.verify_helm_stored_values(value, stored, "prod")
    assert "dspace-staging-metrics-token" not in str(raised.value)


@pytest.mark.parametrize(
    "field",
    [
        "applicationVersion",
        "sourceRevision",
        "imageTag",
        "imageDigest",
        "chartVersion",
        "chartDigest",
        "semanticTag",
        "expectedDefaultChatProvider",
    ],
)
def test_staging_gate_compares_every_immutable_coordinate(field: str) -> None:
    production = prod_candidate()
    production[field] = "mismatch"
    with pytest.raises(manifest.ManifestError):
        manifest.staging_gate(production, runtime_final())


def test_staging_gate_rejects_wrong_environments_and_candidate_evidence() -> None:
    with pytest.raises(manifest.ManifestError, match="requires prod candidate"):
        manifest.staging_gate(candidate(), runtime_final())
    production_evidence = runtime_final()
    production_evidence["environment"] = "prod"
    production_evidence["runtimeVerification"]["environment"] = "prod"
    assert manifest.validate(production_evidence, True) == production_evidence
    with pytest.raises(manifest.ManifestError, match="requires prod candidate"):
        manifest.staging_gate(prod_candidate(), production_evidence)
    with pytest.raises(manifest.ManifestError):
        manifest.staging_gate(prod_candidate(), candidate())


def test_staging_gate_requires_runtime_proof_but_historical_final_stays_valid() -> None:
    historical = finalize()
    assert manifest.validate(historical, True) == historical
    with pytest.raises(manifest.ManifestError, match="mandatory runtime verification"):
        manifest.staging_gate(prod_candidate(), historical)


def test_staging_gate_rejects_malformed_or_release_mismatched_runtime_proof() -> None:
    malformed = runtime_final()
    malformed["runtimeVerification"]["journeys"] = []
    with pytest.raises(manifest.ManifestError, match="bounded journeys"):
        manifest.staging_gate(prod_candidate(), malformed)

    mismatched = runtime_final()
    mismatched["runtimeVerification"]["release"] = "other"
    with pytest.raises(manifest.ManifestError, match="approved release"):
        manifest.staging_gate(prod_candidate(), mismatched)


def _replace_results(value, checks):
    value["verificationResults"] = [
        {"check": check, "passed": True, "details": "observed"} for check in checks
    ]
    return value


def test_final_validation_rejects_arbitrary_only_result() -> None:
    with pytest.raises(manifest.ManifestError, match="unknown verification"):
        manifest.validate(_replace_results(finalize(), ["inventedCheck"]), True)


@pytest.mark.parametrize("missing", sorted(manifest.FINAL_FIXED_CHECKS))
def test_final_validation_requires_every_fixed_check(missing: str) -> None:
    value = finalize()
    value["verificationResults"] = [
        result for result in value["verificationResults"] if result["check"] != missing
    ]
    with pytest.raises(manifest.ManifestError, match="missing verification"):
        manifest.validate(value, True)


@pytest.mark.parametrize("invalid", ["unknown", "imagePlatformSourceRevision[x]"])
def test_final_validation_rejects_unknown_or_malformed_checks(invalid: str) -> None:
    value = finalize()
    value["verificationResults"].append({"check": invalid, "passed": True, "details": "fabricated"})
    with pytest.raises(manifest.ManifestError, match="unknown verification"):
        manifest.validate(value, True)


def test_final_validation_rejects_duplicate_and_gapped_platform_checks() -> None:
    value = finalize()
    value["verificationResults"].append(dict(value["verificationResults"][0]))
    with pytest.raises(manifest.ManifestError, match="duplicate verification"):
        manifest.validate(value, True)

    value = finalize()
    platform = next(
        result
        for result in value["verificationResults"]
        if result["check"].startswith("imagePlatformSourceRevision")
    )
    platform["check"] = "imagePlatformSourceRevision[1]"
    with pytest.raises(manifest.ManifestError, match="contiguous from zero"):
        manifest.validate(value, True)


def test_final_validation_requires_platform_check() -> None:
    value = finalize()
    value["verificationResults"] = [
        result
        for result in value["verificationResults"]
        if not result["check"].startswith("imagePlatformSourceRevision")
    ]
    with pytest.raises(manifest.ManifestError, match="at least one image platform"):
        manifest.validate(value, True)


@pytest.mark.parametrize(
    "change",
    [
        lambda result: result.update(passed=False),
        lambda result: result.update(details=""),
        lambda result: result.update(check=1),
        lambda result: result.update(extra="field"),
    ],
)
def test_final_validation_rejects_non_passing_or_malformed_results(change) -> None:
    value = finalize()
    change(value["verificationResults"][0])
    with pytest.raises(manifest.ManifestError):
        manifest.validate(value, True)


def test_finalize_rejects_pod_image_mismatch() -> None:
    with pytest.raises(manifest.ManifestError, match="does not match"):
        finalize(pods_json={"items": [pod("dspace-a", "sha256:" + "9" * 64)]})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"environment": "prod"}, "selected environment"),
        ({"image_tag": "main-deadbee"}, "selected imageTag"),
        ({"chart_version": "3.2.1"}, "selected chartVersion"),
        ({"cluster_environment": "prod"}, "cluster environment"),
        ({"helm_json": helm_status(name="other")}, "release and namespace"),
        ({"helm_json": helm_status(info={"status": "failed"})}, "must be deployed"),
        (
            {
                "helm_json": helm_status(
                    info={"status": "deployed", "description": "another invocation"}
                )
            },
            "description",
        ),
        (
            {"helm_json": helm_status(chart={"metadata": {"name": "other", "version": "3.2.0"}})},
            "chart identity",
        ),
        ({"helm_json": helm_status(chart={})}, "chart identity"),
    ],
)
def test_finalize_rejects_unbound_coordinates_and_helm_state(changes, message) -> None:
    with pytest.raises(manifest.ManifestError, match=message):
        finalize(**changes)


@pytest.mark.parametrize(
    "failure", ["wrong-instance", "owner", "terminating", "phase", "ready", "image", "container"]
)
def test_finalize_rejects_unowned_or_non_serving_pods(failure: str) -> None:
    item = pod("dspace-a")
    if failure == "wrong-instance":
        item["metadata"]["labels"]["app.kubernetes.io/instance"] = "other"
    elif failure == "owner":
        item["metadata"]["ownerReferences"][0]["uid"] = "wrong"
    elif failure == "terminating":
        item["metadata"]["deletionTimestamp"] = "2026-07-26T12:02:00Z"
    elif failure == "phase":
        item["status"]["phase"] = "Pending"
    elif failure == "ready":
        item["status"]["conditions"][0]["status"] = "False"
    elif failure == "image":
        item["spec"]["containers"][0]["image"] = f"{manifest.IMAGE_REF}:main-deadbee"
    else:
        item["status"]["containerStatuses"][0]["state"] = {"waiting": {}}
    with pytest.raises(manifest.ManifestError):
        finalize(pods_json={"items": [item]})


def test_finalize_rejects_workload_not_owned_by_helm() -> None:
    discovered = workloads()
    discovered["items"][1]["metadata"]["annotations"]["meta.helm.sh/release-name"] = "other"
    with pytest.raises(manifest.ManifestError, match="not owned"):
        finalize(workloads_json=discovered)


def test_atomic_write_refuses_overwrite_and_leaves_no_temporary_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "record.json"
    manifest._write_new(output, candidate())
    original = output.read_bytes()
    with pytest.raises(manifest.ManifestError, match="overwrite"):
        manifest._write_new(output, candidate())
    assert output.read_bytes() == original
    assert list(tmp_path.iterdir()) == [output]


def test_record_excludes_tokens_and_secrets() -> None:
    encoded = json.dumps(candidate()).lower()
    assert "token" not in encoded.replace("token-place", "")
    assert "secret" not in encoded and "credential" not in encoded


def test_finalize_requires_preflight_results() -> None:
    with pytest.raises(manifest.ManifestError, match="fresh OCI preflight"):
        finalize(preflight_results=[])


def test_check_output_rejects_collision_before_deployment(tmp_path: Path, capsys) -> None:
    output = tmp_path / "existing.json"
    output.write_text("already recorded", encoding="utf-8")
    assert manifest.main(["check-output", "--output", str(output)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err


def test_reservation_is_atomic_and_bound_to_owner(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    barrier = threading.Barrier(2)

    def acquire() -> tuple[str, str]:
        barrier.wait()
        try:
            return (
                "owner",
                manifest.reserve(output, candidate(), "staging", "dspace", "dspace"),
            )
        except manifest.ManifestError as exc:
            return ("loser", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: acquire(), range(2)))

    owners = [value for status, value in results if status == "owner"]
    assert len(owners) == 1
    assert [status for status, _ in results].count("loser") == 1
    sidecar = manifest.verify_reservation(
        output, candidate(), "staging", "dspace", "dspace", owners[0]
    )
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["output"] == str(output.resolve())
    assert metadata["candidateFingerprint"] == manifest._candidate_fingerprint(candidate())


def test_reservation_rejects_existing_record_or_reservation(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    owner = manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    with pytest.raises(manifest.ManifestError, match="already reserved"):
        manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    with pytest.raises(manifest.ManifestError, match="ownership"):
        manifest.verify_reservation(
            output, candidate(), "staging", "dspace", "dspace", owner + "wrong"
        )
    manifest.reservation_path(output).unlink()
    output.write_text("final", encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match="overwrite"):
        manifest.reserve(output, candidate(), "staging", "dspace", "dspace")


def test_reservation_binds_candidate_output_and_coordinates(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    owner = manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    changed = candidate()
    changed["approvedBy"] = "another-approver"
    for selected_output, selected, release in (
        (tmp_path / "other.json", candidate(), "dspace"),
        (output, changed, "dspace"),
        (output, candidate(), "other"),
    ):
        with pytest.raises(manifest.ManifestError):
            manifest.verify_reservation(
                selected_output, selected, "staging", release, "dspace", owner
            )


def test_post_reservation_failure_preserves_ownership(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    output = tmp_path / "evidence.json"
    source.write_text(manifest._canonical(candidate()), encoding="utf-8")
    owner = manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    monkeypatch.setattr(
        manifest,
        "preflight",
        lambda *args, **kwargs: (_ for _ in ()).throw(manifest.ManifestError("OCI failed")),
    )
    assert (
        manifest.main(
            [
                "finalize",
                "--manifest",
                str(source),
                "--output",
                str(output),
                "--environment",
                "staging",
                "--image-tag",
                "main-abcdef0",
                "--chart-version",
                "3.2.0",
                "--kubeconfig",
                "kubeconfig",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
                "--reservation",
                owner,
            ]
        )
        == 2
    )
    assert not output.exists()
    assert manifest.reservation_path(output).exists()


@pytest.mark.parametrize("schema_version", [1, 2])
def test_finalize_cli_collects_bound_evidence_before_consuming_reservation(
    tmp_path: Path, monkeypatch, schema_version: int
) -> None:
    source = tmp_path / "candidate.json"
    output = tmp_path / "evidence.json"
    selected = split_candidate() if schema_version == 2 else candidate()
    source.write_text(manifest._canonical(selected), encoding="utf-8")
    owner = manifest.reserve(output, selected, "staging", "dspace", "dspace")
    sidecar = manifest.reservation_path(output)
    oci_results = manifest.preflight(
        selected,
        manifest.IMAGE_REF,
        manifest.CHART_REF,
        "oras",
        runner=oras_runner(chart_revision=CHART_SHA if schema_version == 2 else SHA),
    )
    events = []

    def preflight(*args, **kwargs):
        events.append("oci-preflight")
        assert args[1:] == (
            manifest.IMAGE_REF,
            manifest.CHART_REF,
            "oras",
            "staging",
            "main-abcdef0",
            "3.2.0",
        )
        return oci_results

    pod_reads = 0

    def run(command):
        nonlocal pod_reads
        if "cluster_identity.py" in " ".join(command):
            events.append("cluster-identity")
            return "staging\n"
        if command[0] == "helm":
            if "get" in command:
                events.append("helm-stored-values")
                return json.dumps(
                    {
                        "image": {
                            "repository": manifest.IMAGE_REF,
                            "tag": selected["imageTag"],
                            "pullPolicy": "Always",
                        }
                    }
                )
            events.append("helm-status")
            return json.dumps(
                helm_status(
                    info={
                        "status": "deployed",
                        "description": f"sugarkube-release-manifest:{owner}",
                    }
                )
            )
        resource = command[command.index("get") + 1]
        if resource == "pods":
            events.append("pod-discovery")
            pod_reads += 1
            if pod_reads == 1:
                old = pod("dspace-old")
                old["metadata"]["deletionTimestamp"] = "2026-07-26T12:02:00Z"
                return json.dumps({"items": [pod("dspace-b"), old]})
            return json.dumps({"items": [pod("dspace-b"), pod("dspace-a")]})
        assert resource == "replicasets,deployments"
        events.append("workload-discovery")
        return json.dumps(workloads())

    write_new = manifest._write_new

    def atomic_write(path, value):
        events.append("atomic-final-write")
        assert sidecar.exists()
        write_new(path, value)
        assert sidecar.exists()

    monkeypatch.setattr(manifest, "preflight", preflight)
    monkeypatch.setattr(manifest, "_run", run)
    monkeypatch.setattr(manifest, "_write_new", atomic_write)
    monkeypatch.setattr(manifest.time, "sleep", lambda seconds: None)

    assert (
        manifest.main(
            [
                "finalize",
                "--manifest",
                str(source),
                "--output",
                str(output),
                "--environment",
                "staging",
                "--image-tag",
                "main-abcdef0",
                "--chart-version",
                "3.2.0",
                "--kubeconfig",
                "kubeconfig",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
                "--reservation",
                owner,
            ]
        )
        == 0
    )
    expected_events = [
        "oci-preflight",
        "cluster-identity",
        "helm-status",
    ]
    if schema_version == 2:
        expected_events.append("helm-stored-values")
    expected_events += [
        "pod-discovery",
        "pod-discovery",
        "helm-status",
        "workload-discovery",
        "helm-status",
        "atomic-final-write",
    ]
    assert events == expected_events
    final = manifest.validate(json.loads(output.read_text(encoding="utf-8")), True)
    assert final["helmRevision"] == 17
    assert [item["name"] for item in final["pods"]] == ["dspace-a", "dspace-b"]
    checks = {item["check"] for item in final["verificationResults"]}
    assert ("helmStoredValues" in checks) is (schema_version == 2)
    assert not sidecar.exists()


@pytest.mark.parametrize("failure", ["timeout", "command"])
def test_finalize_cli_settling_failure_preserves_reservation(
    tmp_path: Path, monkeypatch, failure: str
) -> None:
    source = tmp_path / "candidate.json"
    output = tmp_path / "evidence.json"
    source.write_text(manifest._canonical(candidate()), encoding="utf-8")
    owner = manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    old = pod("dspace-old")
    old["metadata"]["deletionTimestamp"] = "2026-07-26T12:02:00Z"
    clock = iter([0.0, 0.0, 61.0])

    monkeypatch.setattr(manifest, "preflight", lambda *args, **kwargs: [])
    monkeypatch.setattr(manifest.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(manifest.time, "sleep", lambda seconds: None)

    def run(command):
        if "cluster_identity.py" in " ".join(command):
            return "staging\n"
        if command[0] == "helm":
            return json.dumps(
                helm_status(
                    info={
                        "status": "deployed",
                        "description": f"sugarkube-release-manifest:{owner}",
                    }
                )
            )
        if failure == "command":
            raise manifest.ManifestError("pod discovery failed")
        return json.dumps({"items": [old]})

    monkeypatch.setattr(manifest, "_run", run)
    args = [
        "finalize",
        "--manifest",
        str(source),
        "--output",
        str(output),
        "--environment",
        "staging",
        "--image-tag",
        "main-abcdef0",
        "--chart-version",
        "3.2.0",
        "--kubeconfig",
        "kubeconfig",
        "--release",
        "dspace",
        "--namespace",
        "dspace",
        "--reservation",
        owner,
    ]
    assert manifest.main(args) == 2
    assert not output.exists()
    assert manifest.reservation_path(output).exists()


@pytest.mark.parametrize("changed_field", ["version", "description"])
def test_finalize_cli_rejects_changed_helm_binding_and_preserves_reservation(
    tmp_path: Path, monkeypatch, changed_field: str
) -> None:
    source = tmp_path / "candidate.json"
    output = tmp_path / "evidence.json"
    source.write_text(manifest._canonical(candidate()), encoding="utf-8")
    owner = manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    description = f"sugarkube-release-manifest:{owner}"
    status_reads = 0

    oci_results = manifest.preflight(
        candidate(), manifest.IMAGE_REF, manifest.CHART_REF, "oras", runner=oras_runner()
    )
    monkeypatch.setattr(
        manifest,
        "preflight",
        lambda *args, **kwargs: oci_results,
    )

    def run(command):
        nonlocal status_reads
        if "cluster_identity.py" in " ".join(command):
            return "staging\n"
        if command[0] == "helm":
            status_reads += 1
            info = {"status": "deployed", "description": description}
            status = helm_status(info=info)
            if status_reads == 2:
                if changed_field == "version":
                    status["version"] = 18
                else:
                    status["info"]["description"] = "another invocation"
            return json.dumps(status)
        resource = command[command.index("get") + 1]
        return json.dumps({"items": [pod("dspace-a")]} if resource == "pods" else workloads())

    monkeypatch.setattr(manifest, "_run", run)
    args = [
        "finalize",
        "--manifest",
        str(source),
        "--output",
        str(output),
        "--environment",
        "staging",
        "--image-tag",
        "main-abcdef0",
        "--chart-version",
        "3.2.0",
        "--kubeconfig",
        "kubeconfig",
        "--release",
        "dspace",
        "--namespace",
        "dspace",
        "--reservation",
        owner,
    ]
    assert manifest.main(args) == 2
    assert not output.exists()
    assert manifest.reservation_path(output).exists()


def test_public_read_only_and_reservation_dispatch(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "candidate.json"
    output = tmp_path / "evidence.json"
    source.write_text(manifest._canonical(candidate()), encoding="utf-8")
    real_preflight = manifest.preflight
    preflight_calls = []

    def checked_preflight(*args, **kwargs):
        preflight_calls.append(args)
        return real_preflight(*args, **kwargs, runner=oras_runner())

    oci_results = checked_preflight(candidate(), manifest.IMAGE_REF, manifest.CHART_REF, "oras")
    preflight_calls.clear()
    monkeypatch.setattr(manifest, "preflight", checked_preflight)

    assert (
        manifest.main(
            [
                "preflight",
                "--manifest",
                str(source),
                "--environment",
                "staging",
                "--image-tag",
                "main-abcdef0",
                "--chart-version",
                "3.2.0",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == oci_results

    assert (
        manifest.main(
            [
                "preflight",
                "--manifest",
                str(source),
                "--environment",
                "staging",
                "--image-tag",
                "main-abcdef0",
                "--chart-version",
                "3.2.0",
                "--print-chart-coordinate",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == f"oci://{manifest.CHART_REF}@{CHART_DIGEST}\n"
    assert len(preflight_calls) == 2

    assert manifest.main(["evidence-path", "--manifest", str(source)]) == 0
    assert capsys.readouterr().out.strip() == str(manifest.evidence_path(candidate()))

    assert (
        manifest.main(
            [
                "reserve",
                "--manifest",
                str(source),
                "--output",
                str(output),
                "--environment",
                "staging",
                "--release",
                "dspace",
                "--namespace",
                "dspace",
            ]
        )
        == 0
    )
    owner = capsys.readouterr().out.strip()
    assert owner
    assert manifest.verify_reservation(
        output, candidate(), "staging", "dspace", "dspace", owner
    ) == manifest.reservation_path(output)


def test_preflight_chart_coordinate_is_not_printed_after_failed_validation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source = tmp_path / "candidate.json"
    invalid = candidate()
    invalid["chartDigest"] = "sha256:" + "9" * 64
    source.write_text(manifest._canonical(invalid), encoding="utf-8")
    real_preflight = manifest.preflight
    monkeypatch.setattr(
        manifest,
        "preflight",
        lambda *args, **kwargs: real_preflight(*args, **kwargs, runner=oras_runner()),
    )
    assert manifest.main(["preflight", "--manifest", str(source), "--print-chart-coordinate"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "chartDigest" in captured.err


def test_default_evidence_path_is_stable_and_approval_unique() -> None:
    assert str(manifest.evidence_path(candidate())) == (
        "deployment-evidence/dspace/staging/main-abcdef0-20260726T120000Z.json"
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(schemaVersion=3), "schemaVersion"),
        (lambda value: value.update(recordType="final"), "recordType"),
        (lambda value: value.update(approvedAt=1), "approvedAt"),
        (lambda value: value.update(approvedAt="2026-02-30T12:00:00Z"), "valid UTC"),
    ],
)
def test_candidate_validation_rejects_malformed_schema(change, message) -> None:
    value = candidate()
    change(value)
    with pytest.raises(manifest.ManifestError, match=message):
        manifest.validate(value, False)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(helmRevision=True), "positive integer"),
        (lambda value: value.update(pods=[]), "non-empty list"),
        (lambda value: value.update(pods=["pod"]), "pod must be an object"),
        (lambda value: value["pods"][0].update(name=""), "non-empty strings"),
        (lambda value: value["pods"].append(dict(value["pods"][0])), "unique"),
        (lambda value: value.update(runtimeSourceRevision="0" * 40), "must match"),
        (lambda value: value.update(runtimeSourceRevisionMethod="invented"), "must be"),
        (lambda value: value.update(verificationResults=[]), "non-empty list"),
        (lambda value: value.update(verificationResults=["result"]), "must be objects"),
    ],
)
def test_final_validation_rejects_malformed_runtime_schema(change, message) -> None:
    value = finalize()
    change(value)
    with pytest.raises(manifest.ManifestError, match=message):
        manifest.validate(value, True)


def test_reservation_failure_cleanup_and_directory_sync_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(manifest.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    assert not manifest.reservation_path(output).exists()

    monkeypatch.setattr(
        manifest.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())
    )
    manifest._sync_directory(tmp_path)


def test_reservation_rejects_environment_and_late_output_collision(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    with pytest.raises(manifest.ManifestError, match="environment"):
        manifest.reserve(output, candidate(), "prod", "dspace", "dspace")
    owner = manifest.reserve(output, candidate(), "staging", "dspace", "dspace")
    output.write_text("collision", encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match="overwrite"):
        manifest.verify_reservation(output, candidate(), "staging", "dspace", "dspace", owner)


def test_command_and_oci_json_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        manifest.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "failed"),
    )
    with pytest.raises(manifest.ManifestError, match="command failed.*failed"):
        manifest._run(["oras"])
    for response, message in (("not-json", "invalid JSON"), ("[]", "non-object")):
        with pytest.raises(manifest.ManifestError, match=message):
            manifest._json_run(lambda _command, result=response: result, ["oras"])


@pytest.mark.parametrize(
    ("command_key", "replacement", "message"),
    [
        (
            ("manifest", "fetch", "--descriptor", f"{manifest.IMAGE_REF}:main-abcdef0"),
            {},
            "descriptor",
        ),
        (("manifest", "fetch", f"{manifest.IMAGE_REF}@{DIGEST}"), {"manifests": []}, "image index"),
        (
            ("manifest", "fetch", f"{manifest.IMAGE_REF}@{DIGEST}"),
            {"manifests": [{}]},
            "platform digest",
        ),
        (("manifest", "fetch", f"{manifest.IMAGE_REF}@{PLATFORM_DIGEST}"), {}, "config digest"),
        (
            (
                "blob",
                "fetch",
                "--output",
                "-",
                f"{manifest.IMAGE_REF}@{IMAGE_CONFIG_DIGEST}",
            ),
            {},
            "revision label",
        ),
        (("manifest", "fetch", f"{manifest.CHART_REF}@{CHART_DIGEST}"), {}, "config digest"),
        (
            (
                "blob",
                "fetch",
                "--output",
                "-",
                f"{manifest.CHART_REF}@{CHART_CONFIG_DIGEST}",
            ),
            {},
            "revision metadata",
        ),
    ],
)
def test_preflight_rejects_malformed_oci_evidence(command_key, replacement, message) -> None:
    runner = oras_runner()

    def malformed(command):
        if tuple(command[1:]) == command_key:
            return json.dumps(replacement)
        return runner(command)

    with pytest.raises(manifest.ManifestError, match=message):
        manifest.preflight(
            candidate(), manifest.IMAGE_REF, manifest.CHART_REF, "oras", runner=malformed
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"image_ref": "example.invalid/dspace"}, "image reference"),
        ({"environment": "prod"}, "selected environment"),
    ],
)
def test_preflight_rejects_unapproved_selected_coordinates(kwargs, message) -> None:
    arguments = {
        "value": candidate(),
        "image_ref": manifest.IMAGE_REF,
        "chart_ref": manifest.CHART_REF,
        "oras": "oras",
        "runner": oras_runner(),
    }
    arguments.update(kwargs)
    with pytest.raises(manifest.ManifestError, match=message):
        manifest.preflight(**arguments)


@pytest.mark.parametrize("failure", ["object", "labels", "owner", "container"])
def test_finalize_rejects_malformed_release_objects(failure: str) -> None:
    discovered = workloads()
    pods_json = {"items": [pod("dspace-a")]}
    if failure == "object":
        discovered["items"][0] = "replicaset"
    elif failure == "labels":
        discovered["items"][0]["metadata"]["labels"] = {}
    elif failure == "owner":
        pods_json["items"][0]["metadata"]["ownerReferences"] = []
    else:
        pods_json["items"][0]["spec"]["containers"] = []
    with pytest.raises(manifest.ManifestError):
        finalize(workloads_json=discovered, pods_json=pods_json)


def test_finalize_rejects_noncanonical_image_id() -> None:
    item = pod("dspace-a")
    item["status"]["containerStatuses"][0]["imageID"] = "not-a-digest"
    with pytest.raises(manifest.ManifestError, match="non-canonical pod imageID"):
        finalize(pods_json={"items": [item]})
