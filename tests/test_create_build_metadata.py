from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import create_build_metadata as cbm  # noqa: E402


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
    assert summary["incomplete_stages"] == [{"name": "stage1", "start_offset_seconds": 5}]


def test_parse_options_casts_and_validates():
    result = cbm._parse_options(
        [
            "threads=4",
            "ratio=0.5",
            "enabled=true",
            "label=sugarkube",
        ]
    )

    assert result == {
        "threads": 4,
        "ratio": 0.5,
        "enabled": True,
        "label": "sugarkube",
    }

    with pytest.raises(ValueError, match="missing '='"):
        cbm._parse_options(["broken"])


def test_read_checksum_fallbacks(tmp_path):
    image_path = tmp_path / "image.img"
    image_path.write_bytes(b"payload")
    expected = hashlib.sha256(b"payload").hexdigest()

    empty_checksum = tmp_path / "empty.sha256"
    empty_checksum.write_text("\n", encoding="utf-8")
    assert cbm._read_checksum(empty_checksum, image_path) == expected

    invalid_checksum = tmp_path / "invalid.sha256"
    invalid_checksum.write_text("not-a-digest\n", encoding="utf-8")
    assert cbm._read_checksum(invalid_checksum, image_path) == expected

    with pytest.raises(ValueError, match="not a SHA-256 hash"):
        cbm._read_checksum(invalid_checksum, None)


def test_load_verifier_statuses(tmp_path):
    missing = tmp_path / "missing.json"
    result = cbm._load_verifier(str(missing))
    assert result["status"] == "not_found"

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not valid json}", encoding="utf-8")
    result = cbm._load_verifier(str(invalid))
    assert result["status"] == "invalid"
    assert result["path"] == str(invalid)

    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"ok": True}), encoding="utf-8")
    result = cbm._load_verifier(str(payload))
    assert result == {"status": "ok", "data": {"ok": True}, "path": str(payload)}


def test_default_runner_handles_platform_fallback(monkeypatch):
    monkeypatch.delattr(cbm.os, "uname", raising=False)
    monkeypatch.setattr(cbm.platform, "system", lambda: "", raising=False)
    monkeypatch.setattr(cbm.platform, "machine", lambda: "", raising=False)

    system, arch = cbm._default_runner()
    assert system == "unknown"
    assert arch == "unknown"


def test_stage_timer_handles_midnight_wrap():
    timer = cbm.StageTimer()
    timer.observe("[23:59:59] Begin stage0")
    timer.observe("[00:00:10] End stage0")

    spans = timer.spans()
    assert spans[0].duration == 11


def test_stage_timer_nonmatching_line(tmp_path):
    timer = cbm.StageTimer()
    timer.observe("noise without timestamp")

    assert timer.elapsed() == 0.0

    log_path = tmp_path / "missing.log"
    parsed = cbm._parse_stage_log(log_path)
    assert isinstance(parsed, cbm.StageTimer)
    assert cbm._load_stage_durations(log_path) == {}


def test_read_checksum_requires_content(tmp_path):
    empty_checksum = tmp_path / "empty.sha256"
    empty_checksum.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum file"):
        cbm._read_checksum(empty_checksum, None)


def test_main_validates_source_artifacts(tmp_path):
    image_path = tmp_path / "missing.img"
    checksum_path = tmp_path / "present.sha256"
    checksum_path.write_text("deadbeef\n", encoding="utf-8")
    metadata_path = tmp_path / "metadata.json"

    args = _create_command_args(
        metadata_path=metadata_path,
        image_path=image_path,
        checksum_path=checksum_path,
        build_log=tmp_path / "build.log",
        stage_summary=None,
    )

    with pytest.raises(FileNotFoundError, match="image not found"):
        cbm.main(args)

    image_path.write_text("data", encoding="utf-8")
    checksum_path.unlink()

    with pytest.raises(FileNotFoundError, match="checksum file not found"):
        cbm.main(args)
