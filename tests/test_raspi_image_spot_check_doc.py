"""Verify the Raspberry Pi spot-check guide stays in sync with automation."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "raspi-image-spot-check.md"


def _extract_command_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.lstrip("> ")
        if stripped.startswith("```"):
            if in_block:
                block_text = "\n".join(current).strip()
                if block_text and (
                    block_text.startswith("cd ") or block_text.startswith("sudo ")
                ):
                    blocks.append(block_text)
                current = []
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            current.append(stripped)
    return blocks


def test_spot_check_doc_commands_are_expected() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    blocks = _extract_command_blocks(text)
    expected = [
        "cd ~/sugarkube\nsudo just spot-check",
        "sudo just boot-order sd-nvme-usb",
        "sudo PCIE_PROBE=1 just boot-order nvme-first",
        "sudo just install-rpi-clone",
        "sudo rpi-clone -f -U /dev/nvme0n1",
        "sudo just migrate-to-nvme",
        "sudo rpi-eeprom-config --set 'set_reboot_order=0xf1'",
        "sudo mount /dev/nvme0n1p1 /mnt/clone\n"
        "sudo sed -n '1,120p' /mnt/clone/cmdline.txt\n"
        "sudo sed -n '1,120p' /mnt/clone/etc/fstab\n"
        "sudo umount /mnt/clone",
    ]
    assert blocks == expected, (
        "docs/raspi-image-spot-check.md code snippets changed; "
        "update tests/test_raspi_image_spot_check_doc.py accordingly"
    )


def test_spot_check_doc_key_sections_present() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    required_sections = [
        "# Raspberry Pi 5 Image Spot Check (Bookworm)",
        "## Required success criteria",
        "## Known benign noise",
        "## Next steps: clone to NVMe",
        "### 1. Align the boot order (only if needed)",
        "### 2. Clone the SD card to NVMe",
        "### 3. Optional: one-command migration",
        "### Verification checklist",
    ]
    for section in required_sections:
        assert section in text, f"Missing section '{section}' in raspi-image-spot-check.md"
