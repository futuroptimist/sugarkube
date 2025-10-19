from __future__ import annotations

import ast
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"


def test_pi_carrier_stack_imports_pi_carrier_module() -> None:
    """pi_carrier_stack should reuse the base module instead of cubes."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert "pi_carrier.scad" in source, "pi_carrier_stack should import pi_carrier.scad"
    assert re.search(r"\bpi_carrier\s*\(", source), "pi_carrier_stack should call pi_carrier()"


def _parse_default_assignments(source: str) -> dict[str, object]:
    """Extract default values from `is_undef()` guard assignments."""

    defaults: dict[str, object] = {}
    pattern = re.compile(
        r"^(?P<name>\w+)\s*=\s*is_undef\(\s*(?P<ref>\w+)\s*\)\s*\?\s*(?P<default>[^:;]+)\s*:\s*\2;",
        re.MULTILINE,
    )
    for match in pattern.finditer(source):
        default = match.group("default").strip()
        try:
            defaults[match.group("name")] = ast.literal_eval(default)
        except (SyntaxError, ValueError):
            defaults[match.group("name")] = default
    return defaults


def test_pi_carrier_stack_echo_includes_dimension_metadata() -> None:
    """Ensure the SCAD exports emit dimensional context for regression checks."""

    source = SCAD_PATH.read_text(encoding="utf-8")

    echo_match = re.search(r"echo\s*\(([^;]+)\);", source)
    assert echo_match, "pi_carrier_stack.scad should expose an echo() call"
    echo_args = echo_match.group(1)

    for key in ("z_gap_clear", "column_spacing", "fan_offset_from_stack"):
        assert re.search(rf"{key}\s*=", echo_args), (
            f"Expected {key} to appear in the echo metadata"
        )

    defaults = _parse_default_assignments(source)
    assert defaults.get("z_gap_clear") == 32, (
        "Default z-gap clearance should remain 32 mm"
    )
    assert defaults.get("fan_offset_from_stack") == 15, (
        "Default fan offset should remain 15 mm"
    )
    assert defaults.get("column_spacing") == [58, 49], (
        "Column spacing should track Pi mount pattern"
    )
