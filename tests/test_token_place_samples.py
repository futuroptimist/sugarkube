"""Validate bundled token.place sample assets and replay helper."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib import error

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples" / "token_place"
SCRIPT = ROOT / "scripts" / "token_place_replay_samples.py"

SPEC = importlib.util.spec_from_file_location("token_place_replay_samples", SCRIPT)
assert SPEC and SPEC.loader
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)  # type: ignore[assignment]


def _handler_factory(responders):
    class _Handler(BaseHTTPRequestHandler):
        def _dispatch(self) -> None:
            status, body, headers = responders.get(
                (self.command, self.path),
                (404, {"error": "not found"}, {"Content-Type": "application/json"}),
            )
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if isinstance(body, bytes):
                payload = body
            elif isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = json.dumps(body).encode("utf-8")
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            self._dispatch()

        def log_message(self, format: str, *args: object) -> None:  # pragma: no cover - noisy
            return

    return _Handler


@contextlib.contextmanager
def run_server(responders):
    handler = _handler_factory(responders)
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Give the server a moment to bind
        time.sleep(0.05)
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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
    bogus = tmp_path / "bad.json"
    bogus.write_text("{", encoding="utf-8")
    with pytest.raises(replay.ReplayError):
        replay._load_sample(bogus)


def test_http_request_invalid_json() -> None:
    responders = {
        ("GET", "/v1/health"): (200, "not json", {"Content-Type": "text/plain"}),
    }
    with run_server(responders) as base_url:
        with pytest.raises(replay.ReplayError):
            replay._http_request(f"{base_url}/v1/health", timeout=1)


def test_probe_first_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_http_request(url: str, **_: object) -> dict:
        calls.append(url)
        if len(calls) == 1:
            raise replay.ReplayError("first failed")
        return {"ok": True}

    monkeypatch.setattr(replay, "_http_request", fake_http_request)
    candidates = replay._candidate_urls("http://example.com", ("/one", "/two"))
    url, payload = replay._probe_first("http://example.com", candidates, timeout=1)
    assert url.endswith("/two")
    assert payload == {"ok": True}


def test_probe_first_requires_candidate() -> None:
    with pytest.raises(replay.ReplayError, match="No candidates provided"):
        replay._probe_first("http://example.com", (), timeout=1)


def test_probe_first_surfaces_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **_: object) -> dict:
        raise replay.ReplayError(f"fail for {url}")

    monkeypatch.setattr(replay, "_http_request", boom)
    candidates = replay._candidate_urls("http://example.com", ("/one", "/two"))
    with pytest.raises(replay.ReplayError, match="/two"):
        replay._probe_first("http://example.com", candidates, timeout=1)


def test_replay_samples_happy_path(tmp_path: Path) -> None:
    responders = {
        ("GET", "/v1/health"): (404, {}, {"Content-Type": "application/json"}),
        ("GET", "/api/v1/health"): (200, {"status": "ok"}, {"Content-Type": "application/json"}),
        ("GET", "/v1/models"): (404, {}, {"Content-Type": "application/json"}),
        (
            "GET",
            "/api/v1/models",
        ): (200, {"data": [{"id": "demo"}]}, {"Content-Type": "application/json"}),
        ("POST", "/v1/chat/completions"): (404, {}, {"Content-Type": "application/json"}),
        (
            "POST",
            "/api/v1/chat/completions",
        ): (
            200,
            {"choices": [{"message": {"content": "assistant reply\nsecond line"}}]},
            {"Content-Type": "application/json"},
        ),
    }
    with run_server(responders) as base_url:
        replay.replay_samples(
            base_url=base_url,
            samples_dir=SAMPLES_DIR,
            output_dir=tmp_path,
            timeout=2,
        )

    health_report = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    models_report = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    chat_report = json.loads((tmp_path / "chat.json").read_text(encoding="utf-8"))

    assert health_report["url"].endswith("/api/v1/health")
    assert models_report["data"]["data"][0]["id"] == "demo"
    assert chat_report["data"]["choices"][0]["message"]["content"].startswith("assistant reply")


def test_replay_samples_requires_assistant(tmp_path: Path) -> None:
    responders = {
        ("GET", "/v1/health"): (200, {"status": "ok"}, {"Content-Type": "application/json"}),
        ("GET", "/v1/models"): (200, {"data": []}, {"Content-Type": "application/json"}),
        (
            "POST",
            "/v1/chat/completions",
        ): (200, {"choices": [{"message": {}}]}, {"Content-Type": "application/json"}),
    }
    with run_server(responders) as base_url:
        with pytest.raises(replay.ReplayError, match="assistant message"):
            replay.replay_samples(
                base_url=base_url,
                samples_dir=SAMPLES_DIR,
                output_dir=tmp_path,
                timeout=2,
            )


def test_parse_args_defaults() -> None:
    args = replay.parse_args([])
    assert args.base_url == replay.DEFAULT_BASE_URL
    assert args.timeout == replay.DEFAULT_TIMEOUT


def test_main_missing_sample(tmp_path: Path) -> None:
    rc = replay.main(["--samples-dir", str(tmp_path)])
    assert rc == 1


def test_main_invokes_replay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called: dict[str, object] = {}

    def fake_replay(**kwargs: object) -> None:
        called.update(kwargs)

    monkeypatch.setattr(replay, "replay_samples", fake_replay)
    rc = replay.main(
        [
            "--samples-dir",
            str(SAMPLES_DIR),
            "--output-dir",
            str(tmp_path),
            "--timeout",
            "7",
            "--base-url",
            "http://token.place",
        ]
    )
    assert rc == 0
    assert called["timeout"] == 7
    assert called["base_url"] == "http://token.place"
    assert isinstance(called["output_dir"], Path)


def test_main_replay_error_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: object) -> None:
        raise replay.ReplayError("boom")

    monkeypatch.setattr(replay, "replay_samples", boom)
    rc = replay.main(["--samples-dir", str(SAMPLES_DIR)])
    assert rc == 2


def test_main_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: object) -> None:
        raise error.URLError("down")

    monkeypatch.setattr(replay, "replay_samples", boom)
    rc = replay.main(["--samples-dir", str(SAMPLES_DIR)])
    assert rc == 3
