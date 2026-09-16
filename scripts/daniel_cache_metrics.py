#!/usr/bin/env python3
"""Convert Daniel's passive runtime cache document to bounded Prometheus metrics."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

MAX_PAYLOAD_BYTES = 262_144
MAX_DURATION_SECONDS = 3_600
MAX_AGE_SECONDS = 31_536_000
MAX_REPOSITORIES = 50
STATES = ("disabled", "warming", "fresh", "stale", "unavailable")
COMPLETENESS = ("complete", "partial", "none")
FAILURE_CATEGORIES = (
    "configuration",
    "internal",
    "invalid_response",
    "network",
    "not_found",
    "rate_limited",
    "timeout",
    "upstream",
)


class InvalidDocument(ValueError):
    """The bounded public runtime contract was not satisfied."""


def _number(value: Any, name: str, maximum: float, *, nullable: bool = False) -> float | None:
    if nullable and value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value < 0
        or value > maximum
    ):
        raise InvalidDocument(f"invalid {name}")
    return float(value)


def _timestamp(value: Any, name: str) -> dt.datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise InvalidDocument(f"invalid {name}")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise InvalidDocument(f"invalid {name}") from error
    if parsed.tzinfo is None:
        raise InvalidDocument(f"invalid {name}")
    return parsed


def parse_document(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise InvalidDocument("document is oversized")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidDocument("document is malformed") from error
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise InvalidDocument("unsupported document schema")
    cache = document.get("cache")
    if not isinstance(cache, dict):
        raise InvalidDocument("cache object is missing")
    state, completeness = cache.get("state"), cache.get("dataCompleteness")
    if (
        state not in STATES
        or completeness not in COMPLETENESS
        or not isinstance(cache.get("enabled"), bool)
    ):
        raise InvalidDocument("cache enums are invalid")
    categories = cache.get("failureCategories")
    if (
        not isinstance(categories, list)
        or len(categories) != len(set(categories))
        or any(category not in FAILURE_CATEGORIES for category in categories)
    ):
        raise InvalidDocument("failure categories are invalid")
    counts = {}
    for field in (
        "configuredRepositoryCount",
        "successfulRepositoryCount",
        "failedRepositoryCount",
        "retainedRepositoryCount",
    ):
        counts[field] = int(_number(cache.get(field), field, MAX_REPOSITORIES))
    if (
        counts["successfulRepositoryCount"] + counts["failedRepositoryCount"]
        > counts["configuredRepositoryCount"]
    ):
        raise InvalidDocument("repository counts are inconsistent")
    refresh = _number(
        cache.get("refreshDurationMs"),
        "refreshDurationMs",
        MAX_DURATION_SECONDS * 1000,
        nullable=True,
    )
    retained_age = _number(
        cache.get("retainedDataAgeSeconds"),
        "retainedDataAgeSeconds",
        MAX_AGE_SECONDS,
        nullable=True,
    )
    last_success = _timestamp(cache.get("lastSuccessfulRefreshAt"), "lastSuccessfulRefreshAt")
    _timestamp(cache.get("oldestDataFetchedAt"), "oldestDataFetchedAt")
    return {
        "state": state,
        "completeness": completeness,
        "categories": categories,
        "counts": counts,
        "refresh_seconds": None if refresh is None else refresh / 1000,
        "retained_age": retained_age,
        "last_success": last_success,
    }


def _sample(
    name: str, value: float | int, environment: str, extra: tuple[str, str] | None = None
) -> str:
    labels = f'environment="{environment}"'
    if extra:
        labels += f',{extra[0]}="{extra[1]}"'
    return f"{name}{{{labels}}} {value:g}"


def render_metrics(parsed: dict[str, Any] | None, environment: str, now: dt.datetime) -> str:
    healthy = parsed is not None
    state = parsed["state"] if healthy else "unavailable"
    completeness = parsed["completeness"] if healthy else "none"
    lines = [_sample("daniel_cache_collection_up", int(healthy), environment)]
    lines.extend(
        _sample(
            "daniel_cache_state_info", int(candidate == state), environment, ("state", candidate)
        )
        for candidate in STATES
    )
    lines.extend(
        _sample(
            "daniel_cache_data_completeness_info",
            int(candidate == completeness),
            environment,
            ("completeness", candidate),
        )
        for candidate in COMPLETENESS
    )
    categories = set(parsed["categories"] if healthy else ())
    lines.extend(
        _sample(
            "daniel_cache_failure_category_info",
            int(candidate in categories),
            environment,
            ("failure_category", candidate),
        )
        for candidate in FAILURE_CATEGORIES
    )
    if healthy:
        fields = {
            "configuredRepositoryCount": "daniel_cache_configured_repositories",
            "successfulRepositoryCount": "daniel_cache_successful_repositories",
            "failedRepositoryCount": "daniel_cache_failed_repositories",
            "retainedRepositoryCount": "daniel_cache_retained_repositories",
        }
        lines.extend(
            _sample(metric, parsed["counts"][field], environment)
            for field, metric in fields.items()
        )
        if parsed["refresh_seconds"] is not None:
            lines.append(
                _sample(
                    "daniel_cache_refresh_duration_seconds", parsed["refresh_seconds"], environment
                )
            )
        if parsed["retained_age"] is not None:
            lines.append(
                _sample(
                    "daniel_cache_retained_data_age_seconds", parsed["retained_age"], environment
                )
            )
        if parsed["last_success"] is not None:
            age = max(0, min(MAX_AGE_SECONDS, (now - parsed["last_success"]).total_seconds()))
            lines.append(
                _sample("daniel_cache_last_successful_refresh_age_seconds", age, environment)
            )
    return "\n".join(lines) + "\n"


def collect(
    url: str,
    environment: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    now: dt.datetime | None = None,
) -> tuple[str, bool]:
    parsed_url = urllib.parse.urlsplit(url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.path != "/runtime/github-metrics.json"
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError("URL must be an HTTPS Daniel runtime document")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "sugarkube-daniel-cache-collector/1"}
        )
        with opener(request, timeout=10) as response:
            payload = response.read(MAX_PAYLOAD_BYTES + 1)
        parsed = parse_document(payload)
        ok = True
    except (OSError, urllib.error.URLError, InvalidDocument):
        parsed, ok = None, False
    current = now or dt.datetime.now(dt.timezone.utc)
    return render_metrics(parsed, environment, current), ok


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metrics, ok = collect(args.url, args.environment)
    atomic_write(args.output, metrics)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
