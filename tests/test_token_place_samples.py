"""Validate bundled token.place sample assets and replay helper."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Iterable

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples" / "token_place"
SCRIPT = ROOT / "scripts" / "token_place_replay_samples.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("token_place_replay_samples", SCRIPT)
    assert spec and spec.loader, "unable to load replay helper"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


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


def test_load_sample_invalid_json(tmp_path: Path) -> None:
    broken = tmp_path / "sample.json"
    broken.write_text("{not-json}", encoding="utf-8")
    with pytest.raises(MODULE.ReplayError) as exc:
        MODULE._load_sample(broken)
    assert "invalid JSON" in str(exc.value)


def test_candidate_urls_strip_trailing_slash() -> None:
    urls = list(MODULE._candidate_urls("http://example.com/", ["/health", "/models"]))
    assert urls == ["http://example.com/health", "http://example.com/models"]


def test_http_request_handles_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyHeaders:
        def get_content_charset(self, default: str) -> str:
            return "utf-8"

    class DummyResponse:
        headers = DummyHeaders()

        def __enter__(self) -> "DummyResponse":
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(req, timeout: int):  # type: ignore[no-untyped-def]
        assert req.get_full_url() == "http://example.com/api"
        headers = {k.lower(): v for k, v in req.headers.items()}
        assert headers["content-type"] == "application/json"
        assert json.loads(req.data.decode("utf-8")) == {"hello": "world"}
        assert timeout == 5
        return DummyResponse()

    monkeypatch.setattr(MODULE.request, "urlopen", fake_urlopen)
    result = MODULE._http_request(
        "http://example.com/api",
        method="POST",
        timeout=5,
        payload={"hello": "world"},
    )
    assert result == {"ok": True}


def test_http_request_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyHeaders:
        def get_content_charset(self, default: str) -> str:
            return "utf-8"

    class DummyResponse:
        headers = DummyHeaders()

        def __enter__(self) -> "DummyResponse":
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return b"not json"

    def fake_urlopen(req, timeout: int):  # type: ignore[no-untyped-def]
        return DummyResponse()

    monkeypatch.setattr(MODULE.request, "urlopen", fake_urlopen)
    with pytest.raises(MODULE.ReplayError) as exc:
        MODULE._http_request("http://example.com/api", timeout=1)
    assert "Non-JSON response" in str(exc.value)


def test_probe_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def fake_http(url: str, **_: object) -> dict:
        attempts.append(url)
        if url.endswith("/good"):
            return {"ok": True}
        raise MODULE.error.URLError("nope")

    monkeypatch.setattr(MODULE, "_http_request", fake_http)
    url, payload = MODULE._probe_first(
        "http://host",
        MODULE._candidate_urls("http://host", ["/bad", "/good"]),
        timeout=1,
    )
    assert attempts == ["http://host/bad", "http://host/good"]
    assert url.endswith("/good")
    assert payload == {"ok": True}


def test_probe_first_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_http(url: str, **_: object) -> dict:
        raise MODULE.error.HTTPError(url, 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr(MODULE, "_http_request", fake_http)
    with pytest.raises(MODULE.ReplayError):
        MODULE._probe_first(
            "http://host",
            MODULE._candidate_urls("http://host", ["/boom"]),
            timeout=1,
        )


def test_replay_samples_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_probe(_: str, candidates: Iterable[str], **kwargs: object) -> tuple[str, dict]:
        urls = list(candidates)
        assert kwargs["timeout"] == 7
        if any("chat" in url for url in urls):
            return urls[0], {
                "choices": [
                    {"message": {"content": "Assistant reply\nMore text"}},
                ]
            }
        if any("models" in url for url in urls):
            return urls[0], {"data": ["model-a", "model-b"]}
        return urls[0], {"status": "ok"}

    monkeypatch.setattr(MODULE, "_probe_first", fake_probe)
    MODULE.replay_samples(
        base_url="http://token.place",
        samples_dir=SAMPLES_DIR,
        output_dir=tmp_path,
        timeout=7,
    )

    outputs = {p.name for p in tmp_path.iterdir()}
    assert {"health.json", "models.json", "chat.json"} == outputs


def test_replay_samples_missing_assistant(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_probe(_: str, candidates: Iterable[str], **kwargs: object) -> tuple[str, dict]:
        urls = list(candidates)
        if any("chat" in url for url in urls):
            return urls[0], {"choices": [{"message": {}}]}
        return urls[0], {"status": "ok"}

    monkeypatch.setattr(MODULE, "_probe_first", fake_probe)
    with pytest.raises(MODULE.ReplayError):
        MODULE.replay_samples(
            base_url="http://token.place",
            samples_dir=SAMPLES_DIR,
            output_dir=tmp_path,
            timeout=5,
        )


def test_main_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = {}

    def fake_replay(**kwargs: object) -> None:
        called.update(kwargs)

    monkeypatch.setattr(MODULE, "replay_samples", fake_replay)
    exit_code = MODULE.main(
        [
            "--base-url",
            "http://token.place",
            "--samples-dir",
            str(SAMPLES_DIR),
            "--output-dir",
            str(tmp_path),
            "--timeout",
            "3",
        ]
    )
    assert exit_code == 0
    assert called["timeout"] == 3


def test_main_missing_samples(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()
    exit_code = MODULE.main(["--samples-dir", str(missing_dir)])
    assert exit_code == 1


def test_main_replay_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def raise_replay_error(**_: object) -> None:
        raise MODULE.ReplayError("fail")

    monkeypatch.setattr(MODULE, "replay_samples", raise_replay_error)
    exit_code = MODULE.main(
        [
            "--samples-dir",
            str(SAMPLES_DIR),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 2


def test_main_http_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(**_: object) -> None:
        raise MODULE.error.HTTPError("http://token.place", 500, "boom", hdrs=None, fp=None)

    monkeypatch.setattr(MODULE, "replay_samples", boom)
    exit_code = MODULE.main(
        [
            "--samples-dir",
            str(SAMPLES_DIR),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 3
