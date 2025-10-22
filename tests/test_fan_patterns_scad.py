"""Ensure fan_patterns.scad exposes documented helper functions."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCAD_FILE = Path("cad/pi_cluster/fan_patterns.scad")
OPENSCAD = shutil.which("openscad")


def test_fan_patterns_declares_circle_helper() -> None:
    """Docs promise a fan_hole_circle_d helper—ensure it exists."""

    source = SCAD_FILE.read_text(encoding="utf-8")
    assert (
        "function fan_hole_circle_d" in source
    ), "docs/pi_cluster_stack.md describes fan_hole_circle_d; add it to fan_patterns.scad"


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_fan_hole_circle_helper_returns_expected_diameters(tmp_path: Path) -> None:
    """Evaluate the helper in OpenSCAD to confirm documented diameters."""

    probe = tmp_path / "probe.scad"
    output = tmp_path / "probe.stl"
    probe.write_text(
        textwrap.dedent(
            f"""
            include <{SCAD_FILE.resolve().as_posix()}>;

            echo(d80 = fan_hole_circle_d(80));
            echo(d92 = fan_hole_circle_d(92));
            echo(d120 = fan_hole_circle_d(120));
            echo(d_other = fan_hole_circle_d(127));
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["openscad", "-o", str(output), str(probe)],
        check=True,
        capture_output=True,
        text=True,
    )

    echoes: dict[str, float] = {}
    for line in result.stderr.splitlines():
        if "ECHO:" not in line or "=" not in line:
            continue
        _, remainder = line.split("ECHO:", 1)
        key_part, value_part = remainder.split("=", 1)
        key = key_part.strip()
        value = float(value_part.strip())
        echoes[key] = value

    assert echoes, "OpenSCAD did not emit any echo values for fan_hole_circle_d"
    assert echoes["d80"] == pytest.approx(4.5, rel=1e-6)
    assert echoes["d92"] == pytest.approx(4.5, rel=1e-6)
    assert echoes["d120"] == pytest.approx(4.5, rel=1e-6)
    assert echoes["d_other"] == pytest.approx(4.5, rel=1e-6)
