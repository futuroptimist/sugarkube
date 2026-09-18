#!/usr/bin/env python3
"""Transport and revalidate Daniel's already-published GitHub-cache telemetry."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 262_144
MAX_METRICS_BYTES = 8_192
MAX_COUNT = 50
MAX_DURATION_MS = 3_600_000
MAX_AGE_SECONDS = 31_536_000
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
RUNTIME_URLS = {
    "staging": "https://staging.danielsmith.io/runtime/github-metrics.json",
    "prod": "https://danielsmith.io/runtime/github-metrics.json",
}
SOURCE_BY_STATE = {
    "disabled": "static-neutral-placeholder",
    "warming": "github-api-warming",
    "fresh": "github-api",
    "stale": "github-api",
    "unavailable": "github-api-unavailable",
}
DESCRIPTOR_REVISION = "c4d45d96f593d0075096c55ea0a71215350b5ed3"
DESCRIPTOR_FIELDS = {
    "name",
    "application",
    "environment",
    "enabled",
    "cadence",
    "timeout",
    "concurrency",
    "requestMultiplicity",
    "url",
    "bucket",
    "limits",
    "safetyMargin",
}


class InvalidDocument(ValueError):
    """The passive document does not satisfy the pinned application contract."""


def validate_descriptor(descriptor: object) -> list[dict[str, object]]:
    """Validate the complete installed descriptor without repository imports."""
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "schemaVersion",
        "sourceRevision",
        "producers",
    }:
        raise InvalidDocument("descriptor fields")
    if type(descriptor["schemaVersion"]) is not int or descriptor["schemaVersion"] != 1:
        raise InvalidDocument("descriptor schemaVersion")
    if descriptor["sourceRevision"] != DESCRIPTOR_REVISION:
        raise InvalidDocument("descriptor sourceRevision")
    producers = descriptor["producers"]
    if not isinstance(producers, list) or len(producers) != 2:
        raise InvalidDocument("descriptor producers")
    validated = []
    for producer in producers:
        if not isinstance(producer, dict) or set(producer) != DESCRIPTOR_FIELDS:
            raise InvalidDocument("descriptor producer fields")
        environment = producer["environment"]
        if type(environment) is not str or environment not in RUNTIME_URLS:
            raise InvalidDocument("descriptor producer environment")
        expected = {
            "name": f"danielsmith-github-cache-{environment}",
            "application": "danielsmith",
            "url": RUNTIME_URLS[environment],
            "cadence": "15m",
            "timeout": "10s",
            "concurrency": 1,
            "requestMultiplicity": 1,
            "bucket": "github-cache-transport",
            "limits": {"hourly": 60, "daily": 1000},
            "safetyMargin": 0.2,
        }
        if any(producer[key] != value for key, value in expected.items()):
            raise InvalidDocument("descriptor producer metadata")
        if (
            type(producer["concurrency"]) is not int
            or type(producer["requestMultiplicity"]) is not int
            or type(producer["safetyMargin"]) is not float
            or not isinstance(producer["limits"], dict)
            or any(type(value) is not int for value in producer["limits"].values())
        ):
            raise InvalidDocument("descriptor producer metadata types")
        if type(producer["enabled"]) is not bool:
            raise InvalidDocument("descriptor producer enabled")
        validated.append(producer)
    if {producer["environment"] for producer in validated} != set(RUNTIME_URLS):
        raise InvalidDocument("descriptor producer identities")
    return validated


def _reject_duplicate_json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidDocument(f"duplicate JSON field: {key}")
        result[key] = value
    return result


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect rejected", headers, fp)


def _integer(value: object, maximum: int, field: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise InvalidDocument(field)
    return value


def _timestamp(value: object, field: str, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or len(value) > 24 or not value.endswith("Z"):
        raise InvalidDocument(field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidDocument(field) from exc
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise InvalidDocument(field)
    return parsed


def parse_document(payload: bytes, now: datetime | None = None) -> dict[str, object]:
    """Mirror the pinned app validator and check the surrounding passive envelope."""
    if len(payload) > MAX_BYTES:
        raise OverflowError("runtime document exceeds 262144 bytes")
    try:
        document = json.loads(payload, object_pairs_hook=_reject_duplicate_json_fields)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise InvalidDocument("JSON") from exc
    if not isinstance(document, dict) or set(document) != {
        "schemaVersion",
        "generatedAt",
        "expiresAt",
        "source",
        "repos",
        "errors",
        "cache",
    }:
        raise InvalidDocument("document fields")
    if document["schemaVersion"] != 1 or type(document["schemaVersion"]) is not int:
        raise InvalidDocument("schemaVersion")
    generated = _timestamp(document["generatedAt"], "generatedAt", nullable=True)
    expires = _timestamp(document["expiresAt"], "expiresAt", nullable=True)
    if (generated is None) != (expires is None) or (generated and expires <= generated):
        raise InvalidDocument("envelope timestamps")
    repos, errors = document["repos"], document["errors"]
    if not isinstance(repos, dict) or len(repos) > MAX_COUNT or not isinstance(errors, dict):
        raise InvalidDocument("repos/errors")

    cache = document["cache"]
    fields = {
        "enabled",
        "state",
        "lastSuccessfulRefreshAt",
        "oldestDataFetchedAt",
        "retainedDataAgeSeconds",
        "dataCompleteness",
        "refreshDurationMs",
        "failureCategories",
        "configuredRepositoryCount",
        "successfulRepositoryCount",
        "failedRepositoryCount",
        "retainedRepositoryCount",
    }
    if not isinstance(cache, dict) or set(cache) != fields:
        raise InvalidDocument("cache fields")
    enabled, state, completeness = cache["enabled"], cache["state"], cache["dataCompleteness"]
    if type(enabled) is not bool or state not in STATES or completeness not in COMPLETENESS:
        raise InvalidDocument("cache enum")
    if document["source"] != SOURCE_BY_STATE[state]:
        raise InvalidDocument("source")
    failures = cache["failureCategories"]
    if (
        not isinstance(failures, list)
        or len(failures) > len(FAILURES)
        or any(type(item) is not str or item not in FAILURES for item in failures)
        or len(failures) != len(set(failures))
    ):
        raise InvalidDocument("failureCategories")
    counts = {
        key: _integer(cache[f"{key}RepositoryCount"], MAX_COUNT, key)
        for key in ("configured", "successful", "failed", "retained")
    }
    duration = cache["refreshDurationMs"]
    age = cache["retainedDataAgeSeconds"]
    if duration is not None:
        duration = _integer(duration, MAX_DURATION_MS, "refreshDurationMs")
    if age is not None:
        age = _integer(age, MAX_AGE_SECONDS, "retainedDataAgeSeconds")
    last_success = _timestamp(
        cache["lastSuccessfulRefreshAt"], "lastSuccessfulRefreshAt", nullable=True
    )
    oldest = _timestamp(cache["oldestDataFetchedAt"], "oldestDataFetchedAt", nullable=True)
    has_data = counts["successful"] > 0 or counts["retained"] > 0
    completed = state in {"fresh", "stale", "unavailable"}
    contradictory = (
        enabled != (state != "disabled")
        or (enabled and counts["configured"] == 0)
        or (state != "warming" and counts["successful"] + counts["failed"] != counts["configured"])
        or counts["retained"] > counts["failed"]
        or (completed and duration is None)
        or (counts["failed"] > 0) != bool(failures)
        or (
            state in {"disabled", "warming"}
            and (
                (state == "disabled" and counts["configured"] != 0)
                or any(counts[key] for key in ("successful", "failed", "retained"))
                or completeness != "none"
                or duration is not None
                or last_success is not None
                or oldest is not None
                or age is not None
                or failures
            )
        )
        or (
            state == "fresh"
            and (
                completeness != "complete"
                or last_success is None
                or counts["failed"] != 0
                or failures
            )
        )
        or (
            state == "stale"
            and (completeness != "partial" or counts["failed"] == 0 or not has_data)
        )
        or (state == "unavailable" and (completeness != "none" or has_data))
        or (has_data != (oldest is not None and age is not None))
        or len(repos) != counts["successful"] + counts["retained"]
    )
    current = now or datetime.now(timezone.utc)
    if any(ts is not None and ts > current for ts in (generated, last_success, oldest)):
        raise InvalidDocument("future timestamp")
    if contradictory:
        raise InvalidDocument("cache state/count relationship")
    return {
        "enabled": enabled,
        "state": state,
        "completeness": completeness,
        "failures": set(failures),
        "counts": counts,
        "duration": duration,
        "age": age,
        "last_success": last_success,
        "oldest": oldest,
    }


def _metric(name: str, value: int | float, label: str = "") -> str:
    rendered = str(int(value)) if isinstance(value, int) or value.is_integer() else f"{value:g}"
    return f"{name}{label} {rendered}"


def _render_values(
    values: dict[str, object] | None,
    *,
    monitoring_enabled: bool,
    collection_up: bool | None = None,
    environment: str,
    name: str,
    collected_at: datetime | None = None,
) -> str:
    """Render canonical metrics and compatibility aliases from validated values."""
    identity = f'{{environment="{environment}",name="{name}"}}'
    current = collected_at or datetime.now(timezone.utc)
    up = values is not None if collection_up is None else collection_up
    lines = [
        _metric("daniel_github_cache_monitoring_enabled", int(monitoring_enabled), identity),
        _metric("daniel_github_cache_collection_up", int(up), identity),
        _metric("daniel_github_cache_collection_timestamp_seconds", current.timestamp(), identity),
    ]
    if values is None:
        lines.append(_metric("daniel_cache_collection_up", 0, f'{{environment="{environment}"}}'))
        return "\n".join(lines) + "\n"
    lines.append(_metric("daniel_github_cache_enabled", int(values["enabled"])))
    for item in STATES:
        lines.append(
            _metric(
                "daniel_github_cache_state", int(item == values["state"]), f'{{state="{item}"}}'
            )
        )
    for item in COMPLETENESS:
        lines.append(
            _metric(
                "daniel_github_cache_data_completeness",
                int(item == values["completeness"]),
                f'{{completeness="{item}"}}',
            )
        )
    for item in FAILURES:
        lines.append(
            _metric(
                "daniel_github_cache_refresh_failure",
                int(item in values["failures"]),
                f'{{category="{item}"}}',
            )
        )
    lines.extend(
        [
            _metric(
                "daniel_github_cache_last_success_unixtime_seconds",
                values["last_success"].timestamp() if values["last_success"] else 0,
            ),
            _metric(
                "daniel_github_cache_oldest_data_unixtime_seconds",
                values["oldest"].timestamp() if values["oldest"] else 0,
            ),
            _metric("daniel_github_cache_retained_data_age_seconds", values["age"] or 0),
            _metric("daniel_github_cache_refresh_duration_milliseconds", values["duration"] or 0),
        ]
    )
    for key in ("configured", "successful", "failed", "retained"):
        lines.append(_metric(f"daniel_github_cache_{key}_repositories", values["counts"][key]))

    # Step 07c owns dashboard migration; keep these aliases sourced from the
    # same validated object rather than a second parser or collector.
    env = f'{{environment="{environment}"}}'
    lines.append(_metric("daniel_cache_collection_up", int(up), env))
    for metric, domain, selected, label in (
        ("daniel_cache_state", STATES, values["state"], "state"),
        ("daniel_cache_data_completeness", COMPLETENESS, values["completeness"], "completeness"),
    ):
        for item in domain:
            lines.append(
                _metric(
                    metric,
                    int(item == selected),
                    f'{{environment="{environment}",{label}="{item}"}}',
                )
            )
    for item in FAILURES:
        lines.append(
            _metric(
                "daniel_cache_failure_category",
                int(item in values["failures"]),
                f'{{environment="{environment}",category="{item}"}}',
            )
        )
    if values["last_success"] is not None:
        lines.append(
            _metric(
                "daniel_cache_freshness_age_seconds",
                max(0, current.timestamp() - values["last_success"].timestamp()),
                env,
            )
        )
    if values["duration"] is not None:
        lines.append(
            _metric("daniel_cache_refresh_duration_seconds", values["duration"] / 1000, env)
        )
    if values["age"] is not None:
        lines.append(_metric("daniel_cache_retained_data_age_seconds", values["age"], env))
    for key in ("configured", "successful", "failed", "retained"):
        lines.append(
            _metric(
                "daniel_cache_repositories",
                values["counts"][key],
                f'{{environment="{environment}",result="{key}"}}',
            )
        )
    output = "\n".join(lines) + "\n"
    if len(output.encode()) > MAX_METRICS_BYTES:
        raise InvalidDocument("serialized metrics")
    return output


def render(payload, environment=None, *, now=None, **kwargs) -> str:
    """Render one validated values object; bytes are accepted for direct adapter tests."""
    if isinstance(payload, (bytes, bytearray)):
        values = parse_document(payload, now)
        return _render_values(
            values,
            monitoring_enabled=True,
            environment=environment,
            name=f"danielsmith-github-cache-{environment}",
            collected_at=now,
        )
    return _render_values(payload, environment=environment, **kwargs)


def collect(producer, environment=None, *, opener=None, now=None) -> str:
    """Read only the passive application snapshot; disabled producers do no I/O."""
    if isinstance(producer, str):
        if environment not in RUNTIME_URLS or producer != RUNTIME_URLS[environment]:
            raise ValueError("URL must be the canonical runtime URL for the selected environment")
        producer = {
            "url": producer,
            "environment": environment,
            "name": f"danielsmith-github-cache-{environment}",
            "enabled": True,
        }
    if not producer["enabled"]:
        neutral = {
            "enabled": False,
            "state": "disabled",
            "completeness": "none",
            "failures": set(),
            "counts": {key: 0 for key in ("configured", "successful", "failed", "retained")},
            "duration": None,
            "age": None,
            "last_success": None,
            "oldest": None,
        }
        return _render_values(
            neutral,
            monitoring_enabled=False,
            collection_up=False,
            environment=producer["environment"],
            name=producer["name"],
            collected_at=now,
        )
    open_url = opener or urllib.request.build_opener(_RejectRedirects()).open
    try:
        request = urllib.request.Request(
            producer["url"],
            headers={
                "Accept": "application/json",
                "User-Agent": "sugarkube-daniel-cache-collector/1",
            },
        )
        with open_url(request, timeout=10) as response:
            if getattr(response, "geturl", lambda: producer["url"])() != producer["url"]:
                raise urllib.error.URLError("redirected response rejected")
            payload = response.read(MAX_BYTES + 1)
        return _render_values(
            parse_document(payload, now),
            monitoring_enabled=True,
            environment=producer["environment"],
            name=producer["name"],
            collected_at=now,
        )
    except OverflowError:
        pass
    except InvalidDocument:
        pass
    except (OSError, TimeoutError, http.client.HTTPException, urllib.error.URLError):
        pass
    return _render_values(
        None,
        monitoring_enabled=True,
        environment=producer["environment"],
        name=producer["name"],
        collected_at=now,
    )


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--descriptor",
        type=Path,
        required=True,
    )
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        descriptor = json.loads(
            args.descriptor.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_fields,
        )
        producers = validate_descriptor(descriptor)
        producer = next(item for item in producers if item["environment"] == args.environment)
        output = collect(producer)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, StopIteration) as error:
        # Replace a formerly healthy textfile before reporting configuration failure.
        write_textfile(
            args.output,
            render(
                None,
                monitoring_enabled=True,
                collection_up=False,
                environment=args.environment,
                name=f"danielsmith-github-cache-{args.environment}",
            ),
        )
        parser.error(str(error))
    write_textfile(args.output, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
