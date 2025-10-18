from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "raspi-image-spot-check.md"
JUSTFILE = REPO_ROOT / "justfile"


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_sections_present(doc_text: str) -> None:
    headings = [
        "# Raspberry Pi 5 Image Spot Check (Bookworm)",
        "## Required success criteria",
        "## Sample output",
        "## Known benign noise",
        "## Next steps: clone to NVMe",
        "### 1. Align the boot order (only if needed)",
        "### 2. Clone the SD card to NVMe",
        "### 3. Optional: one-command migration",
        "### One-time SD override",
        "### Verification checklist",
    ]
    for heading in headings:
        assert heading in doc_text, f"Missing expected heading: {heading}"


def test_doc_command_blocks(doc_text: str) -> None:
    commands = [
        "sudo just spot-check",
        "sudo just boot-order sd-nvme-usb",
        "sudo PCIE_PROBE=1 just boot-order nvme-first",
        "sudo just clone-ssd TARGET=/dev/nvme0n1 WIPE=1",
        "sudo just clone-ssd TARGET=/dev/nvme0n1",
        "sudo just migrate-to-nvme",
    ]
    for command in commands:
        assert command in doc_text, f"Guide should reference '{command}'"


def test_clone_commands_do_not_use_shell_semicolon_assignment(doc_text: str) -> None:
    bad_pattern = re.compile(r"TARGET=/dev[^\n]*;|WIPE=1;[ ]*sudo just clone-ssd")
    assert not bad_pattern.search(
        doc_text
    ), "Commands should export variables inline instead of using ';' separators"


def test_boot_order_recipe_uses_preset() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("boot-order preset"):
            break
    else:
        pytest.fail("boot-order recipe missing from justfile")
    assert '"{{ boot_order_cmd }}" preset "{{ preset }}"' in text


def test_migrate_recipe_delegates_to_script() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    assert 'migrate-to-nvme:' in text
    assert 'scripts/migrate_to_nvme.sh' in text


def test_doc_mentions_artifacts_paths(doc_text: str) -> None:
    expected = [
        "artifacts/spot-check/",
        "artifacts/spot-check/summary.{json,md}",
        "artifacts/clone-to-nvme.log",
        "artifacts/migrate-to-nvme/",
    ]
    for item in expected:
        assert item in doc_text, f"Expected '{item}' to be documented"
