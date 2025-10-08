"""Ensure the shared glossary exists for tutorial references."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_DOC = REPO_ROOT / "docs" / "glossary.md"
TUTORIAL_INDEX = REPO_ROOT / "docs" / "tutorials" / "index.md"

EXPECTED_HEADINGS = [
    "## CPU",
    "## Memory",
    "## Storage",
    "## Operating System",
    "## Shell",
]


def test_glossary_defines_core_terms() -> None:
    """The glossary should exist and define the core terminology."""

    assert GLOSSARY_DOC.exists(), "docs/glossary.md is missing; publish the shared glossary."

    text = GLOSSARY_DOC.read_text(encoding="utf-8")
    for heading in EXPECTED_HEADINGS:
        assert heading in text, f"Glossary should document the heading: {heading}"


def test_tutorial_index_links_glossary() -> None:
    """Tutorial roadmap should link to the shared glossary."""

    text = TUTORIAL_INDEX.read_text(encoding="utf-8")
    assert (
        "[Sugarkube Glossary](../glossary.md)" in text
    ), "Tutorial roadmap should reference the shared glossary for milestone vocabulary."
