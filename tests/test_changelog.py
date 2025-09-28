from __future__ import annotations

from itertools import islice
from pathlib import Path


def test_changelog_includes_ergonomics_section() -> None:
    changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    lines = changelog_path.read_text(encoding="utf-8").splitlines()

    try:
        section_index = next(
            idx for idx, line in enumerate(lines) if line.strip() == "### Ergonomics"
        )
    except StopIteration as exc:  # pragma: no cover - explicit assertion below
        raise AssertionError("CHANGELOG.md missing '### Ergonomics' section") from exc

    bullet_lines: list[str] = []
    for line in islice(lines, section_index + 1, None):
        stripped = line.strip()
        if stripped.startswith("### ") or stripped.startswith("## "):
            break
        if stripped.startswith("* "):
            bullet_lines.append(stripped)

    assert (
        bullet_lines
    ), "'### Ergonomics' section must include at least one bullet to track DX updates"
