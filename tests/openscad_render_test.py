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
