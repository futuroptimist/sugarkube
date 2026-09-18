#!/usr/bin/env python3
"""Convert Daniel's passive runtime cache document to bounded Prometheus metrics."""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import tempfile
import urllib.error
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
SOURCE_VALUES = {
    "disabled": "static-neutral-placeholder",
    "warming": "github-api-warming",
    "fresh": "github-api",
    "stale": "github-api",
    "unavailable": "github-api-unavailable",
}
SOURCE_REVISION = "c4d45d96f593d0075096c55ea0a71215350b5ed3"
RUNTIME_URLS = {
    "staging": "https://staging.danielsmith.io/runtime/github-metrics.json",
    "prod": "https://danielsmith.io/runtime/github-metrics.json",
}


class InvalidDocument(ValueError):
    pass


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect rejected", headers, fp)


def _bounded_number(value, maximum, field, *, nullable=False, integer=False):
    if nullable and value is None:
        return math.nan
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidDocument(field)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise InvalidDocument(field) from exc
    if not math.isfinite(number) or number < 0 or number > maximum:
        raise InvalidDocument(field)
    if integer and not number.is_integer():
        raise InvalidDocument(field)
    return number


def _timestamp(value, field, *, nullable=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 40:
        raise InvalidDocument(field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidDocument(field) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise InvalidDocument(field)
    return parsed


def parse_document(payload: bytes, now: datetime | None = None) -> dict[str, object]:
    if len(payload) > MAX_BYTES:
        raise OverflowError("runtime document exceeds 262144 bytes")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise InvalidDocument("JSON") from exc
    if not isinstance(document, dict):
        raise InvalidDocument("document")
    required = {"schemaVersion", "generatedAt", "expiresAt", "source", "repos", "errors", "cache"}
    if set(document) != required:
        raise InvalidDocument("required fields")
    version = document["schemaVersion"]
    if isinstance(version, bool) or version != 1:
        raise InvalidDocument("schemaVersion")
    generated = _timestamp(document["generatedAt"], "generatedAt", nullable=True)
    expires = _timestamp(document["expiresAt"], "expiresAt", nullable=True)
    repos, errors = document["repos"], document["errors"]
    if (
        not isinstance(repos, dict)
        or len(repos) > MAX_COUNT
        or not isinstance(errors, dict)
        or errors
    ):
        raise InvalidDocument("repos/errors")

    cache = document["cache"]
    required_cache = {
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
    if not isinstance(cache, dict) or set(cache) != required_cache:
        raise InvalidDocument("cache required fields")
    state, completeness = cache["state"], cache["dataCompleteness"]
    if state not in STATES or completeness not in COMPLETENESS:
        raise InvalidDocument("cache enum")
    if document["source"] != SOURCE_VALUES[state]:
        raise InvalidDocument("source")
    enabled = cache["enabled"]
    if not isinstance(enabled, bool) or enabled != (state != "disabled"):
        raise InvalidDocument("cache.enabled")
    failures = cache["failureCategories"]
    if (
        not isinstance(failures, list)
        or any(not isinstance(item, str) for item in failures)
        or len(failures) != len(set(failures))
        or any(item not in FAILURES for item in failures)
    ):
        raise InvalidDocument("cache.failureCategories")

    values: dict[str, object] = {
        "state": state,
        "completeness": completeness,
        "failures": set(failures),
        "duration": _bounded_number(
            cache["refreshDurationMs"], MAX_DURATION_MS, "duration", nullable=True
        )
        / 1000,
        "retained_age": _bounded_number(
            cache["retainedDataAgeSeconds"], MAX_AGE_SECONDS, "retained age", nullable=True
        ),
    }
    for name in ("configured", "successful", "failed", "retained"):
        values[name] = _bounded_number(
            cache[f"{name}RepositoryCount"], MAX_COUNT, name, integer=True
        )
    last_success = _timestamp(
        cache["lastSuccessfulRefreshAt"], "lastSuccessfulRefreshAt", nullable=True
    )
    oldest = _timestamp(cache["oldestDataFetchedAt"], "oldestDataFetchedAt", nullable=True)
    values["freshness_age"] = math.nan
    if last_success is not None:
        age = ((now or datetime.now(timezone.utc)) - last_success).total_seconds()
        values["freshness_age"] = _bounded_number(age, MAX_AGE_SECONDS, "lastSuccessfulRefreshAt")

    configured, successful = values["configured"], values["successful"]
    failed, retained = values["failed"], values["retained"]
    disabled = state == "disabled"
    warming = state == "warming"
    has_data = bool(repos)
    contradictory = (
        (generated is None) != (expires is None)
        or (generated is not None and expires <= generated)
        or retained > failed
        or len(repos) != successful + retained
        or (
            disabled
            and (
                completeness != "none"
                or any((configured, successful, failed, retained))
                or has_data
                or failures
                or last_success
                or oldest
                or not math.isnan(values["duration"])
                or not math.isnan(values["retained_age"])
            )
        )
        or (
            warming
            and (
                completeness != "none"
                or successful
                or failed
                or retained
                or has_data
                or failures
                or last_success
                or oldest
                or generated
                or expires
                or not math.isnan(values["duration"])
                or not math.isnan(values["retained_age"])
            )
        )
        or (not disabled and not warming and successful + failed != configured)
        or (
            state == "fresh"
            and (
                completeness != "complete"
                or failed
                or retained
                or successful != configured
                or not has_data
                or failures
                or last_success is None
                or oldest is None
            )
        )
        or (
            state == "stale"
            and (
                completeness != "partial"
                or not failed
                or not has_data
                or not failures
                or oldest is None
            )
        )
        or (
            state == "unavailable"
            and (
                completeness != "none"
                or successful
                or retained
                or has_data
                or not failed
                or not failures
                or oldest is not None
            )
        )
        or ((state in {"fresh", "stale"}) != (not math.isnan(values["retained_age"])))
        or (state not in {"disabled", "warming"}) != (not math.isnan(values["duration"]))
    )
    if contradictory:
        raise InvalidDocument("cache state/count relationship")
    return values


def render(
    payload: bytes | None,
    environment: str,
    status="valid",
    now=None,
    *,
    monitoring_enabled: bool = True,
) -> str:
    values = parse_document(payload, now) if payload is not None else None
    state = values["state"] if values else ("unavailable" if monitoring_enabled else "disabled")
    completeness = values["completeness"] if values else "none"
    lines = [
        "# HELP daniel_cache_collection_up Whether the passive runtime document "
        "was collected and validated.",
        "# TYPE daniel_cache_collection_up gauge",
        f'daniel_cache_collection_up{{environment="{environment}"}} {1 if values else 0}',
        "# HELP daniel_cache_monitoring_enabled Whether passive collection is authorized.",
        "# TYPE daniel_cache_monitoring_enabled gauge",
        f'daniel_cache_monitoring_enabled{{environment="{environment}"}} '
        f"{int(monitoring_enabled)}",
    ]
    for metric, domain, selected, label in (
        ("daniel_cache_state", STATES, state, "state"),
        ("daniel_cache_data_completeness", COMPLETENESS, completeness, "completeness"),
        ("daniel_cache_document_status", DOCUMENT_STATUSES, status, "status"),
    ):
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


def collect(url: str, environment: str, *, opener=None, now=None) -> str:
    if url != RUNTIME_URLS[environment]:
        raise ValueError("URL must be the canonical runtime URL for the selected environment")
    open_url = opener or urllib.request.build_opener(_RejectRedirects()).open
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "sugarkube-daniel-cache-collector/1",
            },
        )
        with open_url(request, timeout=10) as response:
            if getattr(response, "geturl", lambda: url)() != url:
                raise urllib.error.URLError("redirected response rejected")
            payload = response.read(MAX_BYTES + 1)
        return render(payload, environment, now=now)
    except OverflowError:
        status = "oversized"
    except InvalidDocument:
        status = "malformed"
    except (OSError, TimeoutError, http.client.HTTPException, urllib.error.URLError):
        status = "unavailable"
    return render(None, environment, status)


def load_producer(descriptor: Path, environment: str) -> dict[str, object]:
    """Load one pinned producer without accepting open-ended collection coordinates."""
    document = json.loads(descriptor.read_text(encoding="utf-8"))
    if set(document) != {"schemaVersion", "sourceRevision", "producers"}:
        raise ValueError("invalid descriptor fields")
    if document["schemaVersion"] != 1 or document["sourceRevision"] != SOURCE_REVISION:
        raise ValueError("invalid descriptor version")
    matches = [item for item in document["producers"] if item.get("environment") == environment]
    if len(matches) != 1:
        raise ValueError("descriptor environment identity is missing or duplicated")
    producer = matches[0]
    expected_name = f"danielsmith-github-cache-{environment}"
    if set(producer) != {
        "name",
        "application",
        "environment",
        "enabled",
        "cadence",
        "timeout",
        "url",
        "transport",
    } or producer != {
        "name": expected_name,
        "application": "danielsmith",
        "environment": environment,
        "enabled": False,
        "cadence": "5m",
        "timeout": "10s",
        "url": RUNTIME_URLS[environment],
        "transport": "passive-snapshot",
    }:
        raise ValueError("descriptor producer is not the pinned disabled contract")
    return producer


def collect_producer(producer: dict[str, object], *, opener=None, now=None) -> str:
    """Collect the passive snapshot only when the reviewed producer is enabled."""
    environment = str(producer["environment"])
    if not producer["enabled"]:
        return render(None, environment, "unavailable", monitoring_enabled=False)
    return collect(str(producer["url"]), environment, opener=opener, now=now)


def write_textfile(output_path: Path, output: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output_path.parent, prefix=".daniel-cache-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument("--environment", choices=tuple(RUNTIME_URLS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.url) == bool(args.descriptor):
        parser.error("pass exactly one of --url or --descriptor")
    output = (
        collect(args.url, args.environment)
        if args.url
        else collect_producer(load_producer(args.descriptor, args.environment))
    )
    write_textfile(args.output, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
