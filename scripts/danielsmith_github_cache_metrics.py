#!/usr/bin/env python3
"""Validate an already-published Daniel GitHub-cache snapshot and emit metrics."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from scripts import validate_probe_quotas

ROOT = Path(__file__).resolve().parents[1]
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
CACHE_FIELDS = {
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


def _timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 24 or not value.endswith("Z"):
        raise ValueError("cache timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("cache timestamp is invalid") from error
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ValueError("cache timestamp is not canonical")
    return int(parsed.timestamp())


def validate_cache(value):
    """Mirror the pinned application contract; reject rather than repair drift."""
    if not isinstance(value, dict) or set(value) != CACHE_FIELDS:
        raise ValueError("cache snapshot does not match the exact sanitized schema")
    if type(value["enabled"]) is not bool or value["state"] not in STATES:
        raise ValueError("cache enablement or state is invalid")
    if value["dataCompleteness"] not in COMPLETENESS:
        raise ValueError("cache completeness is invalid")
    categories = value["failureCategories"]
    if (
        not isinstance(categories, list)
        or len(categories) != len(set(categories))
        or categories != sorted(categories)
        or any(item not in FAILURES for item in categories)
    ):
        raise ValueError("cache failure categories are invalid")
    counts = [
        value[key]
        for key in (
            "configuredRepositoryCount",
            "successfulRepositoryCount",
            "failedRepositoryCount",
            "retainedRepositoryCount",
        )
    ]
    if any(type(item) is not int or not 0 <= item <= 50 for item in counts):
        raise ValueError("cache repository counts are invalid")
    configured, successful, failed, retained = counts
    duration, age = value["refreshDurationMs"], value["retainedDataAgeSeconds"]
    if duration is not None and (type(duration) is not int or not 0 <= duration <= 3_600_000):
        raise ValueError("cache refresh duration is invalid")
    if age is not None and (type(age) is not int or not 0 <= age <= 31_536_000):
        raise ValueError("cache retained-data age is invalid")
    last_success = _timestamp(value["lastSuccessfulRefreshAt"])
    oldest = _timestamp(value["oldestDataFetchedAt"])
    state, completeness = value["state"], value["dataCompleteness"]
    has_data = retained > 0 or successful > 0
    complete_attempt = state in {"fresh", "stale", "unavailable"}
    contradictory = (
        (state != "warming" and successful + failed != configured)
        or retained > failed
        or (value["enabled"] != (state != "disabled"))
        or (value["enabled"] and configured == 0)
        or (complete_attempt and duration is None)
        or ((failed > 0) != bool(categories))
        or (
            state in {"disabled", "warming"}
            and (
                (state == "disabled" and configured != 0)
                or successful
                or failed
                or retained
                or completeness != "none"
                or duration is not None
                or last_success is not None
                or oldest is not None
                or age is not None
                or categories
            )
        )
        or (
            state == "fresh"
            and (completeness != "complete" or last_success is None or failed or categories)
        )
        or (state == "stale" and (completeness != "partial" or not failed or not has_data))
        or (state == "unavailable" and (completeness != "none" or has_data))
        or (has_data != (oldest is not None and age is not None))
    )
    if contradictory:
        raise ValueError("cache snapshot contains contradictory lifecycle data")
    return dict(value), last_success or 0, oldest or 0


def render_metrics(producer, snapshot=None):
    labels = ",".join(f'{key}="{producer[key]}"' for key in ("application", "environment", "name"))
    lines = [f"daniel_github_cache_monitoring_enabled{{{labels}}} {int(producer['enabled'])}"]
    if not producer["enabled"]:
        if snapshot is not None:
            raise ValueError("disabled producer cannot publish a snapshot")
        return "\n".join(lines) + "\n"
    if snapshot is None:
        return "\n".join(lines) + "\n"
    cache, last_success, oldest = validate_cache(snapshot)
    if not cache["enabled"]:
        raise ValueError("enabled producer received disabled telemetry")
    suffix = f",{labels}"
    lines.append(f"daniel_github_cache_enabled{{{labels}}} 1")
    for state in STATES:
        lines.append(
            f'daniel_github_cache_state{{state="{state}"{suffix}}} {int(cache["state"] == state)}'
        )
    for item in COMPLETENESS:
        lines.append(
            f'daniel_github_cache_data_completeness{{completeness="{item}"{suffix}}} {int(cache["dataCompleteness"] == item)}'
        )
    for category in FAILURES:
        lines.append(
            f'daniel_github_cache_refresh_failure{{category="{category}"{suffix}}} {int(category in cache["failureCategories"])}'
        )
    scalars = {
        "last_success_unixtime_seconds": last_success,
        "oldest_data_unixtime_seconds": oldest,
        "retained_data_age_seconds": cache["retainedDataAgeSeconds"] or 0,
        "refresh_duration_milliseconds": cache["refreshDurationMs"] or 0,
        "configured_repositories": cache["configuredRepositoryCount"],
        "successful_repositories": cache["successfulRepositoryCount"],
        "failed_repositories": cache["failedRepositoryCount"],
        "retained_repositories": cache["retainedRepositoryCount"],
    }
    lines.extend(
        f"daniel_github_cache_{name}{{{labels}}} {value}" for name, value in scalars.items()
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--descriptor",
        type=Path,
        default=ROOT / "config/observability/danielsmith-github-cache.json",
    )
    parser.add_argument("--environment", required=True, choices=("staging", "prod"))
    parser.add_argument(
        "--snapshot", type=Path, help="already-published application JSON; never a URL"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        descriptor = json.loads(
            args.descriptor.read_text(),
            object_pairs_hook=validate_probe_quotas._reject_duplicate_json_fields,
        )
        validate_probe_quotas.validate_daniel_cache_contract(descriptor)
        producer = next(
            item for item in descriptor["producers"] if item["environment"] == args.environment
        )
        document = (
            json.loads(
                args.snapshot.read_text(),
                object_pairs_hook=validate_probe_quotas._reject_duplicate_json_fields,
            )
            if args.snapshot
            else None
        )
        snapshot = document.get(producer["snapshotField"]) if isinstance(document, dict) else None
        content = render_metrics(producer, snapshot)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, StopIteration) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".daniel-github-cache.", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
