import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "create_build_metadata.py"
SPEC = importlib.util.spec_from_file_location("create_build_metadata", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - defensive guard
    raise RuntimeError(f"unable to load module from {MODULE_PATH}")
cbm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cbm)


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


def test_stage_timer_handles_midnight_rollover_and_occurrences():
    timer = cbm.StageTimer()
    for line in [
        "[23:59:50] Begin stage-a",
        "[00:00:05] End stage-a",
        "[00:20:00] Begin stage-b",
        "[00:30:30] End stage-b",
        "[00:40:00] Begin stage-b",
        "[00:45:00] End stage-b",
    ]:
        timer.observe(line)

    durations = timer.durations()
    assert durations == {"stage-a": 15, "stage-b": 930}

    summary = timer.summary()
    assert summary[0]["name"] == "stage-a"
    assert summary[0]["occurrences"] == 1
    assert summary[0]["duration_seconds"] == 15
    assert summary[0]["first_start_seconds"] == 86390
    assert summary[0]["last_end_seconds"] == 86405

    assert summary[1]["name"] == "stage-b"
    assert summary[1]["occurrences"] == 2
    assert summary[1]["duration_seconds"] == 930
    assert summary[1]["first_start_seconds"] == 86400 + 1200
    assert summary[1]["last_end_seconds"] == 86400 + 2700


def test_load_stage_metrics_missing_file(tmp_path):
    durations, summary = cbm._load_stage_metrics(tmp_path / "missing.log")
    assert durations == {}
    assert summary == []


def test_parse_options_coerce_types_and_validate():
    options = cbm._parse_options(
        [
            "enabled=true",
            "count=5",
            "ratio=3.25",
            "name=build",
        ]
    )
    assert options == {
        "enabled": True,
        "count": 5,
        "ratio": 3.25,
        "name": "build",
    }

    with pytest.raises(ValueError, match="missing '='"):
        cbm._parse_options(["invalid"])


def test_read_checksum_falls_back_to_image_hash(tmp_path):
    image = tmp_path / "image.img"
    image.write_bytes(b"binary-image")
    checksum_path = tmp_path / "image.img.sha256"
    checksum_path.write_text("not-a-hash\n", encoding="utf-8")

    digest = cbm._read_checksum(checksum_path, image)
    expected = hashlib.sha256(b"binary-image").hexdigest()
    assert digest == expected


def test_read_checksum_empty_without_image(tmp_path):
    checksum_path = tmp_path / "image.img.sha256"
    checksum_path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum file '.*' is empty"):
        cbm._read_checksum(checksum_path, None)


def test_load_verifier_states(tmp_path):
    assert cbm._load_verifier(None) == {"status": "not_run"}

    missing = tmp_path / "missing.json"
    assert cbm._load_verifier(str(missing)) == {
        "status": "not_found",
        "path": str(missing),
    }

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    result = cbm._load_verifier(str(invalid))
    assert result["status"] == "invalid"
    assert result["path"] == str(invalid)

    valid = tmp_path / "valid.json"
    payload = {"status": "ok"}
    valid.write_text(json.dumps(payload), encoding="utf-8")
    assert cbm._load_verifier(str(valid)) == {
        "status": "ok",
        "data": payload,
        "path": str(valid),
    }


def test_stage_summary_requires_build_log(tmp_path):
    image_path = tmp_path / "image.img"
    image_path.write_bytes(b"data")
    checksum_path = tmp_path / "image.img.sha256"
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  image.img\n", encoding="utf-8")

    metadata_path = tmp_path / "metadata.json"
    summary_path = tmp_path / "summary.json"

    argv = [
        "--output",
        str(metadata_path),
        "--image",
        str(image_path),
        "--checksum",
        str(checksum_path),
        "--pi-gen-branch",
        "bookworm",
        "--pi-gen-url",
        "https://example.com/pi-gen.git",
        "--pi-gen-commit",
        "0" * 40,
        "--pi-gen-stages",
        "stage0",
        "--repo-commit",
        "1" * 40,
        "--build-start",
        "2024-01-01T00:00:00Z",
        "--build-end",
        "2024-01-01T00:10:00Z",
        "--duration-seconds",
        "600",
        "--stage-summary",
        str(summary_path),
    ]

    with pytest.raises(ValueError, match="--stage-summary requires --build-log"):
        cbm.main(argv)


def test_default_runner_prefers_uname(monkeypatch):
    monkeypatch.setattr(
        os,
        "uname",
        lambda: os.uname_result(("MyOS", "host", "release", "version", "arch")),
    )

    system, arch = cbm._default_runner()
    assert system == "MyOS"
    assert arch == "arch"
