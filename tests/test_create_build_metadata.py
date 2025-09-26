import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _run_create(tmp_path: Path, *, write_summary: bool = False) -> Path:
    image_path = tmp_path / "sugarkube.img.xz"
    image_path.write_bytes(b"test-image")
    checksum = hashlib.sha256(image_path.read_bytes()).hexdigest()
    checksum_path = tmp_path / "sugarkube.img.xz.sha256"
    checksum_path.write_text(f"{checksum}  {image_path.name}\n", encoding="utf-8")

    build_log = tmp_path / "build.log"
    build_log.write_text(
        "\n".join(
            [
                "[00:00:00] Begin stage0",
                "[00:00:05] End stage0",
                "[00:00:05] Begin stage1",
                "[00:01:05] End stage1",
                "[00:01:06] Begin export-image",
                "[00:01:36] End export-image",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metadata_path = tmp_path / "metadata.json"
    stage_summary_path = tmp_path / "stage-summary.json"
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
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "--pi-gen-stages",
        "stage0 stage1 export-image",
        "--repo-commit",
        "cafebabecafebabecafebabecafebabecafebabe",
        "--repo-ref",
        "refs/heads/main",
        "--build-start",
        "2024-05-20T12:00:00Z",
        "--build-end",
        "2024-05-20T12:10:00Z",
        "--duration-seconds",
        "600",
        "--runner-os",
        "Linux",
        "--runner-arch",
        "x86_64",
        "--option",
        "arm64=1",
        "--option",
        "clone_sugarkube=true",
        "--option",
        "clone_token_place=false",
    ]
    if write_summary:
        cmd.extend(["--stage-summary", str(stage_summary_path)])
    subprocess.run(cmd, check=True, cwd=Path(__file__).resolve().parents[1])
    if write_summary:
        assert stage_summary_path.exists()
    return metadata_path


def test_metadata_contains_stage_durations(tmp_path):
    metadata_path = _run_create(tmp_path)
    data = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert data["image"]["size_bytes"] == len(b"test-image")
    assert data["image"]["sha256"]

    durations = data["build"]["stage_durations"]
    assert durations["stage0"] == 5
    assert durations["stage1"] == 60
    assert durations["export-image"] == 30

    assert data["options"]["arm64"] == 1
    assert data["options"]["clone_sugarkube"] is True
    assert data["options"]["clone_token_place"] is False
    assert data["verifier"]["status"] == "not_run"


def test_stage_summary_file_contains_structured_entries(tmp_path):
    metadata_path = _run_create(tmp_path, write_summary=True)
    summary_path = metadata_path.parent / "stage-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert [entry["name"] for entry in summary] == [
        "stage0",
        "stage1",
        "export-image",
    ]
    assert summary[0]["duration_seconds"] == 5
    assert summary[1]["duration_seconds"] == 60
    assert summary[2]["duration_seconds"] == 30
    assert summary[2]["first_start_seconds"] == 66
    assert summary[2]["last_end_seconds"] == 96
    assert metadata["build"]["stage_summary"] == summary
    assert metadata["build"]["stage_summary_path"] == str(summary_path)
