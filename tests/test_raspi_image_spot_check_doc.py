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
        "### Core workflow",
        "#### Step 1. Align the boot order (only if needed)",
        "#### Step 2. Clone the SD card to NVMe",
        "#### Step 3. Verification checklist",
        "### Optional helpers and automations",
        "#### Optional: reset mounts before cloning",
        "#### Optional: one-command migration",
        "#### Optional: one-time SD override",
        "#### Optional: troubleshoot an early failure",
        "## Finalize and continue to k3s setup",
    ]
    for heading in headings:
        assert heading in doc_text, f"Missing expected heading: {heading}"


def test_doc_command_blocks(doc_text: str) -> None:
    commands = [
        "sudo just spot-check",
        "sudo just boot-order sd-nvme-usb",
        "sudo PCIE_PROBE=1 just boot-order nvme-first",
        "sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd",
        "sudo TARGET=/dev/nvme0n1 just clone-ssd",
        "sudo just clean-mounts -- --verbose",
        "sudo just migrate-to-nvme",
        "sudo rpi-eeprom-config --set 'set_reboot_order=0xf1'",
        "sudo shutdown now",
        "lsblk -o NAME,MOUNTPOINT,SIZE,PARTUUID",
    ]
    for command in commands:
        assert command in doc_text, f"Guide should reference '{command}'"


def test_clone_commands_do_not_use_shell_semicolon_assignment(doc_text: str) -> None:
    semicolon_pattern = re.compile(
        r"TARGET=/dev[^\n]*;|WIPE=1;[ ]*sudo [^\n]*just clone-ssd"
    )
    assignment_after_recipe = re.compile(r"just clone-ssd[^`\n]*\b[A-Z][A-Z0-9_]*=")
    assert not semicolon_pattern.search(
        doc_text
    ), "Commands should export variables inline instead of using ';' separators"
    assert not assignment_after_recipe.search(
        doc_text
    ), "Commands should export variables before invoking 'just clone-ssd'"


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


def test_doc_links_to_cluster_setup(doc_text: str) -> None:
    assert "[k3s cluster setup](./raspi_cluster_setup.md)" in doc_text
