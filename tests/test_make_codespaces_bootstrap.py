"""Ensure Makefile exposes the codespaces bootstrap helper."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"


def test_makefile_defines_codespaces_bootstrap_target() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    pattern = (
        r"^codespaces-bootstrap:\n"
        r"\tsudo apt-get update\n"
        r"\tsudo apt-get install -y curl gh jq pv unzip xz-utils"
    )
    match = re.search(pattern, text, flags=re.MULTILINE)
    assert match, "Makefile is missing the codespaces bootstrap recipe"
