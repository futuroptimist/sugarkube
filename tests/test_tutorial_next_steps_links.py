"""Validate that tutorial "Next Steps" links resolve to existing guides."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs" / "tutorials"


def _extract_reference_definitions(text: str) -> dict[str, str]:
    pattern = re.compile(r"^\[(?P<key>[^\]]+)\]:\s*(?P<value>\S+)", re.MULTILINE)
    return {match.group("key"): match.group("value") for match in pattern.finditer(text)}


def _iter_next_steps_links(text: str) -> Iterable[str]:
    start = text.find("## Next Steps")
    if start == -1:
        return []

    end = text.find("\n## ", start + len("## Next Steps"))
    if end == -1:
        end = len(text)

    block = text[start:end]
    definitions = _extract_reference_definitions(text)

    inline_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    reference_pattern = re.compile(r"\[[^\]]+\]\[([^\]]+)\]")

    for match in inline_pattern.finditer(block):
        yield match.group(1).strip()

    for match in reference_pattern.finditer(block):
        reference = match.group(1).strip()
        if reference in definitions:
            yield definitions[reference].strip()


def test_next_steps_links_reference_existing_files() -> None:
    for path in sorted(DOCS_DIR.glob("tutorial-*.md")):
        text = path.read_text(encoding="utf-8")

        for link in _iter_next_steps_links(text):
            if not link or link.startswith("http://") or link.startswith("https://"):
                continue
            if link.startswith("mailto:") or link.startswith("#"):
                continue

            target, _, _ = link.partition("#")
            if not target:
                continue

            resolved = (path.parent / target).resolve()
            assert resolved.exists(), f"{path.name} Next Steps references missing guide: {link}"
