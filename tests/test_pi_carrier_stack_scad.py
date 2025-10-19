from pathlib import Path
import re


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_stack_imports_carrier_module():
    text = _read("cad/pi_cluster/pi_carrier_stack.scad")
    assert "use <pi_carrier.scad>" in text, (
        "Stack should reuse pi_carrier.scad instead of duplicating geometry"
    )
    assert re.search(r"\bpi_carrier\s*\(", text), (
        "Stack must call pi_carrier() when instantiating each level"
    )
    assert (
        "cube([plate_len, plate_wid, plate_thickness], center = true);" not in text
    ), "Stack should no longer rely on placeholder cubes once pi_carrier is imported"


def test_carrier_exports_plate_dimensions():
    text = _read("cad/pi_cluster/pi_carrier.scad")
    assert (
        "function pi_carrier_plate_size()" in text
    ), "Expose plate dimensions via helper so downstream assemblies can align carriers"
