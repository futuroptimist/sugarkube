"""Focused tests for fail-closed DSPACE release evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dspace_release_manifest as manifest

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
CHART_DIGEST = "sha256:" + "2" * 64


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
        lambda x: x.update(imageTag="v3.2.0"),
        lambda x: x.update(imageTag="main-deadbee"),
        lambda x: x.update(imageDigest="sha256:abc"),
        lambda x: x.update(chartDigest="2" * 64),
        lambda x: x.update(chartVersion="v3.2.0"),
    ],
)
def test_rejects_invalid_upstream(change) -> None:
    value = upstream()
    change(value)
    with pytest.raises(manifest.ManifestError):
        manifest.candidate(
            value, "staging", "token-place", "2026-07-26T12:00:00Z", "operator"
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
def test_rejects_wrong_enrichment(
    environment: str, provider: str, approver: str
) -> None:
    with pytest.raises(manifest.ManifestError):
        manifest.candidate(
            upstream(), environment, provider, "2026-07-26T12:00:00Z", approver
        )


def test_preflight_checks_digests_and_both_revision_metadata(monkeypatch) -> None:
    responses = iter([(DIGEST, SHA), (CHART_DIGEST, SHA)])
    monkeypatch.setattr(manifest, "_oras_evidence", lambda *_: next(responses))
    results = manifest.preflight(candidate(), "image", "chart", "oras-stub")
    assert [item["check"] for item in results] == [
        "imageDigest",
        "chartDigest",
        "imageSourceRevision",
        "chartSourceRevision",
    ]


@pytest.mark.parametrize(
    "responses",
    [
        [("sha256:" + "9" * 64, SHA), (CHART_DIGEST, SHA)],
        [(DIGEST, SHA), ("sha256:" + "9" * 64, SHA)],
        [(DIGEST, "0" * 40), (CHART_DIGEST, SHA)],
    ],
)
def test_preflight_mismatch_fails(monkeypatch, responses) -> None:
    values = iter(responses)
    monkeypatch.setattr(manifest, "_oras_evidence", lambda *_: next(values))
    with pytest.raises(manifest.ManifestError, match="mismatch"):
        manifest.preflight(candidate(), "image", "chart", "oras")


def pod(name: str, digest: str = DIGEST) -> dict[str, object]:
    return {
        "metadata": {"name": name},
        "status": {
            "startTime": "2026-07-26T12:01:00Z",
            "containerStatuses": [
                {"imageID": "ghcr.io/democratizedspace/dspace@" + digest}
            ],
        },
    }


def test_finalize_collects_sorted_multi_pod_identity() -> None:
    final = manifest.finalize(
        candidate(),
        {"version": 17},
        {"items": [pod("dspace-b"), pod("dspace-a")]},
        [{"check": "imageDigest", "passed": True, "details": "fresh OCI result"}],
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
            [{"check": "imageDigest", "passed": True, "details": "fresh OCI result"}],
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


def test_check_output_rejects_collision_before_deployment(
    tmp_path: Path, capsys
) -> None:
    output = tmp_path / "existing.json"
    output.write_text("already recorded", encoding="utf-8")
    assert manifest.main(["check-output", "--output", str(output)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
