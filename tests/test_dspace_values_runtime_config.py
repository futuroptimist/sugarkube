"""Guardrails for DSPACE token.place runtime routing values."""

from __future__ import annotations

import re
from pathlib import Path

DSPACE_OVERLAYS = [
    Path("docs/examples/dspace.values.staging.yaml"),
    Path("docs/examples/dspace.values.prod.yaml"),
]


def _env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    current_name: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        name_match = re.match(r"\s*-\s+name:\s+([^\s#]+)\s*$", line)
        if name_match:
            current_name = name_match.group(1)
            continue
        value_match = re.match(r"\s+value:\s+(.+?)\s*$", line)
        if value_match and current_name is not None:
            values[current_name] = value_match.group(1).strip('"\'')
            current_name = None
    return values


def test_dspace_staging_routes_to_staging_token_place() -> None:
    env = _env_values(Path("docs/examples/dspace.values.staging.yaml"))

    assert env["DSPACE_TOKEN_PLACE_URL"] == "https://staging.token.place"
    assert env["DSPACE_TOKEN_PLACE_CHAT_MODEL"] == "gpt-5-chat-latest"


def test_dspace_prod_routes_to_prod_token_place() -> None:
    env = _env_values(Path("docs/examples/dspace.values.prod.yaml"))

    assert env["DSPACE_TOKEN_PLACE_URL"] == "https://token.place"
    assert env["DSPACE_TOKEN_PLACE_CHAT_MODEL"] == "gpt-5-chat-latest"


def test_dspace_runtime_overlays_do_not_use_vite_build_time_fallbacks() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DSPACE_OVERLAYS)

    assert "VITE_TOKEN_PLACE_URL" not in combined
    assert "VITE_TOKEN_PLACE_CHAT_MODEL" not in combined


def test_dspace_runtime_overlays_do_not_include_token_place_credentials() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DSPACE_OVERLAYS)

    assert "Authorization" not in combined
    assert ("api" + "Key") not in combined
    assert "credential" not in combined.lower()
