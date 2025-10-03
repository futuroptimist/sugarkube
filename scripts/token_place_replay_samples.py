#!/usr/bin/env python3

"""Replay bundled token.place sample requests for first-boot validation."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Optional
from urllib import error, request

DEFAULT_BASE_URL = "http://127.0.0.1:5000"
TOKEN_PLACE_URL_ENV = "TOKEN_PLACE_URL"
DEFAULT_SAMPLE = "openai-chat-demo.json"
DEFAULT_REPORT_DIR = Path.home() / "sugarkube" / "reports" / "token-place-samples"
DEFAULT_TIMEOUT = 10


class ReplayError(RuntimeError):
    """Raised when a probe fails."""


def _load_sample(sample_path: Path) -> dict:
    try:
        with sample_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:  # pragma: no cover - handled by caller
        raise ReplayError(f"Sample payload not found: {sample_path}") from exc
    except json.JSONDecodeError as exc:
        raise ReplayError(f"Sample payload is invalid JSON: {sample_path}") from exc


def _candidate_urls(base_url: str, paths: Iterable[str]) -> Iterable[str]:
    for path in paths:
        yield base_url.rstrip("/") + path


def _http_request(
    url: str,
    *,
    method: str = "GET",
    timeout: int,
    payload: Optional[dict] = None,
) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset("utf-8")
        body = response.read().decode(charset)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ReplayError(f"Non-JSON response from {url}: {body[:120]}") from exc


def _probe_first(base_url: str, candidates: Iterable[str], **kwargs) -> tuple[str, dict]:
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            payload = _http_request(candidate, **kwargs)
            return candidate, payload
        except (ReplayError, error.URLError, error.HTTPError) as exc:
            last_error = exc
    if last_error is None:
        raise ReplayError("No candidates provided for probe")
    raise ReplayError(str(last_error))


def replay_samples(*, base_url: str, samples_dir: Path, output_dir: Path, timeout: int) -> None:
    sample_payload = _load_sample(samples_dir / DEFAULT_SAMPLE)

    health_url, health = _probe_first(
        base_url,
        _candidate_urls(base_url, ("/v1/health", "/api/v1/health", "/health")),
        timeout=timeout,
    )
    models_url, models = _probe_first(
        base_url,
        _candidate_urls(base_url, ("/v1/models", "/api/v1/models")),
        timeout=timeout,
    )
    chat_url, chat = _probe_first(
        base_url,
        _candidate_urls(base_url, ("/v1/chat/completions", "/api/v1/chat/completions")),
        timeout=timeout,
        payload=sample_payload,
        method="POST",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, url_used, payload in (
        ("health", health_url, health),
        ("models", models_url, models),
        ("chat", chat_url, chat),
    ):
        target = output_dir / f"{name}.json"
        with target.open("w", encoding="utf-8") as handle:
            json.dump({"url": url_used, "data": payload}, handle, indent=2)
            handle.write("\n")

    chat_choices = chat.get("choices", [])
    assistant_msg = None
    if chat_choices:
        assistant_msg = chat_choices[0].get("message", {}).get("content")
    if not assistant_msg:
        raise ReplayError(
            "Chat completion response did not include an assistant message; "
            "check container logs for token.place"
        )

    print("token.place sample replay complete:")
    print(f"  Health URL: {health_url}")
    print(f"  Models URL: {models_url} (returned {len(models.get('data', []))} models)")
    preview = assistant_msg.strip().splitlines()[0]
    print(f"  Chat URL: {chat_url} -> {preview}")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get(TOKEN_PLACE_URL_ENV, DEFAULT_BASE_URL),
        help=(
            "token.place base URL (default: {default}; set {env} to override)".format(
                default=DEFAULT_BASE_URL,
                env=TOKEN_PLACE_URL_ENV,
            )
        ),
    )
    parser.add_argument(
        "--samples-dir",
        default=str(Path("/opt/sugarkube/samples/token-place")),
        help="Directory containing sample payloads",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Where to write replay results",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check for sample payloads without issuing HTTP requests",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    samples_dir = Path(args.samples_dir)
    sample_path = samples_dir / DEFAULT_SAMPLE
    if not sample_path.exists():
        print(f"Sample payload missing: {sample_path}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"Dry run OK — found {sample_path}")
        return 0

    try:
        replay_samples(
            base_url=args.base_url,
            samples_dir=samples_dir,
            output_dir=Path(args.output_dir),
            timeout=args.timeout,
        )
    except ReplayError as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 2
    except (error.URLError, error.HTTPError) as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
