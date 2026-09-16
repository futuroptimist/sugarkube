#!/usr/bin/env python3
"""Collect Daniel's passive runtime cache contract as bounded Prometheus metrics."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

MAX_PAYLOAD_BYTES = 262_144
MAX_COUNT = 50
MAX_DURATION_MS = 300_000
MAX_AGE_SECONDS = 31_536_000
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
CACHE_FIELDS = {
    "enabled",
    "state",
    "lastSuccessfulRefreshAt",
    "dataCompleteness",
    "refreshDurationMs",
    "failureCategories",
    "configuredRepositoryCount",
    "successfulRepositoryCount",
    "failedRepositoryCount",
    "retainedRepositoryCount",
    "oldestDataFetchedAt",
    "retainedDataAgeSeconds",
}


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


def _timestamp(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string or null")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("timestamp is malformed") from error
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks a timezone")
    return parsed.timestamp()


def _bounded_number(value: object, maximum: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} is not numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or result > maximum:
        raise ValueError(f"{field} is outside its bound")
    return result


def validate_document(document: object) -> dict:
    """Validate only the bounded aggregate contract; repository identities are ignored."""
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise ValueError("runtime document schema is invalid")
    cache = document.get("cache")
    if not isinstance(cache, dict) or set(cache) != CACHE_FIELDS:
        raise ValueError("cache contract shape is invalid")
    if type(cache["enabled"]) is not bool or cache["state"] not in STATES:
        raise ValueError("cache state is invalid")
    if cache["dataCompleteness"] not in COMPLETENESS:
        raise ValueError("cache completeness is invalid")
    categories = cache["failureCategories"]
    if (
        not isinstance(categories, list)
        or len(categories) != len(set(categories))
        or any(category not in FAILURE_CATEGORIES for category in categories)
    ):
        raise ValueError("cache failure categories are invalid")
    counts = {}
    for field in (
        "configuredRepositoryCount",
        "successfulRepositoryCount",
        "failedRepositoryCount",
        "retainedRepositoryCount",
    ):
        value = cache[field]
        if type(value) is not int:
            raise ValueError(f"{field} is not an integer")
        counts[field] = int(_bounded_number(value, MAX_COUNT, field))
    if (
        counts["successfulRepositoryCount"] + counts["failedRepositoryCount"]
        > counts["configuredRepositoryCount"]
    ):
        raise ValueError("repository counts contradict")
    duration = cache["refreshDurationMs"]
    if duration is not None:
        duration = _bounded_number(duration, MAX_DURATION_MS, "refreshDurationMs")
    retained_age = cache["retainedDataAgeSeconds"]
    if retained_age is not None:
        retained_age = _bounded_number(retained_age, MAX_AGE_SECONDS, "retainedDataAgeSeconds")
    last_success = _timestamp(cache["lastSuccessfulRefreshAt"])
    oldest = _timestamp(cache["oldestDataFetchedAt"])
    if cache["state"] == "disabled" and cache["enabled"]:
        raise ValueError("disabled state contradicts enabled flag")
    if cache["state"] != "disabled" and not cache["enabled"]:
        raise ValueError("enabled state contradicts enabled flag")
    if cache["state"] == "fresh" and cache["dataCompleteness"] != "complete":
        raise ValueError("fresh cache is not complete")
    if cache["state"] in {"warming", "unavailable"} and cache["dataCompleteness"] != "none":
        raise ValueError("empty cache state has data")
    return {
        **cache,
        **counts,
        "refreshDurationMs": duration,
        "retainedDataAgeSeconds": retained_age,
        "lastSuccessfulRefreshTimestamp": last_success,
        "oldestDataFetchedTimestamp": oldest,
    }


def unavailable_cache() -> dict:
    return {
        "enabled": True,
        "state": "unavailable",
        "dataCompleteness": "none",
        "failureCategories": [],
        "configuredRepositoryCount": 0,
        "successfulRepositoryCount": 0,
        "failedRepositoryCount": 0,
        "retainedRepositoryCount": 0,
        "refreshDurationMs": None,
        "retainedDataAgeSeconds": None,
        "lastSuccessfulRefreshTimestamp": None,
        "oldestDataFetchedTimestamp": None,
    }


def fetch_document(url: str, timeout: float = 10) -> dict:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "sugarkube-daniel-cache/1"},
    )
    opener = urllib.request.build_opener(RejectRedirects)
    with opener.open(request, timeout=timeout) as response:  # noqa: S310 - configured HTTPS URL
        if response.status != 200:
            raise OSError("runtime endpoint did not return 200")
        payload = response.read(MAX_PAYLOAD_BYTES + 1)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("runtime document exceeds the size bound")
    try:
        return validate_document(json.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("runtime document is malformed") from error


def render_metrics(cache: dict, environment: str, now: float, collection_success: bool) -> str:
    if environment not in {"staging", "prod"}:
        raise ValueError("environment must be staging or prod")
    base = f'environment="{environment}"'
    lines = [
        "# HELP daniel_cache_collection_success Whether the passive runtime document "
        "was collected and validated.",
        "# TYPE daniel_cache_collection_success gauge",
        f"daniel_cache_collection_success{{{base}}} {int(collection_success)}",
        "# HELP daniel_cache_state Current bounded cache lifecycle state.",
        "# TYPE daniel_cache_state gauge",
    ]
    lines.extend(
        f'daniel_cache_state{{{base},state="{state}"}} {int(cache["state"] == state)}'
        for state in STATES
    )
    lines.extend(
        [
            "# HELP daniel_cache_completeness Current bounded cache data completeness.",
            "# TYPE daniel_cache_completeness gauge",
        ]
    )
    lines.extend(
        f'daniel_cache_completeness{{{base},completeness="{value}"}} '
        f'{int(cache["dataCompleteness"] == value)}'
        for value in COMPLETENESS
    )
    lines.extend(
        [
            "# HELP daniel_cache_failure_category Whether the latest refresh had a "
            "fixed failure category.",
            "# TYPE daniel_cache_failure_category gauge",
        ]
    )
    lines.extend(
        f'daniel_cache_failure_category{{{base},failure_category="{category}"}} '
        f'{int(category in cache["failureCategories"])}'
        for category in FAILURE_CATEGORIES
    )
    for field, metric in (
        ("configuredRepositoryCount", "configured"),
        ("successfulRepositoryCount", "successful"),
        ("failedRepositoryCount", "failed"),
        ("retainedRepositoryCount", "retained"),
    ):
        lines.append(f'daniel_cache_repositories{{{base},result="{metric}"}} {cache[field]}')
    optional = (
        ("refreshDurationMs", "daniel_cache_refresh_duration_seconds", 0.001),
        ("retainedDataAgeSeconds", "daniel_cache_retained_data_age_seconds", 1),
    )
    for field, metric, multiplier in optional:
        if cache[field] is not None:
            lines.append(f"{metric}{{{base}}} {cache[field] * multiplier:g}")
    last_success = cache["lastSuccessfulRefreshTimestamp"]
    if last_success is not None:
        lines.append(f"daniel_cache_freshness_age_seconds{{{base}}} {max(0, now-last_success):g}")
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def collect(url: str, environment: str, output: Path, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    success = True
    try:
        cache = fetch_document(url)
    except (OSError, ValueError, urllib.error.URLError):
        cache, success = unavailable_cache(), False
    atomic_write(output, render_metrics(cache, environment, current, success))
    return success


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/var/lib/node_exporter/textfile_collector/daniel-cache.prom"),
    )
    args = parser.parse_args()
    expected = {
        "staging": "https://staging.danielsmith.io/runtime/github-metrics.json",
        "prod": "https://danielsmith.io/runtime/github-metrics.json",
    }
    if args.url != expected[args.environment]:
        parser.error("URL must be the canonical passive runtime endpoint for the environment")
    collect(args.url, args.environment, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
