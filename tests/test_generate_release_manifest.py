import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import generate_release_manifest as grm


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
    qemu_dir = tmp_path / "qemu-smoke"
    qemu_dir.mkdir()
    serial_log = qemu_dir / "serial.log"
    serial_log.write_text("serial output\n", encoding="utf-8")
    success_path = qemu_dir / "smoke-success.json"
    success_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    report_dir = qemu_dir / "first-boot-report"
    report_dir.mkdir()
    (report_dir / "summary.json").write_text("{}\n", encoding="utf-8")

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
        "--qemu-artifacts",
        str(qemu_dir),
    ]
    subprocess.run(cmd, check=True, env=env, cwd=Path(__file__).resolve().parents[1])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert manifest["version"].startswith("v2024.05.21")
    assert manifest["build"]["stage_durations"]["stage1"] == 30
    assert manifest["artifacts"][0]["name"] == "sugarkube.img.xz"
    assert manifest["artifacts"][1]["contains_sha256"] == metadata["image"]["sha256"]

    qemu = manifest["qemu_smoke"]
    assert qemu["status"] == "pass"
    serial_entry = next(item for item in qemu["artifacts"] if item["path"] == "serial.log")
    assert serial_entry["sha256"] == hashlib.sha256(b"serial output\n").hexdigest()

    report_entry = next(
        item for item in qemu["artifacts"] if item["path"] == "first-boot-report/summary.json"
    )
    assert report_entry["sha256"] == hashlib.sha256(b"{}\n").hexdigest()

    notes = notes_path.read_text(encoding="utf-8")
    assert "Stage timings" in notes
    assert metadata["image"]["sha256"] in notes
    assert "QEMU smoke test" in notes
    assert "serial.log" in notes

    outputs = dict(
        line.split("=", 1)
        for line in outputs_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert outputs["tag"].startswith("v2024.05.21")
    assert outputs["prerelease"] == "false"


def test_helpers_cover_edge_cases(tmp_path, monkeypatch):
    # _iso_now should honour SOURCE_DATE_EPOCH.
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700001234")
    assert grm._iso_now() == "2023-11-14T22:33:54Z"

    # _human_duration should pluralise components correctly.
    assert grm._human_duration(3661.1) == "1h 1m 1s"
    assert grm._human_duration(59.6) == "1m 0s"

    # _render helpers behave when data is missing.
    assert grm._render_stage_table({}) == "No stage timing data was captured."
    checksum_table = grm._render_checksum_table(
        [
            {"name": "serial.log", "sha256": "abc", "size_bytes": 4096},
            {"name": "smoke-success.json", "contains_sha256": "def", "size_bytes": None},
        ]
    )
    assert "serial.log" in checksum_table
    assert "?" in checksum_table.splitlines()[-1]

    # _version_for_channel handles nightly and stable release channels.
    tag, prerelease, name = grm._version_for_channel("nightly", "0123456", "2024-05-21T10:30:00Z")
    assert tag.startswith("nightly-20240521")
    assert prerelease is True
    assert name.startswith("Sugarkube Pi Image nightly")

    tag, prerelease, name = grm._version_for_channel(
        "stable", "abcdef012345", "2024-05-21T10:30:00Z"
    )
    assert tag.startswith("v2024.05.21")
    assert prerelease is False
    assert name.startswith("Sugarkube Pi Image 2024")

    # _write_outputs appends key/value pairs as expected.
    output_file = tmp_path / "outputs.txt"
    grm._write_outputs(output_file, alpha="1", beta="two")
    assert output_file.read_text(encoding="utf-8").splitlines() == [
        "alpha=1",
        "beta=two",
    ]


def test_gather_qemu_smoke_variants(tmp_path):
    base = tmp_path / "qemu"
    base.mkdir()
    (base / "serial.log").write_text("serial\n", encoding="utf-8")
    (base / "random.bin").write_bytes(b"\x00\x01")
    # Invalid JSON should surface as an error but still set status.
    (base / "smoke-success.json").write_text('{"status":', encoding="utf-8")
    (base / "error.json").write_text('{"message":"fail"}', encoding="utf-8")

    info = grm._gather_qemu_smoke(base)
    assert info["status"] == "invalid"
    assert info["serial_log"] == "serial.log"
    assert info["error"]["message"] == "fail"
    assert any(item["path"] == "random.bin" for item in info["artifacts"])

    # Missing directory should return None.
    assert grm._gather_qemu_smoke(tmp_path / "missing") is None


def test_write_notes_includes_qemu_details(tmp_path):
    manifest = {
        "source": {"commit": "0123456789abcdef0123456789abcdef01234567"},
        "build": {
            "duration_seconds": 90,
            "stage_durations": {"stage0": 45},
            "pi_gen": {
                "branch": "bookworm",
                "commit": "fedcba9876543210fedcba9876543210fedcba98",
                "url": "https://example.com/pi-gen",
            },
        },
        "artifacts": [
            {"name": "serial.log", "sha256": "abc", "size_bytes": 0, "path": "serial.log"},
        ],
        "qemu_smoke": {
            "status": "pass",
            "serial_log": "serial.log",
            "artifacts": [
                {"path": "serial.log", "sha256": "abc", "size_bytes": 0},
            ],
            "summary": {"status": "pass"},
            "error": None,
        },
    }
    notes_path = tmp_path / "notes.md"
    grm._write_notes(notes_path, manifest, "futuroptimist/sugarkube", "v2024.05.21")
    notes = notes_path.read_text(encoding="utf-8")
    assert "QEMU smoke test" in notes
    assert "serial.log" in notes
    assert "smoke-success.json status: `pass`" in notes


def test_write_manifest_round_trip(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest = {"channel": "stable", "generated_at": "2024-01-01T00:00:00Z"}
    grm._write_manifest(manifest_path, manifest)
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert loaded == manifest
