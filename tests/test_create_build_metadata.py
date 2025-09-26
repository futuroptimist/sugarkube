from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import create_build_metadata as cbm


def _create_command_args(
    *,
    metadata_path: Path,
    image_path: Path,
    checksum_path: Path,
    build_log: Path,
    stage_summary: Path | None,
) -> list[str]:
    args = [
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
    if stage_summary is not None:
        args.extend(["--stage-summary", str(stage_summary)])
    return args


def _run_create(tmp_path: Path, *, stage_summary: Path | None = None) -> Path:
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
    args = _create_command_args(
        metadata_path=metadata_path,
        image_path=image_path,
        checksum_path=checksum_path,
        build_log=build_log,
        stage_summary=stage_summary,
    )
    cbm.main(args)
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


def test_stage_summary_outputs_timelines(tmp_path):
    summary_path = tmp_path / "stage-summary.json"
    metadata_path = _run_create(tmp_path, stage_summary=summary_path)

    assert metadata_path.exists()
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["log_path"].endswith("build.log")
    assert summary["stage_count"] == 3
    assert summary["total_duration_seconds"] == 95

    stages = summary["stages"]
    assert [stage["name"] for stage in stages] == [
        "stage0",
        "stage1",
        "export-image",
    ]
    assert stages[0]["start_offset_seconds"] == 0
    assert stages[0]["end_offset_seconds"] == 5
    assert stages[1]["start_offset_seconds"] == 5
    assert stages[1]["end_offset_seconds"] == 65
    assert stages[2]["start_offset_seconds"] == 66
    assert stages[2]["end_offset_seconds"] == 96
    assert summary["incomplete_stages"] == []


def test_stage_summary_incomplete_entries(tmp_path):
    log_path = tmp_path / "build.log"
    log_path.write_text(
        "\n".join(
            [
                "[00:00:00] Begin stage0",
                "[00:00:05] End stage0",
                "[00:00:05] Begin stage1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    timer = cbm._parse_stage_log(log_path)
    summary_path = tmp_path / "summary.json"
    cbm._write_stage_summary(summary_path, timer, log_path)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["stage_count"] == 1
    assert summary["observed_elapsed_seconds"] == 5
    assert summary["incomplete_stages"] == [
        {"name": "stage1", "start_offset_seconds": 5}
    ]
