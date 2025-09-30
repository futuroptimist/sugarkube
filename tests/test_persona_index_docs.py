from __future__ import annotations

from pathlib import Path


def _extract_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}

    end = text.find("\n---", 4)
    assert end != -1, f"Front matter not closed in {path}"  # pragma: no cover
    block = text[4:end]

    metadata: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        metadata[key.strip()] = value.strip().strip('"')
    return metadata


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


def test_persona_indexes_expose_front_matter_metadata() -> None:
    hardware_metadata = _extract_front_matter(HARDWARE_INDEX)
    software_metadata = _extract_front_matter(SOFTWARE_INDEX)

    assert (
        hardware_metadata.get("persona") == "hardware"
    ), "docs/hardware/index.md should declare persona: hardware"
    assert (
        software_metadata.get("persona") == "software"
    ), "docs/software/index.md should declare persona: software"

    # Front matter should carry titles so the static site can render navigation labels.
    assert hardware_metadata.get("title") == "Sugarkube Hardware Index"
    assert software_metadata.get("title") == "Sugarkube Software Index"
