"""Assertions that guard justfile syntax for flash recipes."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _extract_recipe(target: str) -> tuple[str, list[str]]:
    """Return the header and body lines for a just recipe."""

    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    header = None
    body: list[str] = []
    capture = False
    prefix = f"{target}:"
    for line in lines:
        if capture:
            if line.startswith("    "):
                body.append(line)
                continue
            if line == "":
                break
            if line.startswith("#"):
                break
            break
        if line.startswith(prefix):
            header = line
            capture = True
    if header is None:
        pytest.fail(f"{target} recipe missing from justfile")
    return header, body


def test_justfile_has_no_tabs_or_trailing_whitespace() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")
    assert "\t" not in text, "Tab characters should never appear in the justfile"
    for index, line in enumerate(text.splitlines(), start=1):
        assert line == line.rstrip(), f"Trailing whitespace found on line {index}"


@pytest.mark.parametrize(
    "target, expected_header, expected_body",
    [
        (
            "flash-pi",
            "flash-pi: install-pi-image",
            [
                '    if [ -z "{{ flash_device }}" ]; then echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi." >&2; exit 1; fi',
                '    "{{ flash_cmd }}" --image "{{ image_path }}" --device "{{ flash_device }}" {{ flash_args }}',
            ],
        ),
        (
            "flash-pi-report",
            "flash-pi-report: install-pi-image",
            [
                '    if [ -z "{{ flash_device }}" ]; then echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi-report." >&2; exit 1; fi',
                '    "{{ flash_report_cmd }}" --image "{{ image_path }}" --device "{{ flash_device }}" {{ flash_args }} {{ flash_report_args }}',
            ],
        ),
    ],
)
def test_flash_recipes_have_expected_guards_and_commands(
    target: str, expected_header: str, expected_body: list[str]
) -> None:
    header, body = _extract_recipe(target)
    assert header == expected_header
    assert body == expected_body
    assert all(line.startswith("    ") for line in body), "Commands must use four-space indent"
