"""Validate bundled token.place sample assets and replay helper."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples" / "token_place"
SCRIPT = ROOT / "scripts" / "token_place_replay_samples.py"

spec = importlib.util.spec_from_file_location("token_place_replay_samples", SCRIPT)
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)  # type: ignore[misc]


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
    bad_sample = tmp_path / "bad.json"
    bad_sample.write_text("not json", encoding="utf-8")
    with pytest.raises(replay.ReplayError):
        replay._load_sample(bad_sample)  # noqa: SLF001


def test_candidate_urls_strips_trailing_slash() -> None:
    urls = list(replay._candidate_urls("http://host/", ("/one", "/two")))  # noqa: SLF001
    assert urls == ["http://host/one", "http://host/two"]


def _fake_headers(charset: str = "utf-8") -> Any:
    return SimpleNamespace(
        get_content_charset=lambda default="utf-8": charset or default,
    )


class DummyResponse:
    def __init__(self, body: str, *, charset: str = "utf-8") -> None:
        self._body = body
        self.headers = _fake_headers(charset)

    def read(self) -> bytes:
        return self._body.encode(self.headers.get_content_charset())

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_http_request_get(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: int) -> DummyResponse:
        captured["method"] = req.method
        captured["headers"] = req.headers
        captured["timeout"] = timeout
        return DummyResponse("{}")

    monkeypatch.setattr(replay.request, "urlopen", fake_urlopen)
    result = replay._http_request("http://example", timeout=5)  # noqa: SLF001
    assert result == {}
    assert captured["method"] == "GET"
    assert captured["timeout"] == 5
    assert captured["headers"]["Accept"] == "application/json"


def test_http_request_post(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: int) -> DummyResponse:
        captured["method"] = req.method
        captured["data"] = req.data
        captured["headers"] = req.headers
        captured["timeout"] = timeout
        return DummyResponse("{}")

    monkeypatch.setattr(replay.request, "urlopen", fake_urlopen)
    result = replay._http_request(  # noqa: SLF001
        "http://example",
        timeout=4,
        payload={"hello": "world"},
        method="POST",
    )
    assert result == {}
    assert json.loads(captured["data"]) == {"hello": "world"}
    lowered = {key.lower(): value for key, value in captured["headers"].items()}
    assert lowered["content-type"] == "application/json"
    assert captured["timeout"] == 4


def test_http_request_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: Any, timeout: int) -> DummyResponse:
        return DummyResponse("not json")

    monkeypatch.setattr(replay.request, "urlopen", fake_urlopen)
    with pytest.raises(replay.ReplayError):
        replay._http_request("http://example", timeout=3)  # noqa: SLF001


def test_probe_first_tries_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def fake_http(url: str, **_: Any) -> dict[str, str]:
        attempts.append(url)
        if "second" in url:
            return {"ok": "yes"}
        raise replay.ReplayError("nope")

    monkeypatch.setattr(replay, "_http_request", fake_http)  # noqa: SLF001
    url, payload = replay._probe_first("base", ["first", "second"])  # noqa: SLF001
    assert url == "second"
    assert payload == {"ok": "yes"}
    assert attempts == ["first", "second"]


def test_probe_first_no_candidates() -> None:
    with pytest.raises(replay.ReplayError):
        replay._probe_first("base", [])  # noqa: SLF001


def test_replay_samples_writes_reports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sample_payload = {"model": "demo", "messages": [{"role": "system", "content": "x"}]}
    sample_file = tmp_path / replay.DEFAULT_SAMPLE
    sample_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    calls: list[tuple[str, Iterable[str]]] = []

    def fake_probe(
        base_url: str,
        candidates: Iterable[str],
        **_: Any,
    ) -> Tuple[str, dict[str, Any]]:
        calls.append((base_url, tuple(candidates)))
        if len(calls) == 3:
            return "chat", {"choices": [{"message": {"content": "hello world"}}]}
        if len(calls) == 1:
            return "health", {"status": "ok"}
        return "models", {"data": [1, 2]}

    monkeypatch.setattr(replay, "_probe_first", fake_probe)  # noqa: SLF001
    replay.replay_samples(
        base_url="http://token.place",
        samples_dir=tmp_path,
        output_dir=tmp_path / "reports",
        timeout=9,
    )

    outputs = sorted((tmp_path / "reports").glob("*.json"))
    assert [path.name for path in outputs] == ["chat.json", "health.json", "models.json"]
    chat_payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert chat_payload["url"] == "chat"
    assert "hello world" in chat_payload["data"]["choices"][0]["message"]["content"]


def test_replay_samples_requires_assistant(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sample_payload = {"model": "demo", "messages": [{"role": "system", "content": "x"}]}
    sample_file = tmp_path / replay.DEFAULT_SAMPLE
    sample_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    def fake_probe(*_: Any, **__: Any) -> tuple[str, dict[str, Any]]:
        return "chat", {"choices": []}

    monkeypatch.setattr(replay, "_probe_first", fake_probe)  # noqa: SLF001
    with pytest.raises(replay.ReplayError):
        replay.replay_samples(
            base_url="http://token.place",
            samples_dir=tmp_path,
            output_dir=tmp_path / "reports",
            timeout=9,
        )


def test_parse_args_defaults() -> None:
    args = replay.parse_args([])
    assert args.base_url == replay.DEFAULT_BASE_URL
    assert args.timeout == replay.DEFAULT_TIMEOUT


def test_main_missing_sample(tmp_path: Path) -> None:
    missing_dir = tmp_path / "samples"
    exit_code = replay.main(["--samples-dir", str(missing_dir)])
    assert exit_code == 1


def test_main_replay_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    (samples_dir / replay.DEFAULT_SAMPLE).write_text("{}", encoding="utf-8")

    def fake_replay(**_: Any) -> None:
        raise replay.ReplayError("boom")

    monkeypatch.setattr(replay, "replay_samples", fake_replay)
    exit_code = replay.main(["--samples-dir", str(samples_dir)])
    assert exit_code == 2


def test_main_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    (samples_dir / replay.DEFAULT_SAMPLE).write_text("{}", encoding="utf-8")

    called: dict[str, Any] = {}

    def fake_replay(**kwargs: Any) -> None:
        called.update(kwargs)

    monkeypatch.setattr(replay, "replay_samples", fake_replay)
    exit_code = replay.main(
        [
            "--samples-dir",
            str(samples_dir),
            "--base-url",
            "http://custom",
            "--output-dir",
            str(tmp_path / "out"),
            "--timeout",
            "7",
        ]
    )
    assert exit_code == 0
    assert called["base_url"] == "http://custom"
    assert called["timeout"] == 7
