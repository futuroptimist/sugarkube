"""Guard against hidden bidirectional control characters in text assets."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Common bidirectional control characters that trigger GitHub's warning banner.
BIDI_CODEPOINTS = {
    0x200E,  # LEFT-TO-RIGHT MARK
    0x200F,  # RIGHT-TO-LEFT MARK
    0x202A,  # LEFT-TO-RIGHT EMBEDDING
    0x202B,  # RIGHT-TO-LEFT EMBEDDING
    0x202C,  # POP DIRECTIONAL FORMATTING
    0x202D,  # LEFT-TO-RIGHT OVERRIDE
    0x202E,  # RIGHT-TO-LEFT OVERRIDE
    0x2066,  # LEFT-TO-RIGHT ISOLATE
    0x2067,  # RIGHT-TO-LEFT ISOLATE
    0x2068,  # FIRST STRONG ISOLATE
    0x2069,  # POP DIRECTIONAL ISOLATE
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE / BOM
}


def _bidi_locations(text: str) -> list[tuple[int, str]]:
    return [
        (idx, f"U+{ord(ch):04X}") for idx, ch in enumerate(text) if ord(ch) in BIDI_CODEPOINTS
    ]


def test_scad_and_docs_are_bidi_clean() -> None:
    """Prevent hidden bidi control characters from slipping into CAD or docs."""

    targets = list((ROOT / "cad").rglob("*.scad")) + list((ROOT / "docs").rglob("*.md"))
    offenders: list[str] = []

    for path in targets:
        text = path.read_text(encoding="utf-8")
        hits = _bidi_locations(text)
        if hits:
            preview = ", ".join(f"{code}@{idx}" for idx, code in hits[:5])
            offenders.append(f"{path.relative_to(ROOT)} -> {preview}")

    assert not offenders, "Bidi control characters found: " + "; ".join(offenders)
