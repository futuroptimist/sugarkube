import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


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
    qemu_dir = tmp_path / "qemu-smoke"
    qemu_dir.mkdir()
    serial_log = qemu_dir / "serial.log"
    serial_payload = "serial ok\n"
    serial_log.write_text(serial_payload, encoding="utf-8")
    success_payload = {"status": "pass", "completed_at": "2024-05-21T10:45:00Z"}
    (qemu_dir / "smoke-success.json").write_text(
        json.dumps(success_payload, indent=2) + "\n", encoding="utf-8"
    )
    report_dir = qemu_dir / "first-boot-report"
    report_dir.mkdir()
    summary_json = report_dir / "summary.json"
    summary_json.write_text('{\n  "status": "ok"\n}\n', encoding="utf-8")
    summary_md = report_dir / "summary.md"
    summary_md.write_text("# Summary\n", encoding="utf-8")
    state_dir = qemu_dir / "sugarkube-state"
    state_dir.mkdir()
    state_marker = state_dir / "first-boot.ok"
    state_marker.write_text("ok\n", encoding="utf-8")
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

    qemu_meta = manifest["qemu_smoke"]
    assert qemu_meta["status"] == "pass"
    expected_serial_hash = hashlib.sha256(serial_payload.encode("utf-8")).hexdigest()
    assert qemu_meta["serial_log"]["path"] == "serial.log"
    assert qemu_meta["serial_log"]["sha256"] == expected_serial_hash
    artifact_paths = {entry["path"] for entry in qemu_meta["artifacts"]}
    assert "smoke-success.json" in artifact_paths
    assert "first-boot-report/summary.json" in artifact_paths
    summary_entry = next(
        entry
        for entry in qemu_meta["artifacts"]
        if entry["path"] == "first-boot-report/summary.json"
    )
    expected_summary_hash = hashlib.sha256(summary_json.read_bytes()).hexdigest()
    assert summary_entry["sha256"] == expected_summary_hash
