import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_release_manifest.py"
_spec = importlib.util.spec_from_file_location("generate_release_manifest", _MODULE_PATH)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

_hash_file = _module._hash_file
_human_duration = _module._human_duration
_load_metadata = _module._load_metadata
_load_qemu_artifacts = _module._load_qemu_artifacts
_render_checksum_table = _module._render_checksum_table
_render_stage_table = _module._render_stage_table
_version_for_channel = _module._version_for_channel
_write_notes = _module._write_notes
_write_outputs = _module._write_outputs


def _make_metadata(tmp_path: Path) -> Path:
    image_path = tmp_path / "sugarkube.img.xz"
    image_path.write_bytes(b"release-test")
    checksum = hashlib.sha256(image_path.read_bytes()).hexdigest()
    checksum_path = tmp_path / "sugarkube.img.xz.sha256"
    checksum_path.write_text(f"{checksum}  {image_path.name}\n", encoding="utf-8")
    build_log = tmp_path / "build.log"
    build_log.write_text(
        "\n".join(
            [
                "[00:00:00] Begin stage0",
                "[00:00:04] End stage0",
                "[00:00:05] Begin stage1",
                "[00:00:35] End stage1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    metadata_path = tmp_path / "metadata.json"
    cmd = [
        sys.executable,
        str(Path("scripts/create_build_metadata.py")),
        "--output",
        str(metadata_path),
        "--image",
        str(image_path),
        "--checksum",
        str(checksum_path),
        "--build-log",
        str(build_log),
        "--pi-gen-branch",
        "bookworm",
        "--pi-gen-url",
        "https://github.com/RPi-Distro/pi-gen.git",
        "--pi-gen-commit",
        "0123456789abcdef0123456789abcdef01234567",
        "--pi-gen-stages",
        "stage0 stage1",
        "--repo-commit",
        "89abcdef89abcdef89abcdef89abcdef89abcdef",
        "--repo-ref",
        "refs/heads/main",
        "--build-start",
        "2024-05-21T10:00:00Z",
        "--build-end",
        "2024-05-21T10:30:00Z",
        "--duration-seconds",
        "1800",
        "--runner-os",
        "Linux",
        "--runner-arch",
        "x86_64",
        "--option",
        "arm64=1",
    ]
    subprocess.run(cmd, check=True, cwd=Path(__file__).resolve().parents[1])
    return metadata_path


def test_release_manifest_outputs(tmp_path):
    metadata_path = _make_metadata(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    notes_path = tmp_path / "NOTES.md"
    outputs_file = tmp_path / "github_output.txt"
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = "1700000000"
    env["GITHUB_OUTPUT"] = str(outputs_file)
    cmd = [
        sys.executable,
        str(Path("scripts/generate_release_manifest.py")),
        "--metadata",
        str(metadata_path),
        "--manifest-output",
        str(manifest_path),
        "--notes-output",
        str(notes_path),
        "--release-channel",
        "stable",
        "--repo",
        "futuroptimist/sugarkube",
        "--run-id",
        "12345",
        "--run-attempt",
        "1",
        "--workflow",
        "pi-image-release",
    ]
    subprocess.run(cmd, check=True, env=env, cwd=Path(__file__).resolve().parents[1])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert manifest["version"].startswith("v2024.05.21")
    assert manifest["build"]["stage_durations"]["stage1"] == 30
    assert manifest["artifacts"][0]["name"] == "sugarkube.img.xz"
    assert manifest["artifacts"][1]["contains_sha256"] == metadata["image"]["sha256"]

    notes = notes_path.read_text(encoding="utf-8")
    assert "Stage timings" in notes
    assert metadata["image"]["sha256"] in notes

    outputs = dict(
        line.split("=", 1)
        for line in outputs_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert outputs["tag"].startswith("v2024.05.21")
    assert outputs["prerelease"] == "false"


def test_release_manifest_includes_qemu_smoke(tmp_path):
    metadata_path = _make_metadata(tmp_path)
    qemu_dir = tmp_path / "qemu-smoke"
    report_dir = qemu_dir / "first-boot-report"
    report_dir.mkdir(parents=True)
    (qemu_dir / "serial.log").write_text("serial output\n", encoding="utf-8")
    (qemu_dir / "smoke-success.json").write_text(
        json.dumps({"status": "pass", "notes": "stub"}), encoding="utf-8"
    )
    (report_dir / "summary.json").write_text(
        json.dumps({"checks": [{"name": "cloud_init", "status": "pass"}]}),
        encoding="utf-8",
    )
    (report_dir / "summary.md").write_text("# Summary\nAll good\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.json"
    notes_path = tmp_path / "NOTES.md"
    outputs_file = tmp_path / "github_output.txt"
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = "1700000000"
    env["GITHUB_OUTPUT"] = str(outputs_file)

    cmd = [
        sys.executable,
        str(Path("scripts/generate_release_manifest.py")),
        "--metadata",
        str(metadata_path),
        "--manifest-output",
        str(manifest_path),
        "--notes-output",
        str(notes_path),
        "--release-channel",
        "stable",
        "--repo",
        "futuroptimist/sugarkube",
        "--run-id",
        "67890",
        "--run-attempt",
        "1",
        "--workflow",
        "pi-image-release",
        "--qemu-artifacts",
        str(qemu_dir),
    ]
    subprocess.run(cmd, check=True, env=env, cwd=Path(__file__).resolve().parents[1])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qemu = manifest["qemu_smoke"]
    assert qemu["status"] == "pass"
    paths = {artifact["path"]: artifact for artifact in qemu["artifacts"]}
    serial = paths["serial.log"]
    assert serial["sha256"] == hashlib.sha256("serial output\n".encode()).hexdigest()
    summary_json = paths["first-boot-report/summary.json"]
    assert summary_json["size_bytes"] == len(
        json.dumps({"checks": [{"name": "cloud_init", "status": "pass"}]}).encode("utf-8")
    )

    notes = notes_path.read_text(encoding="utf-8")
    assert "QEMU smoke test" in notes
    assert serial["sha256"] in notes


def test_load_metadata_missing_file(tmp_path):
    missing_path = tmp_path / "does-not-exist.json"
    with pytest.raises(FileNotFoundError):
        _load_metadata(missing_path)


def test_human_duration_formats_hours_minutes_seconds():
    assert _human_duration(3661.2) == "1h 1m 1s"


def test_version_for_nightly_channel():
    tag, prerelease, name = _version_for_channel(
        "nightly",
        "0123456789abcdef0123456789abcdef01234567",
        "2024-05-22T12:34:56Z",
    )
    assert tag == "nightly-20240522"
    assert prerelease is True
    assert name == "Sugarkube Pi Image nightly 2024-05-22"


def test_render_stage_table_empty():
    assert _render_stage_table({}) == "No stage timing data was captured."


def test_render_stage_table_with_values():
    table = _render_stage_table({"prep": 5, "build": 61})
    assert "| `prep` | `5s` |" in table
    assert "| `build` | `1m 1s` |" in table


def test_render_checksum_table_prefers_contains_sha256(tmp_path):
    artifact_path = tmp_path / "artifact.bin"
    artifact_path.write_bytes(b"payload")
    digest = _hash_file(artifact_path)
    table = _render_checksum_table(
        [
            {
                "name": "artifact.bin",
                "contains_sha256": digest,
                "size_bytes": 0,
            }
        ]
    )
    assert "artifact.bin" in table
    assert digest in table
    assert "?" in table  # 0-byte size renders as unknown


def test_render_checksum_table_with_sizes():
    table = _render_checksum_table(
        [
            {
                "name": "artifact.bin",
                "sha256": "cafebabe",
                "size_bytes": 3 * 1024 * 1024,
            }
        ]
    )
    assert "3.0 MiB" in table


def test_load_qemu_artifacts_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        _load_qemu_artifacts(tmp_path / "missing")


def test_load_qemu_artifacts_invalid_success_json(tmp_path):
    qemu_dir = tmp_path / "qemu"
    qemu_dir.mkdir()
    (qemu_dir / "serial.log").write_text("serial\n", encoding="utf-8")
    (qemu_dir / "smoke-success.json").write_text("{", encoding="utf-8")

    payload = _load_qemu_artifacts(qemu_dir)
    assert payload["status"] == "invalid"
    assert payload["details"]["path"].endswith("smoke-success.json")
    assert any(artifact["path"] == "serial.log" for artifact in payload["artifacts"])


def test_load_qemu_artifacts_error_file_fallback(tmp_path):
    qemu_dir = tmp_path / "qemu"
    qemu_dir.mkdir()
    (qemu_dir / "error.json").write_text("not-json", encoding="utf-8")

    payload = _load_qemu_artifacts(qemu_dir)
    assert payload["status"] == "error"
    assert payload["details"]["error"] == "not-json"


def test_load_qemu_artifacts_error_file_valid_json(tmp_path):
    qemu_dir = tmp_path / "qemu"
    qemu_dir.mkdir()
    (qemu_dir / "error.json").write_text(
        json.dumps({"status": "fail", "reason": "timeout"}), encoding="utf-8"
    )

    payload = _load_qemu_artifacts(qemu_dir)
    assert payload["status"] == "error"
    assert payload["details"]["reason"] == "timeout"


def test_write_outputs_appends_to_file(tmp_path):
    output_path = tmp_path / "outputs.txt"
    output_path.write_text("existing=1\n", encoding="utf-8")
    _write_outputs(output_path, alpha="one", beta="two")

    contents = output_path.read_text(encoding="utf-8").splitlines()
    assert contents[0] == "existing=1"
    assert "alpha=one" in contents
    assert "beta=two" in contents


def test_iso_now_without_epoch(monkeypatch):
    class FrozenDatetime(_module.dt.datetime):
        @classmethod
        def utcnow(cls):
            return cls(2024, 6, 1, 12, 34, 56, 789000)

    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    monkeypatch.setattr(_module.dt, "datetime", FrozenDatetime)

    assert _module._iso_now() == "2024-06-01T12:34:56Z"


def test_write_notes_lists_generic_qemu_artifacts(tmp_path):
    notes_path = tmp_path / "notes.md"
    manifest = {
        "source": {"commit": None},
        "build": {
            "duration_seconds": 0,
            "stage_durations": {},
            "pi_gen": {"branch": "main"},
        },
        "artifacts": [
            {
                "name": "sugarkube.img.xz",
                "sha256": "deadbeef",
                "size_bytes": 1024,
                "path": "sugarkube.img.xz",
            }
        ],
        "qemu_smoke": {
            "status": "unknown",
            "artifacts": [
                {
                    "path": "other.txt",
                    "sha256": "cafebabe",
                    "size_bytes": 8,
                }
            ],
        },
    }

    _write_notes(notes_path, manifest, "futuroptimist/sugarkube", "vTEST")

    text = notes_path.read_text(encoding="utf-8")
    assert "Key artifacts: see manifest for full listing" in text


def test_write_notes_includes_commit_links(tmp_path):
    notes_path = tmp_path / "notes.md"
    manifest = {
        "source": {"commit": "0123456789abcdef0123456789abcdef01234567"},
        "build": {
            "duration_seconds": 90,
            "stage_durations": {"build": 90},
            "pi_gen": {
                "branch": "bookworm",
                "commit": "89abcdef89abcdef89abcdef89abcdef89abcdef",
                "url": "https://example.com/pi-gen",
            },
        },
        "artifacts": [
            {
                "name": "sugarkube.img.xz",
                "sha256": "deadbeef",
                "size_bytes": 1024,
                "path": "sugarkube.img.xz",
            },
        ],
    }

    _write_notes(notes_path, manifest, "futuroptimist/sugarkube", "vTEST")

    text = notes_path.read_text(encoding="utf-8")
    assert "[`0123456`]" in text
    assert (
        "https://github.com/futuroptimist/sugarkube/commit/0123456789abcdef0123456789abcdef01234567"
        in text
    )
    assert "https://example.com/pi-gen/commit/89abcdef89abcdef89abcdef89abcdef89abcdef" in text
    assert "`1m 30s`" in text
