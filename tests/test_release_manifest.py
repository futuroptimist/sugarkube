"""Focused tests for fail-closed DSPACE release evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
CHART_DIGEST = "sha256:" + "2" * 64
PLATFORM_DIGEST = "sha256:" + "3" * 64
IMAGE_CONFIG_DIGEST = "sha256:" + "4" * 64
CHART_CONFIG_DIGEST = "sha256:" + "5" * 64


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
        ("blob", "fetch", f"{manifest.IMAGE_REF}@{IMAGE_CONFIG_DIGEST}"): {
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
        ("blob", "fetch", f"{manifest.CHART_REF}@{CHART_CONFIG_DIGEST}"): {
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
        "metadata": {"name": name},
        "status": {
            "startTime": "2026-07-26T12:01:00Z",
            "containerStatuses": [{"imageID": "ghcr.io/democratizedspace/dspace@" + digest}],
        },
    }


def test_finalize_collects_sorted_multi_pod_identity() -> None:
    final = manifest.finalize(
        candidate(),
        {"version": 17},
        {"items": [pod("dspace-b"), pod("dspace-a")]},
        manifest.preflight(
            candidate(), manifest.IMAGE_REF, manifest.CHART_REF, "oras", runner=oras_runner()
        ),
    )
    assert final["helmRevision"] == 17
    assert [item["name"] for item in final["pods"]] == ["dspace-a", "dspace-b"]
    assert final["runtimeSourceRevision"] == SHA
    assert final["runtimeSourceRevisionMethod"] == "podImageID+ociRevisionAnnotation"


def test_finalize_rejects_pod_image_mismatch() -> None:
    with pytest.raises(manifest.ManifestError, match="does not match"):
        manifest.finalize(
            candidate(),
            {"version": 1},
            {"items": [pod("dspace-a", "sha256:" + "9" * 64)]},
            manifest.preflight(
                candidate(), manifest.IMAGE_REF, manifest.CHART_REF, "oras", runner=oras_runner()
            ),
        )


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
        manifest.finalize(candidate(), {"version": 1}, {"items": [pod("dspace-a")]}, [])


def test_check_output_rejects_collision_before_deployment(tmp_path: Path, capsys) -> None:
    output = tmp_path / "existing.json"
    output.write_text("already recorded", encoding="utf-8")
    assert manifest.main(["check-output", "--output", str(output)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err


def test_default_evidence_path_is_stable_and_approval_unique() -> None:
    assert str(manifest.evidence_path(candidate())) == (
        "deployment-evidence/dspace/staging/main-abcdef0-20260726T120000Z.json"
    )
