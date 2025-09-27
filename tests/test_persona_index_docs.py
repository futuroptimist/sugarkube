from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARDWARE_INDEX = REPO_ROOT / "docs" / "hardware" / "index.md"
SOFTWARE_INDEX = REPO_ROOT / "docs" / "software" / "index.md"


def test_hardware_index_exists_and_lists_core_guides() -> None:
    assert HARDWARE_INDEX.exists(), "docs/hardware/index.md is missing"
    text = HARDWARE_INDEX.read_text(encoding="utf-8")
    expected_snippets = [
        "# Sugarkube Hardware Index",
        "[SAFETY.md]",
        "[build_guide.md]",
        "Pi Carrier Field Guide",
    ]
    for snippet in expected_snippets:
        assert snippet in text, f"Expected '{snippet}' in hardware index"


def test_software_index_exists_and_lists_core_guides() -> None:
    assert SOFTWARE_INDEX.exists(), "docs/software/index.md is missing"
    text = SOFTWARE_INDEX.read_text(encoding="utf-8")
    expected_snippets = [
        "# Sugarkube Software Index",
        "[pi_image_quickstart.md]",
        "[pi_image_contributor_guide.md]",
        "Pi Support Bundles",
    ]
    for snippet in expected_snippets:
        assert snippet in text, f"Expected '{snippet}' in software index"
