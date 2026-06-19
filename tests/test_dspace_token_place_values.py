"""Guardrails for DSPACE token.place runtime routing values."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DSPACE_OVERLAYS = {
    "staging": REPO_ROOT / "docs" / "examples" / "dspace.values.staging.yaml",
    "prod": REPO_ROOT / "docs" / "examples" / "dspace.values.prod.yaml",
}
EXPECTED_URLS = {
    "staging": "https://staging.token.place",
    "prod": "https://token.place",
}
EXPECTED_MODEL = "gpt-5-chat-latest"
FORBIDDEN_RUNTIME_NAMES = ("VITE_TOKEN_PLACE_URL", "VITE_TOKEN_PLACE_CHAT_MODEL")
FORBIDDEN_SECRET_PATTERNS = (
    re.compile(r"Authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"api" + r"Key\s*[:=]", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
)


def _runtime_env(text: str) -> dict[str, str]:
    """Extract the chart's simple env list from a values overlay."""

    entries = re.findall(
        r"^\s*-\s+name:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\n\s+value:\s*([^\n#]+)",
        text,
        flags=re.MULTILINE,
    )
    return {name: value.strip().strip('"\'') for name, value in entries}


def test_dspace_overlays_select_expected_token_place_runtime_origins() -> None:
    for env_name, path in DSPACE_OVERLAYS.items():
        env = _runtime_env(path.read_text(encoding="utf-8"))

        assert env.get("DSPACE_TOKEN_PLACE_URL") == EXPECTED_URLS[env_name]
        assert env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") == EXPECTED_MODEL


def test_dspace_overlays_do_not_set_vite_runtime_fallbacks() -> None:
    for path in DSPACE_OVERLAYS.values():
        text = path.read_text(encoding="utf-8")

        for forbidden_name in FORBIDDEN_RUNTIME_NAMES:
            assert forbidden_name not in text


def test_dspace_overlays_do_not_embed_token_place_credentials() -> None:
    for path in DSPACE_OVERLAYS.values():
        text = path.read_text(encoding="utf-8")

        for forbidden_pattern in FORBIDDEN_SECRET_PATTERNS:
            assert not forbidden_pattern.search(text)
