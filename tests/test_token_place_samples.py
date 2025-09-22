"""Validate bundled token.place sample assets and replay helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from urllib import error

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples" / "token_place"

_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "token_place_replay_samples", ROOT / "scripts" / "token_place_replay_samples.py"
)
assert _SCRIPT_SPEC and _SCRIPT_SPEC.loader
replay = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(replay)


class _DummyHeaders:
    def get_content_charset(self, default: str) -> str:
        return default


class _DummyResponse:
    def __init__(self, body: str):
        self._body = body
        self.headers = _DummyHeaders()

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, *args: Any) -> None:  # pragma: no cover - no cleanup needed
        return None


def _make_sample_dir(tmp_path: Path) -> Path:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    payload = {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ],
    }
    sample_path = samples_dir / replay.DEFAULT_SAMPLE
    with sample_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return samples_dir


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


def test_candidate_urls_strips_trailing_slash() -> None:
    urls = list(replay._candidate_urls("http://example.com/", ("/one", "/two")))
    assert urls == ["http://example.com/one", "http://example.com/two"]


def test_http_request_handles_get_and_post(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_urlopen(req: replay.request.Request, timeout: int) -> _DummyResponse:
        calls.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "data": None if req.data is None else req.data.decode("utf-8"),
                "timeout": timeout,
            }
        )
        bodies = [json.dumps({"status": "ok"}), json.dumps({"data": [1]})]
        return _DummyResponse(bodies[len(calls) - 1])

    monkeypatch.setattr(replay.request, "urlopen", fake_urlopen)

    get_result = replay._http_request("http://example.com/health", timeout=5)
    post_result = replay._http_request(
        "http://example.com/chat",
        timeout=5,
        payload={"foo": "bar"},
        method="POST",
    )

    assert get_result == {"status": "ok"}
    assert post_result == {"data": [1]}
    assert calls[0]["method"] == "GET"
    assert calls[1]["method"] == "POST"
    assert json.loads(calls[1]["data"]) == {"foo": "bar"}


def test_http_request_raises_for_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(*args: Any, **kwargs: Any) -> _DummyResponse:
        return _DummyResponse("not-json")

    monkeypatch.setattr(replay.request, "urlopen", fake_urlopen)

    with pytest.raises(replay.ReplayError, match="Non-JSON response"):
        replay._http_request("http://example.com", timeout=1)


def test_probe_first_returns_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_http_request(url: str, **_: Any) -> dict[str, str]:
        calls.append(url)
        if "models" in url:
            return {"ok": True}
        raise replay.ReplayError("boom")

    monkeypatch.setattr(replay, "_http_request", fake_http_request)
    url, payload = replay._probe_first("http://example", ["/health", "/models"])
    assert url.endswith("/models")
    assert payload == {"ok": True}
    assert len(calls) == 2


def test_probe_first_raises_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_http_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise replay.ReplayError("last failure")

    monkeypatch.setattr(replay, "_http_request", fake_http_request)

    with pytest.raises(replay.ReplayError, match="last failure"):
        replay._probe_first("http://example", ["/one", "/two"])


def test_probe_first_raises_for_empty_candidates() -> None:
    with pytest.raises(replay.ReplayError, match="No candidates provided"):
        replay._probe_first("http://example", [])


def test_load_sample_invalid_json(tmp_path: Path) -> None:
    bad_sample = tmp_path / "bad.json"
    bad_sample.write_text("{", encoding="utf-8")

    with pytest.raises(replay.ReplayError, match="invalid JSON"):
        replay._load_sample(bad_sample)


def test_replay_samples_writes_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    samples_dir = _make_sample_dir(tmp_path)
    output_dir = tmp_path / "reports"

    responses = iter(
        [
            ("http://example/health", {"status": "pass"}),
            ("http://example/models", {"data": [{"id": "gpt"}]}),
            (
                "http://example/chat",
                {
                    "choices": [
                        {"message": {"content": "Assistant hello\nMore"}},
                    ]
                },
            ),
        ]
    )

    def fake_probe_first(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        return next(responses)

    monkeypatch.setattr(replay, "_probe_first", fake_probe_first)

    replay.replay_samples(
        base_url="http://example",
        samples_dir=samples_dir,
        output_dir=output_dir,
        timeout=3,
    )

    for name in ("health", "models", "chat"):
        report_path = output_dir / f"{name}.json"
        assert report_path.exists()
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert "url" in data and "data" in data


def test_replay_samples_requires_assistant_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples_dir = _make_sample_dir(tmp_path)

    responses = iter(
        [
            ("http://example/health", {"status": "pass"}),
            ("http://example/models", {"data": []}),
            ("http://example/chat", {"choices": [{}]}),
        ]
    )

    def fake_probe_first(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        return next(responses)

    monkeypatch.setattr(replay, "_probe_first", fake_probe_first)

    with pytest.raises(replay.ReplayError, match="assistant message"):
        replay.replay_samples(
            base_url="http://example",
            samples_dir=samples_dir,
            output_dir=tmp_path / "out",
            timeout=2,
        )


def test_parse_args_round_trip() -> None:
    args = replay.parse_args(
        [
            "--base-url",
            "http://override",
            "--samples-dir",
            "/tmp/samples",
            "--output-dir",
            "/tmp/out",
            "--timeout",
            "15",
            "--dry-run",
        ]
    )

    assert args.base_url == "http://override"
    assert args.samples_dir == "/tmp/samples"
    assert args.output_dir == "/tmp/out"
    assert args.timeout == 15
    assert args.dry_run is True


def test_main_returns_one_when_sample_missing(tmp_path: Path) -> None:
    rc = replay.main(
        [
            "--samples-dir",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 1


def test_main_dry_run(tmp_path: Path) -> None:
    samples_dir = _make_sample_dir(tmp_path)
    rc = replay.main(
        [
            "--samples-dir",
            str(samples_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )
    assert rc == 0


def test_main_success_invokes_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    samples_dir = _make_sample_dir(tmp_path)
    called: dict[str, Any] = {}

    def fake_replay_samples(**kwargs: Any) -> None:
        called.update(kwargs)

    monkeypatch.setattr(replay, "replay_samples", fake_replay_samples)
    rc = replay.main(
        [
            "--samples-dir",
            str(samples_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--base-url",
            "http://override",
            "--timeout",
            "42",
        ]
    )

    assert rc == 0
    assert called["base_url"] == "http://override"
    assert called["timeout"] == 42


def test_main_handles_replay_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    samples_dir = _make_sample_dir(tmp_path)

    def fake_replay_samples(**kwargs: Any) -> None:
        raise replay.ReplayError("boom")

    monkeypatch.setattr(replay, "replay_samples", fake_replay_samples)

    rc = replay.main(
        [
            "--samples-dir",
            str(samples_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert rc == 2


def test_main_handles_url_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    samples_dir = _make_sample_dir(tmp_path)

    def fake_replay_samples(**kwargs: Any) -> None:
        raise error.URLError("boom")

    monkeypatch.setattr(replay, "replay_samples", fake_replay_samples)

    rc = replay.main(
        [
            "--samples-dir",
            str(samples_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert rc == 3
