"""Ensure the Makefile exposes the SSD validation helper."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_makefile_includes_validate_ssd_clone_target() -> None:
    """The Makefile wrapper should mirror the documented sudo make command."""

    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "validate-ssd-clone:" in makefile_text, "Add a validate-ssd-clone target to the Makefile"
    assert (
        "$(VALIDATE_CMD) $(VALIDATE_ARGS)" in makefile_text
    ), "Make validate-ssd-clone target should invoke the validation helper"
    assert (
        "validate-ssd-clone" in makefile_text.split(".PHONY:", maxsplit=1)[1]
    ), ".PHONY list should include validate-ssd-clone"
