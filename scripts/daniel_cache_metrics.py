#!/usr/bin/env python3
"""Convert Daniel's passive runtime cache document to bounded Prometheus metrics."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 262_144
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
DOCUMENT_STATUSES = ("valid", "malformed", "oversized", "unavailable")
MAX_COUNT = 50
MAX_DURATION_MS = 3_600_000
MAX_AGE_SECONDS = 31_536_000


class InvalidDocument(ValueError):
    pass


def _bounded_number(
    value, maximum: int, field: str, *, nullable: bool = False, integer: bool = False
) -> float:
    if nullable and value is None:
        return math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidDocument(field)
    number = float(value)
    if (
        not math.isfinite(number)
        or number < 0
        or number > maximum
        or (integer and not number.is_integer())
    ):
        raise InvalidDocument(field)
    return number


def parse_document(payload: bytes, now: datetime | None = None) -> dict[str, object]:
    if len(payload) > MAX_BYTES:
        raise OverflowError("runtime document exceeds 262144 bytes")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidDocument("JSON") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise InvalidDocument("schemaVersion")
    cache = document.get("cache")
    if not isinstance(cache, dict):
        raise InvalidDocument("cache")
    state, completeness = cache.get("state"), cache.get("dataCompleteness")
    if state not in STATES or completeness not in COMPLETENESS:
        raise InvalidDocument("cache enum")
    enabled = cache.get("enabled")
    if not isinstance(enabled, bool) or enabled != (state != "disabled"):
        raise InvalidDocument("cache.enabled")
    failures = cache.get("failureCategories")
    if not isinstance(failures, list) or len(failures) != len(set(failures)):
        raise InvalidDocument("cache.failureCategories")
    if any(item not in FAILURES for item in failures):
        raise InvalidDocument("cache.failureCategories")
    values: dict[str, object] = {
        "state": state,
        "completeness": completeness,
        "failures": set(failures),
        "duration": _bounded_number(
            cache.get("refreshDurationMs"), MAX_DURATION_MS, "duration", nullable=True
        )
        / 1000,
        "retained_age": _bounded_number(
            cache.get("retainedDataAgeSeconds"), MAX_AGE_SECONDS, "retained age", nullable=True
        ),
    }
    for name in ("configured", "successful", "failed", "retained"):
        values[name] = _bounded_number(
            cache.get(f"{name}RepositoryCount"), MAX_COUNT, name, integer=True
        )
    stamp = cache.get("lastSuccessfulRefreshAt")
    values["freshness_age"] = math.nan
    if stamp is not None:
        if not isinstance(stamp, str) or not stamp.endswith("Z"):
            raise InvalidDocument("lastSuccessfulRefreshAt")
        try:
            parsed = datetime.fromisoformat(stamp[:-1] + "+00:00")
        except ValueError as exc:
            raise InvalidDocument("lastSuccessfulRefreshAt") from exc
        age = ((now or datetime.now(timezone.utc)) - parsed).total_seconds()
        if age < 0:
            raise InvalidDocument("lastSuccessfulRefreshAt")
        values["freshness_age"] = age
    return values


def render(payload: bytes | None, environment: str, status: str = "valid", now=None) -> str:
    values = None
    if payload is not None:
        values = parse_document(payload, now)
    state = values["state"] if values else "unavailable"
    completeness = values["completeness"] if values else "none"
    lines = [
        "# HELP daniel_cache_collection_up Whether the passive runtime document "
        "was collected and validated.",
        "# TYPE daniel_cache_collection_up gauge",
        f'daniel_cache_collection_up{{environment="{environment}"}} {1 if values else 0}',
    ]
    for metric, domain, selected in (
        ("daniel_cache_state", STATES, state),
        ("daniel_cache_data_completeness", COMPLETENESS, completeness),
        ("daniel_cache_document_status", DOCUMENT_STATUSES, status),
    ):
        label = (
            "state"
            if metric.endswith("state")
            else "completeness" if "completeness" in metric else "status"
        )
        lines += [
            f'{metric}{{environment="{environment}",{label}="{item}"}} {int(item == selected)}'
            for item in domain
        ]
    failures = values["failures"] if values else set()
    lines += [
        f'daniel_cache_failure_category{{environment="{environment}",'
        f'category="{item}"}} {int(item in failures)}'
        for item in FAILURES
    ]
    if values:
        for suffix, key in (
            ("freshness_age_seconds", "freshness_age"),
            ("refresh_duration_seconds", "duration"),
            ("retained_data_age_seconds", "retained_age"),
        ):
            if not math.isnan(values[key]):
                lines.append(
                    f'daniel_cache_{suffix}{{environment="{environment}"}} {values[key]:g}'
                )
        for key in ("configured", "successful", "failed", "retained"):
            lines.append(
                f'daniel_cache_repositories{{environment="{environment}",'
                f'result="{key}"}} {values[key]:g}'
            )
    return "\n".join(lines) + "\n"


def collect(url: str, environment: str, *, opener=urllib.request.urlopen) -> str:
    status = "valid"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "sugarkube-daniel-cache-collector/1",
            },
        )
        with opener(request, timeout=10) as response:
            payload = response.read(MAX_BYTES + 1)
        return render(payload, environment)
    except OverflowError:
        status = "oversized"
    except InvalidDocument:
        status = "malformed"
    except (OSError, TimeoutError):
        status = "unavailable"
    return render(None, environment, status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = collect(args.url, args.environment)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=args.output.parent, prefix=".daniel-cache-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(output)
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
