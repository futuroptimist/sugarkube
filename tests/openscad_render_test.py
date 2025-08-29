import os
import shutil
import subprocess
from pathlib import Path


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


def test_errors_when_extra_arg(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "called"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        f"""#!/usr/bin/env bash
echo called > {marker}
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    scad = tmp_path / "model.scad"
    scad.write_text("cube();")

    result = subprocess.run(
        ["bash", "scripts/openscad_render.sh", str(scad), "extra"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Usage:" in result.stderr
    assert not marker.exists()


def test_errors_when_openscad_missing(tmp_path):
    fake_path = tmp_path / "bin"
    fake_path.mkdir()
    # Symlink required utilities but omit openscad to simulate absence
    for cmd in ["basename", "dirname", "mkdir"]:
        target = shutil.which(cmd)
        assert target is not None
        (fake_path / cmd).symlink_to(target)

    env = os.environ.copy()
    env["PATH"] = str(fake_path)

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


def test_standoff_mode_case_insensitive(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)
    env["STANDOFF_MODE"] = "PRINTED"

    subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi_carrier.scad",
        ],
        check=True,
        env=env,
    )

    args = log_file.read_text().split()
    assert "-D" in args
    assert 'standoff_mode="printed"' in args


def test_standoff_mode_nut(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)
    env["STANDOFF_MODE"] = "nut"

    subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi_carrier.scad",
        ],
        check=True,
        env=env,
    )

    args = log_file.read_text().split()
    assert 'standoff_mode="nut"' in args


def test_standoff_mode_adds_suffix_to_output(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)
    env["STANDOFF_MODE"] = "HEATSET"

    subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi_carrier.scad",
        ],
        check=True,
        env=env,
    )

    args = log_file.read_text().split()
    output = args[args.index("-o") + 1]
    assert output == "stl/pi_carrier_heatset.stl"


def test_trims_whitespace_in_standoff_mode(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)
    env["STANDOFF_MODE"] = "  printed  "

    subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi_carrier.scad",
        ],
        check=True,
        env=env,
    )

    args = log_file.read_text().split()
    assert "-D" in args
    assert 'standoff_mode="printed"' in args


def test_blank_standoff_mode_uses_default(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)
    env["STANDOFF_MODE"] = "   "

    subprocess.run(
        [
            "bash",
            "scripts/openscad_render.sh",
            "cad/pi_cluster/pi_carrier.scad",
        ],
        check=True,
        env=env,
    )

    args = log_file.read_text()
    assert "-D" not in args


def test_handles_leading_dash_filename(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    scad = tmp_path / "-model.scad"
    scad.write_text("cube();")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)

    script = Path(__file__).resolve().parents[1] / "scripts/openscad_render.sh"
    subprocess.run(
        ["bash", str(script), str(scad)],
        check=True,
        env=env,
        cwd=tmp_path,
    )

    args = log_file.read_text().strip().split()
    assert "--" in args
    assert args[args.index("--") + 1] == str(scad)


def test_handles_relative_leading_dash_filename(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    scad = tmp_path / "-rel.scad"
    scad.write_text("cube();")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)

    script = Path(__file__).resolve().parents[1] / "scripts/openscad_render.sh"
    subprocess.run(
        ["bash", str(script), scad.name],
        check=True,
        env=env,
        cwd=tmp_path,
    )

    args = log_file.read_text().strip().split()
    assert "--" in args
    assert args[args.index("--") + 1] == scad.name


def test_accepts_uppercase_extension(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log_file = tmp_path / "args.log"
    openscad = fake_bin / "openscad"
    openscad.write_text(
        """#!/usr/bin/env bash
printf '%s ' "$@" > "$LOG_FILE"
""",
    )
    openscad.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["LOG_FILE"] = str(log_file)

    scad = tmp_path / "MODEL.SCAD"
    scad.write_text("cube();")

    script = Path(__file__).resolve().parents[1] / "scripts/openscad_render.sh"
    subprocess.run(
        ["bash", str(script), str(scad)],
        check=True,
        env=env,
        cwd=tmp_path,
    )

    args = log_file.read_text().split()
    output = args[args.index("-o") + 1]
    assert output == "stl/MODEL.stl"
