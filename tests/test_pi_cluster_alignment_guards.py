"""Guard pi cluster CAD spacing against regressions."""

from __future__ import annotations

from pathlib import Path

SCAD_ROOT = Path("cad/pi_cluster")


def _normalize(source: str) -> str:
    """Remove whitespace to make substring assertions resilient."""

    return "".join(source.split())


def test_pi_carrier_stack_includes_column_spacing_guard() -> None:
    """pi_carrier_stack.scad should enforce the documented column spacing tolerance."""

    source = (SCAD_ROOT / "pi_carrier_stack.scad").read_text(encoding="utf-8")
    normalized = _normalize(source)

    assert "column_alignment_tolerance)?0.2" in normalized
    assert "alignment_guard_enabled" in normalized
    assert "expected_column_spacing=pi_hole_spacing" in normalized
    assert (
        "abs(column_spacing[0]-expected_column_spacing[0])<=column_alignment_tolerance"
        in normalized
    )
    assert (
        "abs(column_spacing[1]-expected_column_spacing[1])<=column_alignment_tolerance"
        in normalized
    )


def test_fan_wall_shares_column_spacing_guard() -> None:
    """fan_wall.scad should inherit the same tolerance guard for tab alignment."""

    source = (SCAD_ROOT / "fan_wall.scad").read_text(encoding="utf-8")
    normalized = _normalize(source)

    assert "column_alignment_tolerance)?0.2" in normalized
    assert "alignment_guard_enabled" in normalized
    assert "expected_column_spacing=pi_hole_spacing" in normalized
    assert (
        "abs(column_spacing[0]-expected_column_spacing[0])<=column_alignment_tolerance"
        in normalized
    )
    assert (
        "abs(column_spacing[1]-expected_column_spacing[1])<=column_alignment_tolerance"
        in normalized
    )
