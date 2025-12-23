from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"


def test_export_part_comparisons_use_string_literals() -> None:
    content = SCAD_PATH.read_text()

    bare_tokens = [
        re.compile(r"export_part\s*(?:==|=)\s*(?!\"|')carrier_level\b"),
        re.compile(r"export_part\s*(?:==|=)\s*(?!\"|')post\b"),
        re.compile(r"export_part\s*(?:==|=)\s*(?!\"|')assembly\b"),
    ]

    for pattern in bare_tokens:
        assert not pattern.search(content), (
            "Found bare token comparison instead of quoted string for export_part: "
            f"{pattern.pattern}"
        )


def test_export_part_normalization_present() -> None:
    content = SCAD_PATH.read_text()

    assert "_normalize_export_part" in content
    assert "export_part_resolved" in content
