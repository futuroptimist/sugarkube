import os
import subprocess


def test_script_respects_model_default(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
"""
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)

    subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi5_triple_carrier_rot45.scad",
        ],
        check=True,
        env=env,
    )

    args = log_file.read_text()
    assert "-D" not in args


def test_errors_when_file_missing(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "called"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        f"""#!/usr/bin/env bash
echo called > {marker}
"""
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    missing = tmp_path / "missing.scad"
    result = subprocess.run(
        ["bash", "scripts/openscad_render.sh", str(missing)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "File not found" in result.stderr
    assert not marker.exists()


def test_errors_when_arg_missing():
    result = subprocess.run(
        ["bash", "scripts/openscad_render.sh"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Usage:" in result.stderr


def test_errors_when_openscad_missing(tmp_path):
    env = os.environ.copy()
    env["PATH"] = "/usr/bin"

    result = subprocess.run(
        [
            "/bin/bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi5_triple_carrier_rot45.scad",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "OpenSCAD not found" in result.stderr


def test_errors_when_extension_wrong(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "called"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        f"""#!/usr/bin/env bash
echo called > {marker}
"""
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    wrong = tmp_path / "model.txt"
    wrong.write_text("not scad")

    result = subprocess.run(
        ["bash", "scripts/openscad_render.sh", str(wrong)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Expected .scad file" in result.stderr
    assert not marker.exists()


def test_errors_when_standoff_mode_invalid():
    env = os.environ.copy()
    env["STANDOFF_MODE"] = "invalid"

    result = subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi_carrier.scad",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Invalid STANDOFF_MODE" in result.stderr
