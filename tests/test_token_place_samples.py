"""Validate bundled token.place sample assets and replay helper."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples" / "token_place"
SCRIPT = ROOT / "scripts" / "token_place_replay_samples.py"


def test_openai_sample_payload_round_trips() -> None:
    payload_path = SAMPLES_DIR / "openai-chat-demo.json"
    with payload_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["model"]
    assert payload["messages"], "messages array must not be empty"
    assert payload["messages"][0]["role"] == "system"


def test_postman_collection_has_requests() -> None:
    collection_path = SAMPLES_DIR / "postman" / "tokenplace-first-boot.postman_collection.json"
    with collection_path.open("r", encoding="utf-8") as handle:
        collection = json.load(handle)
    names = [item["name"] for item in collection.get("item", [])]
    assert {"Health", "List models", "Chat completion (mock)"}.issubset(set(names))


def test_replay_script_dry_run(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            str(SCRIPT),
            "--dry-run",
            "--samples-dir",
            str(SAMPLES_DIR),
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Dry run OK" in proc.stdout
