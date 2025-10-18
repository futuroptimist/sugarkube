from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CLONE_SSD_EXPECTATIONS: list[tuple[str, list[str]]] = [
    (
        "docs/raspi-image-spot-check.md",
        [
            "sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd",
            "sudo TARGET=/dev/nvme0n1 just clone-ssd",
        ],
    ),
    (
        "docs/pi_image_quickstart.md",
        [
            'sudo CLONE_TARGET=/dev/sda make clone-ssd CLONE_ARGS="--dry-run"',
            'sudo CLONE_TARGET=/dev/sda CLONE_ARGS="--resume" just clone-ssd',
        ],
    ),
    (
        "docs/pi_carrier_field_guide.md",
        [
            'sudo CLONE_TARGET=/dev/sdX CLONE_ARGS="--resume" just clone-ssd',
        ],
    ),
]


@pytest.mark.parametrize("doc_path, expected_commands", CLONE_SSD_EXPECTATIONS)
def test_docs_document_expected_clone_wrappers(
    doc_path: str, expected_commands: list[str]
) -> None:
    doc_text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")
    for command in expected_commands:
        assert (
            command in doc_text
        ), f"{doc_path} should document the '{command}' wrapper"


@pytest.mark.parametrize("doc_path", [item[0] for item in CLONE_SSD_EXPECTATIONS])
def test_clone_wrappers_do_not_use_semicolon_assignments(doc_path: str) -> None:
    doc_text = (REPO_ROOT / doc_path).read_text(encoding="utf-8")
    semicolon_pattern = re.compile(r"just clone-ssd[^\n]*;")
    assignment_after_recipe = re.compile(r"just clone-ssd[^`\n]*\b[A-Z][A-Z0-9_]*=")
    assert not semicolon_pattern.search(
        doc_text
    ), f"{doc_path} should not rely on ';' to pass environment variables"
    assert not assignment_after_recipe.search(
        doc_text
    ), (
        f"{doc_path} should export environment variables before invoking 'just clone-ssd'"
    )
