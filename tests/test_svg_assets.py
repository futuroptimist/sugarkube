from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[1]
SVG_DIRS = [
    REPO_ROOT / "docs" / "images",
]


def test_svg_assets_parse_cleanly() -> None:
    svg_paths = [path for directory in SVG_DIRS for path in sorted(directory.glob("*.svg"))]
    assert svg_paths, "Expected at least one SVG asset to validate"

    for svg_path in svg_paths:
        try:
            ElementTree.parse(svg_path)
        except ElementTree.ParseError as exc:  # pragma: no cover - explicit assertion path
            raise AssertionError(
                f"Failed to parse SVG asset {svg_path.relative_to(REPO_ROOT)}: {exc}"
            ) from exc
