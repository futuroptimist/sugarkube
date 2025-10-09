"""Validate that tutorial "Next Steps" links resolve to existing guides."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs" / "tutorials"


def _iter_next_steps_blocks(text: str) -> Iterable[str]:
    start = 0
    heading = "## Next Steps"
    while True:
        start = text.find(heading, start)
        if start == -1:
            break

        end = text.find("\n## ", start + len(heading))
        if end == -1:
            end = len(text)

        yield text[start:end]
        start = end


def _extract_reference_definitions(text: str) -> dict[str, str]:
    pattern = re.compile(r"^\[(?P<key>[^\]]+)\]:\s*(?P<value>\S+)", re.MULTILINE)
    return {match.group("key"): match.group("value") for match in pattern.finditer(text)}


def _iter_next_steps_links(text: str) -> Iterable[str]:
    block = next(_iter_next_steps_blocks(text), "")
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


def test_next_steps_inline_links_are_compact() -> None:
    """Inline links should stay on a single line so Markdown renders them."""

    pattern = re.compile(r"\[[^\]]+\]\s*\n\s*\(")
    for path in sorted(DOCS_DIR.glob("tutorial-*.md")):
        text = path.read_text(encoding="utf-8")
        for block in _iter_next_steps_blocks(text):
            assert not pattern.search(
                block
            ), f"{path.name} Next Steps should place inline links on a single line"
