"""Regression tests for Danielsmith OCI just wrapper tag normalization."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _recipe_body(justfile_text: str, recipe_name: str) -> str:
    pattern = rf"(?ms)^{re.escape(recipe_name)} .+?(?=^\S|\Z)"
    match = re.search(pattern, justfile_text)
    assert match is not None, f"could not find {recipe_name} recipe"
    return match.group(0)


def _normalize_with_wrapper_shell(value: str) -> str:
    script = r'''
set -Eeuo pipefail
resolved_tag="$(echo "$1" | xargs)"
while [ "${resolved_tag#tag=}" != "${resolved_tag}" ]; do
  resolved_tag="${resolved_tag#tag=}"
done
printf '%s\n' "${resolved_tag}"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", value],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.rstrip("\n")


def test_danielsmith_wrappers_strip_named_tag_prefixes_before_use() -> None:
    """All Danielsmith user-facing tag wrappers strip one or more tag= prefixes."""
    justfile_text = JUSTFILE.read_text(encoding="utf-8")

    for recipe_name in (
        "danielsmith-oci-deploy",
        "danielsmith-oci-promote-prod",
        "danielsmith-oci-redeploy",
    ):
        body = _recipe_body(justfile_text, recipe_name)
        assert "while [ \"${resolved_tag#tag=}\" != \"${resolved_tag}\" ]; do" in body
        assert "resolved_tag=\"${resolved_tag#tag=}\"" in body


def test_danielsmith_tag_normalization_accepts_positional_and_named_forms() -> None:
    """The shell normalization used by the wrappers preserves positional tags."""
    assert _normalize_with_wrapper_shell("main-deadbee") == "main-deadbee"
    assert _normalize_with_wrapper_shell("tag=main-deadbee") == "main-deadbee"
    assert _normalize_with_wrapper_shell("tag=tag=main-deadbee") == "main-deadbee"


def test_danielsmith_tag_normalization_keeps_mutable_tag_text_for_validation() -> None:
    """Mutable named tags normalize to mutable values so existing validation rejects them."""
    assert _normalize_with_wrapper_shell("tag=main") == "main"
    assert _normalize_with_wrapper_shell("tag=main-latest") == "main-latest"
    assert _normalize_with_wrapper_shell("tag=latest") == "latest"
