"""Tests to ensure critical just helper recipes remain discoverable."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"
QUICK_START_DOC = REPO_ROOT / "docs" / "raspi_cluster_setup.md"
OPERATIONS_DOC = REPO_ROOT / "docs" / "raspi_cluster_operations.md"
MANUAL_SETUP_DOC = REPO_ROOT / "docs" / "raspi_cluster_setup_manual.md"


@pytest.fixture(scope="module")
def justfile_text() -> str:
    return JUSTFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def quick_start_text() -> str:
    return QUICK_START_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def operations_text() -> str:
    return OPERATIONS_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manual_setup_text() -> str:
    return MANUAL_SETUP_DOC.read_text(encoding="utf-8")


# Test that helper recipes exist in justfile
def test_ha3_recipe_exists(justfile_text: str) -> None:
    """The ha3 recipe should exist in the justfile."""
    assert "ha3 env='dev':" in justfile_text or "ha3:" in justfile_text


def test_ha3_recipe_has_correct_purpose(justfile_text: str) -> None:
    """The ha3 recipe should set SUGARKUBE_SERVERS=3 and call just up."""
    # Find the ha3 recipe
    ha3_start = justfile_text.find("ha3 env='dev':")
    if ha3_start == -1:
        ha3_start = justfile_text.find("ha3:")
    assert ha3_start != -1, "ha3 recipe not found"

    # Get the recipe body (next ~300 characters after the recipe declaration)
    ha3_section = justfile_text[ha3_start : ha3_start + 300]

    assert "SUGARKUBE_SERVERS=3" in ha3_section
    assert "just" in ha3_section and "up" in ha3_section


def test_save_logs_recipe_exists(justfile_text: str) -> None:
    """The save-logs recipe should exist in the justfile."""
    assert "save-logs env='dev':" in justfile_text or "save-logs:" in justfile_text


def test_save_logs_recipe_has_correct_purpose(justfile_text: str) -> None:
    """The save-logs recipe should set SAVE_DEBUG_LOGS=1 and call just up."""
    save_logs_start = justfile_text.find("save-logs env='dev':")
    if save_logs_start == -1:
        save_logs_start = justfile_text.find("save-logs:")
    assert save_logs_start != -1, "save-logs recipe not found"

    # Get the recipe body (next ~300 characters after the recipe declaration)
    save_logs_section = justfile_text[save_logs_start : save_logs_start + 300]

    assert "SAVE_DEBUG_LOGS=1" in save_logs_section
    assert "just" in save_logs_section and "up" in save_logs_section


def test_cat_node_token_recipe_exists(justfile_text: str) -> None:
    """The cat-node-token recipe should exist in the justfile."""
    assert "cat-node-token:" in justfile_text


def test_cat_node_token_recipe_has_correct_purpose(justfile_text: str) -> None:
    """The cat-node-token recipe should read the k3s node token."""
    cat_token_start = justfile_text.find("cat-node-token:")
    assert cat_token_start != -1, "cat-node-token recipe not found"

    # Get the recipe body (next ~300 characters after the recipe declaration)
    cat_token_section = justfile_text[cat_token_start : cat_token_start + 300]

    assert "/var/lib/rancher/k3s/server/node-token" in cat_token_section
    assert "sudo" in cat_token_section or "cat" in cat_token_section


# Test that helper recipes are documented in at least one doc
def test_ha3_mentioned_in_docs(
    quick_start_text: str, operations_text: str, manual_setup_text: str
) -> None:
    """The ha3 recipe should be mentioned in at least one core doc."""
    assert any(
        "ha3" in text for text in (quick_start_text, operations_text, manual_setup_text)
    ), "ha3 recipe should be documented in at least one of the core docs"


def test_save_logs_mentioned_in_docs(
    quick_start_text: str, operations_text: str, manual_setup_text: str
) -> None:
    """The save-logs recipe should be mentioned in at least one core doc."""
    assert any(
        "save-logs" in text for text in (quick_start_text, operations_text, manual_setup_text)
    ), "save-logs recipe should be documented in at least one of the core docs"


def test_cat_node_token_mentioned_in_docs(
    quick_start_text: str, operations_text: str, manual_setup_text: str
) -> None:
    """The cat-node-token recipe should be mentioned in at least one core doc."""
    assert any(
        "cat-node-token" in text for text in (quick_start_text, operations_text, manual_setup_text)
    ), "cat-node-token recipe should be documented in at least one of the core docs"


# Test that the quick start doc has a reference section for the helpers
def test_quick_start_has_reference_section(quick_start_text: str) -> None:
    """The quick start doc should have a reference section listing the key commands."""
    # Check for a section that lists the commands - look for patterns
    assert any(
        pattern in quick_start_text
        for pattern in [
            "Quick reference",
            "just ha3",
            "just save-logs",
            "just cat-node-token",
        ]
    ), "Quick start should document the helper recipes"
