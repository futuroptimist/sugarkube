#!/usr/bin/env python3
"""Expose Daniel's published cache contract as bounded Prometheus metrics."""

from __future__ import annotations

import argparse
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_PAYLOAD_BYTES = 262_144
STATES = ("disabled", "warming", "fresh", "stale", "unavailable")
COMPLETENESS = ("complete", "partial", "none")
FAILURES = (
    "configuration",
    "internal",
    "invalid_response",
    "network",
    "not_found",
    "rate_limited",
    "timeout",
    "upstream",
)
COUNTS = (
    "configuredRepositoryCount",
    "successfulRepositoryCount",
    "failedRepositoryCount",
    "retainedRepositoryCount",
)


class ContractError(ValueError):
    """The passive runtime document does not satisfy the bounded contract."""


def _number(value: object, maximum: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("invalid numeric field")
    result = float(value)
    if not math.isfinite(result) or result < 0 or result > maximum:
        raise ContractError("numeric field outside contract")
    return result


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError("invalid timestamp") from exc
    return parsed if parsed.tzinfo is not None else None


def validate(payload: bytes) -> dict:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ContractError("payload exceeds published limit")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("malformed document") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise ContractError("unsupported document")
    cache = document.get("cache")
    if not isinstance(cache, dict):
        raise ContractError("cache object missing")
    if cache.get("state") not in STATES or cache.get("dataCompleteness") not in COMPLETENESS:
        raise ContractError("unbounded cache enum")
    categories = cache.get("failureCategories")
    if not isinstance(categories, list) or len(categories) != len(set(categories)):
        raise ContractError("invalid failure categories")
    if any(category not in FAILURES for category in categories):
        raise ContractError("unbounded failure category")
    for field in COUNTS:
        _number(cache.get(field), 50)
    if cache.get("refreshDurationMs") is not None:
        _number(cache["refreshDurationMs"], 3_600_000)
    if cache.get("retainedDataAgeSeconds") is not None:
        _number(cache["retainedDataAgeSeconds"], 31_536_000)
    _timestamp(cache.get("lastSuccessfulRefreshAt"))
    return cache


def render(payload: bytes | None, environment: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    try:
        cache = validate(payload if payload is not None else b"")
        document_up = 1
    except ContractError:
        cache = {
            "state": "unavailable",
            "dataCompleteness": "none",
            "failureCategories": [],
            **{field: 0 for field in COUNTS},
            "refreshDurationMs": None,
            "retainedDataAgeSeconds": None,
            "lastSuccessfulRefreshAt": None,
        }
        document_up = 0

    labels = f'environment="{environment}"'
    lines = [
        "# HELP daniel_cache_document_up Whether the runtime document was available and valid.",
        "# TYPE daniel_cache_document_up gauge",
        f"daniel_cache_document_up{{{labels}}} {document_up}",
    ]
    for state in STATES:
        lines.append(
            f'daniel_cache_state{{{labels},state="{state}"}} {int(cache["state"] == state)}'
        )
    for value in COMPLETENESS:
        lines.append(
            f'daniel_cache_completeness{{{labels},completeness="{value}"}} '
            f'{int(cache["dataCompleteness"] == value)}'
        )
    last_success = _timestamp(cache["lastSuccessfulRefreshAt"])
    if last_success is not None:
        age = max(0.0, min((now - last_success).total_seconds(), 31_536_000))
        lines.append(f"daniel_cache_freshness_age_seconds{{{labels}}} {age:g}")
    if cache["refreshDurationMs"] is not None:
        lines.append(
            f"daniel_cache_refresh_duration_seconds{{{labels}}} "
            f'{float(cache["refreshDurationMs"]) / 1000:g}'
        )
    if cache["retainedDataAgeSeconds"] is not None:
        lines.append(
            f"daniel_cache_retained_data_age_seconds{{{labels}}} "
            f'{float(cache["retainedDataAgeSeconds"]):g}'
        )
    for field in COUNTS:
        metric = field.removesuffix("RepositoryCount")
        snake = "".join("_" + c.lower() if c.isupper() else c for c in metric)
        lines.append(f"daniel_cache_repositories_{snake}{{{labels}}} {float(cache[field]):g}")
    failures = set(cache["failureCategories"])
    for category in FAILURES:
        lines.append(
            f'daniel_cache_failure_category{{{labels},failure_category="{category}"}} '
            f"{int(category in failures)}"
        )
    return "\n".join(lines) + "\n"


def collect(url: str, environment: str) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "sugarkube-cache-exporter/1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > MAX_PAYLOAD_BYTES:
                return render(None, environment)
            payload = response.read(MAX_PAYLOAD_BYTES + 1)
    except (OSError, ValueError):
        payload = None
    return render(payload, environment)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("DANIEL_CACHE_URL"))
    parser.add_argument("--environment", default=os.environ.get("ENVIRONMENT"))
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9187)
    args = parser.parse_args()
    if not args.url or args.environment not in {"staging", "prod"}:
        parser.error("a URL and bounded staging/prod environment are required")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = collect(args.url, args.environment).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    ThreadingHTTPServer((args.listen, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
