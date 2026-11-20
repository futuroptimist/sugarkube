"""Offline fixtures for the standalone, read-only staging coordinate preflight."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import dspace_release_manifest as legacy
from scripts import dspace_staging_coordinates as adapter

SOURCE = "a" * 40
TREE = "b" * 40
WORKFLOW = "c" * 40
CONTENT = "sha256:" + "d" * 64
PROVENANCE = "sha256:" + "e" * 64
APP = "3.1.0"
VERSION = "3.1.3"  # Synthetic; does not assert that this is the published chart.
NODE = "24.22.3"
RUNTIME = f"v{APP}+{SOURCE[:7]}"


def encode(value):
    return json.dumps(value, indent=2).encode() + b"\n"


class Fixture:
    def __init__(self, home, fault=None):
        self.calls = []
        self.documents = {}
        self.context = b"sugar-staging\n"
        self.identity = b"staging\n"
        self.home = home
        config = home / ".kube" / "config-sugarkube-staging"
        config.parent.mkdir()
        config.touch()
        runtime = {}
        manifests = []
        for arch in adapter.PLATFORMS:
            config_digest = self.save(
                adapter.IMAGE,
                "blob",
                {
                    "os": "linux",
                    "architecture": "amd64" if fault == "wrong-arch" else arch,
                    "config": {
                        "Labels": {
                            adapter.SOURCE: adapter.REPOSITORY,
                            adapter.REVISION: "1" * 40 if fault == "image-source" else SOURCE,
                        },
                        "Env": [
                            f"NODE_VERSION={NODE}",
                            f"DSPACE_VERSION={RUNTIME if fault != 'runtime' else 'v3.0.2'}",
                        ],
                    },
                },
            )
            manifest = self.save(
                adapter.IMAGE,
                "manifest",
                {
                    "schemaVersion": 2,
                    "mediaType": adapter.IMAGE_MANIFEST,
                    "config": {
                        "mediaType": "application/vnd.oci.image.config.v1+json",
                        "digest": config_digest,
                    },
                    "layers": [{"digest": CONTENT}],
                    # Distinguish architectures even in the intentionally invalid fixture.
                    "annotations": {"fixture.descriptor": arch},
                },
            )
            runtime["linux/" + arch] = {"digest": manifest, "configDigest": config_digest}
            manifests.append(
                {
                    "mediaType": adapter.IMAGE_MANIFEST,
                    "digest": manifest,
                    "platform": {
                        "os": "linux",
                        "architecture": arch,
                        **({"variant": "v8"} if arch == "arm64" else {}),
                    },
                }
            )
        manifests.append(
            {
                "mediaType": adapter.IMAGE_MANIFEST,
                "digest": "sha256:" + "f" * 64,
                "platform": {"os": "unknown", "architecture": "unknown"},
                "annotations": {
                    "vnd.docker.reference.type": "attestation-manifest",
                    "vnd.docker.reference.digest": runtime["linux/amd64"]["digest"],
                },
            }
        )
        if fault == "duplicate-platform":
            manifests.append(manifests[0])
        if fault == "missing-platform":
            manifests.pop(1)
        image_digest = self.save(
            adapter.IMAGE,
            "manifest",
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": manifests,
            },
        )
        config_digest = self.save(
            adapter.CHART,
            "blob",
            {
                "name": "dspace",
                "version": VERSION,
                "appVersion": APP,
                "annotations": {
                    adapter.SOURCE: adapter.REPOSITORY,
                    adapter.REVISION: "1" * 40 if fault == "chart-source" else SOURCE,
                    adapter.VERSION: VERSION if fault == "config-version" else APP,
                },
            },
        )
        # The pinned Helm/ORAS publisher omits mediaType in the raw manifest body
        # and orders layers by digest rather than media type.
        chart_digest = self.save(
            adapter.CHART,
            "manifest",
            {
                "schemaVersion": 2,
                "config": {"mediaType": adapter.HELM_CONFIG, "digest": config_digest},
                "annotations": {
                    adapter.SOURCE: adapter.REPOSITORY,
                    adapter.REVISION: SOURCE,
                    adapter.VERSION: APP if fault == "chart-version" else VERSION,
                },
                "layers": [
                    {"mediaType": adapter.HELM_PROVENANCE, "size": 32, "digest": PROVENANCE},
                    {"mediaType": adapter.HELM_CONTENT, "size": 1024, "digest": CONTENT},
                ],
            },
        )
        self.receipt = {
            "schema": "dspace-staging-coordinates-v1",
            "environment": "staging",
            "app": "dspace",
            "sourceRevision": SOURCE,
            "sourceTree": TREE,
            "applicationVersion": APP,
            "image": {
                "repository": adapter.IMAGE,
                "digest": image_digest,
                "platforms": runtime,
            },
            "chart": {
                "repository": "oci://" + adapter.CHART,
                "version": VERSION,
                "digest": chart_digest,
                "contentDigest": CONTENT,
            },
            "approvalRef": "synthetic-approval",
            "evidenceType": "offline-oci-metadata-correlation",
            "deploymentAuthorized": False,
        }
        self.native = {
            "schema": "dspace-candidate-image-summary-v1",
            "image": adapter.IMAGE,
            "indexDigest": image_digest,
            "sourceSha": SOURCE,
            "tree": TREE,
            "appVersion": APP,
            "node": NODE,
            "runtimeVersion": RUNTIME,
            "workflowSha": WORKFLOW,
            "runId": "1729",
            "runAttempt": "2",
            "platforms": {arch: runtime["linux/" + arch].copy() for arch in adapter.PLATFORMS},
            "publishedByThisRun": False,
            "verified": True,
            "completedAt": "2026-11-20T09:00:00.000Z",
        }
        self.approval = {
            "schema": "dspace-staging-preflight-approval-v1",
            "environment": "staging",
            "approvalRef": self.receipt["approvalRef"],
            "sourceRevision": SOURCE,
            "applicationVersion": APP,
            "imageDigest": image_digest,
            "chartVersion": VERSION,
            "chartDigest": chart_digest,
            "nativeArtifactId": "1730",
            "nativeSummaryDigest": adapter.content_digest(encode(self.native)),
            "nativeWorkflowSha": WORKFLOW,
            "nativeRunId": "1729",
            "nativeRunAttempt": "2",
        }

    def save(self, repository, kind, value):
        raw = encode(value)
        digest = adapter.content_digest(raw)
        self.documents[kind, f"{repository}@{digest}"] = raw
        return digest

    def read(self, argv, limit):
        self.calls.append(argv)
        if argv[0] == "kubectl":
            assert argv[3:] == ["config", "current-context"]
            return self.context
        if argv[0] == sys.executable:
            assert Path(argv[1]).name == "cluster_identity.py"
            assert argv[2] == "assert" and argv[5:] == ["--env", "staging"]
            return self.identity
        assert argv[0] == "oras" and argv[2:5] == ["fetch", "--output", "-"]
        assert limit == adapter.MAX_METADATA
        value = self.documents.get((argv[1], argv[5]))
        if value is None:
            raise adapter.PreflightError("mock read rejected")
        return value

    def run(self, native_raw=None):
        return adapter.preflight(
            self.receipt,
            self.approval,
            encode(self.native) if native_raw is None else native_raw,
            home=self.home,
            read=self.read,
        )


def test_preflight_print_coordinates_not_authorization(tmp_path):
    fixture = Fixture(tmp_path)
    result = fixture.run()
    assert result == {
        "schema": "sugarkube-dspace-staging-preflight-v1",
        "environment": "staging",
        "context": "sugar-staging",
        "sourceRevision": SOURCE,
        "appVersion": APP,
        "imageReference": fixture.receipt["image"]["repository"]
        + "@"
        + fixture.receipt["image"]["digest"],
        "chartReference": fixture.receipt["chart"]["repository"]
        + "@"
        + fixture.receipt["chart"]["digest"],
        "chartVersion": VERSION,
        "chartContentDigest": CONTENT,
        "nativeSummaryDigest": fixture.approval["nativeSummaryDigest"],
        "deploymentAuthorized": False,
    }
    assert len(fixture.calls) == 9
    assert all("@" in call[-1] for call in fixture.calls[2:])
    with pytest.raises(legacy.ManifestError, match="schemaVersion"):
        legacy.candidate(result, "prod", "token-place", "2026-11-20T00:00:00Z", "fixture")
    with pytest.raises(legacy.ManifestError, match="schemaVersion"):
        legacy.candidate(result, "staging", "token-place", "2026-11-20T00:00:00Z", "fixture")
    with pytest.raises(legacy.ManifestError, match="schemaVersion"):
        legacy.validate(result, True)


def test_production_promotion_gate_cannot_accept_preflight(tmp_path):
    fixture = Fixture(tmp_path)
    upstream = {
        "schemaVersion": 2,
        "app": "dspace",
        "applicationVersion": APP,
        "sourceRevision": SOURCE,
        "chartSourceRevision": SOURCE,
        "imageTag": f"main-{SOURCE[:7]}",
        "imageDigest": fixture.receipt["image"]["digest"],
        "chartVersion": VERSION,
        "chartDigest": fixture.receipt["chart"]["digest"],
        "semanticTag": f"v{APP}",  # A controlled synthetic test of the legacy gate only.
    }
    prod = legacy.candidate(upstream, "prod", "token-place", "2026-11-20T00:00:00Z", "fixture")
    with pytest.raises(legacy.ManifestError, match="schemaVersion"):
        legacy.staging_gate(prod, fixture.run())


@pytest.mark.parametrize("context", [b"sugar-prod\n", b"other\n", b""])
def test_context_rejection_before_registry(tmp_path, context):
    fixture = Fixture(tmp_path)
    fixture.context = context
    with pytest.raises(adapter.PreflightError, match="staging context"):
        fixture.run()
    assert len(fixture.calls) == 1


def test_mislabeled_context_cannot_accept_prod_identity(tmp_path):
    fixture = Fixture(tmp_path)
    fixture.identity = b"prod\n"
    with pytest.raises(adapter.PreflightError, match="connected cluster"):
        fixture.run()
    assert len(fixture.calls) == 2


@pytest.mark.parametrize(
    ("obj", "key", "value"),
    [
        ("approval", "environment", "prod"),
        ("approval", "nativeArtifactId", "0"),
        ("approval", "approvalRef", "another-approval"),
        ("approval", "sourceRevision", "f" * 40),
        ("approval", "chartDigest", "sha256:" + "f" * 64),
        ("approval", "nativeSummaryDigest", "sha256:" + "e" * 64),
        ("approval", "nativeRunId", "17"),
        ("approval", "nativeRunAttempt", "1"),
        ("approval", "nativeWorkflowSha", "e" * 40),
        ("receipt", "deploymentAuthorized", True),
        ("receipt", "semanticTag", "v3.1.0"),
        ("native", "verified", False),
        ("native", "completedAt", "2026-11-99T09:00:00.000Z"),
        ("native", "indexDigest", "sha256:" + "e" * 64),
        ("native", "sourceSha", "d" * 40),
    ],
)
def test_wrong_receipt_approval_or_native_fail_before_external_reads(tmp_path, obj, key, value):
    fixture = Fixture(tmp_path)
    getattr(fixture, obj)[key] = value
    if obj == "native":
        fixture.approval["nativeSummaryDigest"] = adapter.content_digest(encode(fixture.native))
    with pytest.raises(adapter.PreflightError):
        fixture.run()
    assert fixture.calls == []


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-arch",
        "image-source",
        "runtime",
        "chart-source",
        "config-version",
        "chart-version",
        "duplicate-platform",
        "missing-platform",
    ],
)
def test_self_consistent_digests_do_not_hide_wrong_provenance_or_graph(tmp_path, fault):
    fixture = Fixture(tmp_path, fault)
    with pytest.raises(adapter.PreflightError):
        fixture.run()


def test_modified_immutable_bytes_fail(tmp_path):
    fixture = Fixture(tmp_path)
    ref = f"{adapter.CHART}@{fixture.approval['chartDigest']}"
    fixture.documents["manifest", ref] = b"{}"
    with pytest.raises(adapter.PreflightError, match="pinned digest"):
        fixture.run()


def test_missing_chart_is_not_allowed_to_fall_back_to_tag(tmp_path):
    fixture = Fixture(tmp_path)
    ref = f"{adapter.CHART}@{fixture.approval['chartDigest']}"
    fixture.documents.pop(("manifest", ref))
    with pytest.raises(adapter.PreflightError, match="mock read rejected"):
        fixture.run()
    assert fixture.calls[-1][-1] == ref


def test_missing_out_of_band_approval_before_reads(tmp_path):
    fixture = Fixture(tmp_path)
    fixture.approval = {}
    with pytest.raises(adapter.PreflightError, match="staging approval"):
        fixture.run()
    assert fixture.calls == []


def test_missing_native_summary_is_not_sufficient(tmp_path):
    fixture = Fixture(tmp_path)
    with pytest.raises(adapter.PreflightError, match="invalid metadata size"):
        fixture.run(b"")
    assert fixture.calls == []


@pytest.mark.parametrize("raw", [b"[]", b"\xff", b'{"app":1,"app":2}', b'{"app":NaN}'])
def test_reject_ambiguous_malformed_or_non_object_documents(raw):
    with pytest.raises(adapter.PreflightError):
        adapter.parse(raw, adapter.MAX_INPUT)


@pytest.mark.parametrize(
    "flag",
    ["--kubeconfig", "--environment=prod", "--environment=staging", "--env=staging", "--image"],
)
def test_cli_rejects_wrong_or_unrecognized_flags(flag, capsys):
    with pytest.raises(SystemExit) as exit_status:
        adapter.main(
            [
                "preflight",
                "--environment",
                "staging",
                "--receipt",
                "not-read",
                "--approval",
                "not-read",
                "--native-summary",
                "not-read",
                flag,
            ]
        )
    assert exit_status.value.code == 2
    assert capsys.readouterr().out == ""


def test_bounded_command_output_and_sanitized_stderr():
    with pytest.raises(adapter.PreflightError, match="output limit"):
        adapter.command([sys.executable, "-c", "print('x' * 100000)"], 32)
    with pytest.raises(adapter.PreflightError, match="read-only command failed"):
        adapter.command(
            [
                sys.executable,
                "-c",
                "import sys; print('not-disclosed', file=sys.stderr); sys.exit(3)",
            ],
            32,
        )
