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

if __package__:
    from scripts import validate_probe_quotas
else:
    import validate_probe_quotas

ROOT = Path(__file__).resolve().parents[1]
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
DOCUMENT_STATUSES = ("valid", "malformed", "oversized", "unavailable")
RUNTIME_URLS = {
    "staging": "https://staging.danielsmith.io/runtime/github-metrics.json",
    "prod": "https://danielsmith.io/runtime/github-metrics.json",
}


class InvalidDocument(ValueError):
    """The passive document does not satisfy the pinned application contract."""


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
        document = json.loads(
            payload, object_pairs_hook=validate_probe_quotas._reject_duplicate_json_fields
        )
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
    if not isinstance(document["source"], str) or not document["source"]:
        raise InvalidDocument("source")
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
    if state == "stale" and last_success is None:
        raise InvalidDocument("stale snapshot has no lastSuccessfulRefreshAt")
    if oldest is not None and age != int((current - oldest).total_seconds()):
        raise InvalidDocument("retainedDataAgeSeconds does not match oldestDataFetchedAt")
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


def _render_new(
    values: dict[str, object] | None,
    *,
    monitoring_enabled: bool,
    status: str,
    collection_up: bool | None = None,
    environment: str | None = None,
    name: str | None = None,
    collected_at: datetime | None = None,
) -> str:
    """Render canonical application metrics plus bounded transport health."""
    identity = f'{{environment="{environment}",name="{name}"}}' if environment and name else ""
    lines = [
        "# HELP daniel_github_cache_monitoring_enabled Whether collection is authorized.",
        "# TYPE daniel_github_cache_monitoring_enabled gauge",
        _metric("daniel_github_cache_monitoring_enabled", int(monitoring_enabled), identity),
        "# HELP daniel_github_cache_collection_up Whether the passive snapshot was validated.",
        "# TYPE daniel_github_cache_collection_up gauge",
        _metric(
            "daniel_github_cache_collection_up",
            int(values is not None if collection_up is None else collection_up),
            identity,
        ),
        _metric(
            "daniel_github_cache_collection_timestamp_seconds",
            (collected_at or datetime.now(timezone.utc)).timestamp(),
            identity,
        ),
    ]
    for item in DOCUMENT_STATUSES:
        lines.append(
            _metric(
                "daniel_github_cache_document_status",
                int(item == status),
                (
                    f'{{environment="{environment}",name="{name}",status="{item}"}}'
                    if identity
                    else f'{{status="{item}"}}'
                ),
            )
        )
    if values is None:
        return "\n".join(lines) + "\n"
    lines.append(_metric("daniel_github_cache_enabled", int(values["enabled"]), identity))
    for item in STATES:
        lines.append(
            _metric(
                "daniel_github_cache_state",
                int(item == values["state"]),
                (
                    f'{{environment="{environment}",name="{name}",state="{item}"}}'
                    if identity
                    else f'{{state="{item}"}}'
                ),
            )
        )
    for item in COMPLETENESS:
        lines.append(
            _metric(
                "daniel_github_cache_data_completeness",
                int(item == values["completeness"]),
                (
                    f'{{environment="{environment}",name="{name}",completeness="{item}"}}'
                    if identity
                    else f'{{completeness="{item}"}}'
                ),
            )
        )
    for item in FAILURES:
        lines.append(
            _metric(
                "daniel_github_cache_refresh_failure",
                int(item in values["failures"]),
                (
                    f'{{environment="{environment}",name="{name}",category="{item}"}}'
                    if identity
                    else f'{{category="{item}"}}'
                ),
            )
        )
    lines.extend(
        [
            _metric(
                "daniel_github_cache_last_success_unixtime_seconds",
                values["last_success"].timestamp() if values["last_success"] else 0,
                identity,
            ),
            _metric(
                "daniel_github_cache_oldest_data_unixtime_seconds",
                values["oldest"].timestamp() if values["oldest"] else 0,
                identity,
            ),
            _metric("daniel_github_cache_retained_data_age_seconds", values["age"] or 0, identity),
            _metric(
                "daniel_github_cache_refresh_duration_milliseconds",
                values["duration"] or 0,
                identity,
            ),
        ]
    )
    for key in ("configured", "successful", "failed", "retained"):
        lines.append(
            _metric(f"daniel_github_cache_{key}_repositories", values["counts"][key], identity)
        )
    output = "\n".join(lines) + "\n"
    if len(output.encode()) > MAX_METRICS_BYTES:
        raise InvalidDocument("serialized metrics")
    return output


def _collect_new(producer: dict, *, opener=None, now=None) -> str:
    """Read only the passive application snapshot; disabled producers do no I/O."""
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
        return _render_new(
            neutral,
            monitoring_enabled=False,
            status="unavailable",
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
        return _render_new(
            parse_document(payload, now),
            monitoring_enabled=True,
            status="valid",
            environment=producer["environment"],
            name=producer["name"],
            collected_at=now,
        )
    except OverflowError:
        status = "oversized"
    except (InvalidDocument, validate_probe_quotas.ContractError):
        status = "malformed"
    except (OSError, TimeoutError, http.client.HTTPException, urllib.error.URLError):
        status = "unavailable"
    return _render_new(
        None,
        monitoring_enabled=True,
        status=status,
        environment=producer["environment"],
        name=producer["name"],
        collected_at=now,
    )


def render(payload, environment=None, **kwargs):
    """Render the descriptor contract, retaining the pre-existing dashboard API."""
    if isinstance(payload, (bytes, bytearray)) or payload is None and environment is not None:
        from scripts import daniel_cache_metrics_legacy as legacy

        return legacy.render(payload, environment, **kwargs)
    return _render_new(payload, **kwargs)


def collect(producer, environment=None, **kwargs):
    """Collect by pinned descriptor, or support the legacy canonical-URL caller."""
    if isinstance(producer, str):
        from scripts import daniel_cache_metrics_legacy as legacy

        return legacy.collect(producer, environment, **kwargs)
    return _collect_new(producer, **kwargs)


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
        default=ROOT / "config/observability/danielsmith-github-cache.json",
    )
    parser.add_argument("--url", help=argparse.SUPPRESS)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.url:
        write_textfile(args.output, collect(args.url, args.environment))
        return 0
    try:
        descriptor = json.loads(
            args.descriptor.read_text(encoding="utf-8"),
            object_pairs_hook=validate_probe_quotas._reject_duplicate_json_fields,
        )
        validate_probe_quotas.validate_daniel_cache_contract(descriptor)
        producer = next(
            item for item in descriptor["producers"] if item["environment"] == args.environment
        )
        output = collect(producer)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, StopIteration) as error:
        # Replace a formerly healthy textfile before reporting configuration failure.
        write_textfile(
            args.output,
            _render_new(
                None,
                monitoring_enabled=True,
                status="malformed",
                environment=args.environment,
                name=f"danielsmith-github-cache-{args.environment}",
            ),
        )
        parser.error(str(error))
    write_textfile(args.output, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
