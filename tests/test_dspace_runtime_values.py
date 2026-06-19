"""Focused tests for DSPACE token.place runtime Helm values."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = {
    "staging": REPO_ROOT / "docs/examples/dspace.values.staging.yaml",
    "prod": REPO_ROOT / "docs/examples/dspace.values.prod.yaml",
}
TOKEN_PLACE_NAMES = {
    "DSPACE_TOKEN_PLACE_URL",
    "DSPACE_TOKEN_PLACE_CHAT_MODEL",
}
FORBIDDEN_RUNTIME_NAMES = {
    "VITE_TOKEN_PLACE_URL",
    "VITE_TOKEN_PLACE_CHAT_MODEL",
}
FORBIDDEN_SECRET_PATTERNS = (
    re.compile(r"Authorization", re.IGNORECASE),
    re.compile("api" + "Key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
)


def _runtime_env(path: Path) -> dict[str, str]:
    """Parse the simple chart env list used by the DSPACE example overlays."""
    env: dict[str, str] = {}
    in_env = False
    current_name: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "env:":
            in_env = True
            continue
        if not in_env:
            continue
        if line.startswith("- name: "):
            current_name = line.removeprefix("- name: ").strip()
            continue
        if line.startswith("value: ") and current_name is not None:
            env[current_name] = line.removeprefix("value: ").strip().strip('"')
            current_name = None
    return env


def test_dspace_staging_overlay_points_to_staging_token_place() -> None:
    env = _runtime_env(OVERLAYS["staging"])

    assert env["DSPACE_TOKEN_PLACE_URL"] == "https://staging.token.place"
    assert env["DSPACE_TOKEN_PLACE_CHAT_MODEL"] == "gpt-5-chat-latest"


def test_dspace_prod_overlay_points_to_prod_token_place() -> None:
    env = _runtime_env(OVERLAYS["prod"])

    assert env["DSPACE_TOKEN_PLACE_URL"] == "https://token.place"
    assert env["DSPACE_TOKEN_PLACE_CHAT_MODEL"] == "gpt-5-chat-latest"


def test_dspace_deployment_overlays_have_no_vite_runtime_env() -> None:
    for path in OVERLAYS.values():
        env = _runtime_env(path)
        assert TOKEN_PLACE_NAMES <= env.keys()
        assert FORBIDDEN_RUNTIME_NAMES.isdisjoint(env.keys())


def test_dspace_deployment_overlays_do_not_carry_token_place_credentials() -> None:
    for path in OVERLAYS.values():
        text = path.read_text(encoding="utf-8")
        assert "token.place" in text
        for pattern in FORBIDDEN_SECRET_PATTERNS:
            assert pattern.search(text) is None, f"{pattern.pattern} found in {path}"
