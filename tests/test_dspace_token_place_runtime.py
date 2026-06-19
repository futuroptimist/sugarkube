"""Regression tests for DSPACE token.place runtime routing overlays."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = {
    "staging": REPO_ROOT / "docs/examples/dspace.values.staging.yaml",
    "prod": REPO_ROOT / "docs/examples/dspace.values.prod.yaml",
}
EXPECTED_URLS = {
    "staging": "https://staging.token.place",
    "prod": "https://token.place",
}
EXPECTED_MODEL = "gpt-5-chat-latest"
FORBIDDEN_RUNTIME_NAMES = {"VITE_TOKEN_PLACE_URL", "VITE_TOKEN_PLACE_CHAT_MODEL"}
FORBIDDEN_SECRET_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"Author" r"ization\s*:",
        r"api" r"Key\s*:",
        r"cred" r"ential\s*:",
        r"token\.place.*(key|secret|token)",
    )
]


def _env_entries(path: Path) -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}
    current_name: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- name: "):
            current_name = line.removeprefix("- name: ").strip().strip('"\'')
            entries.setdefault(current_name, [])
        elif current_name and line.startswith("value: "):
            value = line.removeprefix("value: ").strip().strip('"\'')
            entries[current_name].append(value)
            current_name = None
    return entries


def test_dspace_overlays_select_expected_token_place_runtime_origin_and_model() -> None:
    for env, path in OVERLAYS.items():
        entries = _env_entries(path)
        assert entries.get("DSPACE_TOKEN_PLACE_URL") == [EXPECTED_URLS[env]]
        assert entries.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") == [EXPECTED_MODEL]


def test_dspace_overlays_do_not_use_vite_runtime_fallbacks_or_credentials() -> None:
    for path in OVERLAYS.values():
        text = path.read_text(encoding="utf-8")
        entries = _env_entries(path)
        assert FORBIDDEN_RUNTIME_NAMES.isdisjoint(entries)
        for forbidden in FORBIDDEN_RUNTIME_NAMES:
            assert forbidden not in text
        for pattern in FORBIDDEN_SECRET_PATTERNS:
            assert not pattern.search(text), f"forbidden pattern {pattern.pattern!r} in {path}"


def test_dspace_app_config_preserves_dev_plus_environment_overlay_chain() -> None:
    expected_values = {
        "staging": "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.staging.yaml",
        "prod": "docs/examples/dspace.values.dev.yaml,docs/examples/dspace.values.prod.yaml",
    }
    for env, values in expected_values.items():
        result = subprocess.run(
            ["python3", "scripts/app_config.py", "shell", "--app", "dspace", "--env", env],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        assert f"SUGARKUBE_VALUES={values}" in result.stdout
