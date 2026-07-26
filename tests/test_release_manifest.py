import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_manifest", ROOT / "scripts/release_manifest.py"
)
rm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(rm)

SHA = "abcdef0123456789abcdef0123456789abcdef01"
DIGEST = "sha256:" + "1" * 64
CHART_DIGEST = "sha256:" + "2" * 64


def upstream():
    return {
        "schemaVersion": 1,
        "app": "dspace",
        "applicationVersion": "3.1.0",
        "sourceRevision": SHA,
        "imageTag": "main-abcdef0",
        "imageDigest": DIGEST,
        "chartVersion": "3.2.1",
        "chartDigest": CHART_DIGEST,
        "semanticTag": "v3.1.0",
    }


def candidate():
    return {
        **upstream(),
        "recordType": "candidate",
        "environment": "staging",
        "expectedDefaultChatProvider": "token-place",
        "approvedAt": "2026-07-26T12:00:00Z",
        "approvedBy": "synthetic-test-operator",
    }


def completed(args, stdout):
    return subprocess.CompletedProcess(args, 0, json.dumps(stdout), "")


def test_upstream_import_and_canonical_round_trip():
    value = rm.validate_upstream(upstream())
    assert json.loads(rm.canonical(value)) == value
    assert rm.canonical(value) == rm.canonical(value)


@pytest.mark.parametrize("change", [lambda x: x.pop("chartDigest"), lambda x: x.update(extra=True)])
def test_missing_and_unknown_fields(change):
    value = upstream()
    change(value)
    with pytest.raises(rm.ManifestError):
        rm.validate_upstream(value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("sourceRevision", "abcdef0"),
        ("sourceRevision", SHA.upper()),
        ("imageTag", "latest"),
        ("imageTag", "v3.1.0"),
        ("imageTag", "main-deadbee"),
        ("imageDigest", "sha256:no"),
        ("chartDigest", DIGEST.upper()),
        ("chartVersion", "v3.1.0"),
    ],
)
def test_invalid_release_coordinates(key, value):
    data = upstream()
    data[key] = value
    with pytest.raises(rm.ManifestError):
        rm.validate_upstream(data)


@pytest.mark.parametrize(
    "key,value",
    [
        ("environment", "production"),
        ("expectedDefaultChatProvider", "tokenplace"),
        ("approvedBy", ""),
    ],
)
def test_invalid_approval(key, value):
    data = candidate()
    data[key] = value
    with pytest.raises(rm.ManifestError):
        rm.validate(data)


def test_preflight_order_and_mismatches():
    calls = []

    def runner(args):
        calls.append(args)
        ref = args[-1]
        digest = DIGEST if "/dspace:main-" in ref else CHART_DIGEST
        value = (
            {"digest": digest}
            if "--descriptor" in args
            else {"annotations": {"org.opencontainers.image.revision": SHA}}
        )
        return completed(args, value)

    results = rm.oci_preflight(candidate(), runner)
    assert [x[3] for x in calls] == [
        "--descriptor",
        "ghcr.io/democratizedspace/dspace:main-abcdef0",
        "--descriptor",
        "ghcr.io/democratizedspace/charts/dspace:3.2.1",
    ]
    assert len(results) == 2

    def bad(args):
        return completed(args, {"digest": "sha256:" + "9" * 64})

    with pytest.raises(rm.ManifestError, match="digest mismatch"):
        rm.oci_preflight(candidate(), bad)


def test_source_metadata_mismatch():
    def runner(args):
        if "--descriptor" in args:
            return completed(args, {"digest": DIGEST if "charts" not in args[-1] else CHART_DIGEST})
        return completed(args, {"annotations": {"org.opencontainers.image.revision": "0" * 40}})

    with pytest.raises(rm.ManifestError, match="source-revision"):
        rm.oci_preflight(candidate(), runner)


def test_multi_pod_collection_and_image_mismatch():
    def runner(args):
        if args[0] == "helm":
            return completed(args, {"version": 17})
        return completed(
            args,
            {
                "items": [
                    {
                        "metadata": {"name": name},
                        "status": {
                            "containerStatuses": [
                                {
                                    "imageID": "ghcr.io/democratizedspace/dspace@" + DIGEST,
                                    "state": {"running": {"startedAt": f"2026-07-26T12:00:0{i}Z"}},
                                }
                            ]
                        },
                    }
                    for i, name in enumerate(["dspace-a", "dspace-b"])
                ]
            },
        )

    record = rm.collect(candidate(), runner)
    assert record["helmRevision"] == 17
    assert [p["name"] for p in record["pods"]] == ["dspace-a", "dspace-b"]
    record["pods"][0]["imageID"] = "image@sha256:" + "9" * 64
    with pytest.raises(rm.ManifestError, match="pod image ID"):
        rm.validate(record, True)


def test_atomic_output_and_overwrite_refusal(tmp_path):
    path = tmp_path / "evidence" / "record.json"
    rm.write_new(path, candidate())
    assert json.loads(path.read_text()) == candidate()
    assert not list(path.parent.glob(".*.json.*"))
    with pytest.raises(rm.ManifestError, match="overwrite"):
        rm.write_new(path, candidate())


def test_records_exclude_tokens_and_secrets():
    serialized = rm.canonical(candidate()).lower()
    assert "token-place" in serialized
    assert (
        "password" not in serialized
        and "credential" not in serialized
        and "api_key" not in serialized
    )
