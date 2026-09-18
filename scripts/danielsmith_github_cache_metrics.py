#!/usr/bin/env python3
"""Validate an application-owned GitHub-cache snapshot and publish bounded metrics."""

from __future__ import annotations
import argparse, datetime as dt, json, os, re, tempfile
from pathlib import Path

if __package__:
    from scripts import validate_probe_quotas
else:
    import validate_probe_quotas
ROOT = Path(__file__).resolve().parents[1]
STATES = ("disabled", "warming", "fresh", "stale", "unavailable")
COMPLETENESS = ("complete", "partial", "none")
CATEGORIES = (
    "configuration",
    "internal",
    "invalid_response",
    "network",
    "not_found",
    "rate_limited",
    "timeout",
    "upstream",
)
FIELDS = {
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
IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 24 or not value.endswith("Z"):
        raise ValueError("cache timestamp is invalid")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("cache timestamp is invalid") from exc
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ValueError("cache timestamp is not canonical UTC")
    return parsed.timestamp()


def validate_snapshot(value):
    """Revalidate the exact bounded application cache object, failing closed."""
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("snapshot does not match the exact cache schema")
    if (
        type(value["enabled"]) is not bool
        or value["state"] not in STATES
        or value["dataCompleteness"] not in COMPLETENESS
    ):
        raise ValueError("snapshot has an invalid fixed-domain value")
    cats = value["failureCategories"]
    if (
        not isinstance(cats, list)
        or len(cats) != len(set(cats))
        or cats != sorted(cats)
        or any(c not in CATEGORIES for c in cats)
    ):
        raise ValueError("snapshot failure categories are invalid")
    last = _timestamp(value["lastSuccessfulRefreshAt"])
    oldest = _timestamp(value["oldestDataFetchedAt"])
    counts = []
    for key in (
        "configuredRepositoryCount",
        "successfulRepositoryCount",
        "failedRepositoryCount",
        "retainedRepositoryCount",
    ):
        number = value[key]
        if type(number) is not int or not 0 <= number <= 50:
            raise ValueError("snapshot repository count is invalid")
        counts.append(number)
    configured, successful, failed, retained = counts
    age = value["retainedDataAgeSeconds"]
    duration = value["refreshDurationMs"]
    if age is not None and (type(age) is not int or not 0 <= age <= 31_536_000):
        raise ValueError("snapshot retained age is invalid")
    if duration is not None and (type(duration) is not int or not 0 <= duration <= 3_600_000):
        raise ValueError("snapshot duration is invalid")
    state = value["state"]
    has_data = successful > 0 or retained > 0
    completed = state in {"fresh", "stale", "unavailable"}
    invalid = (
        value["enabled"] != (state != "disabled")
        or (value["enabled"] and configured == 0)
        or (state != "warming" and successful + failed != configured)
        or retained > failed
        or (completed and duration is None)
        or (failed > 0) != (len(cats) > 0)
        or (
            state in {"disabled", "warming"}
            and (
                successful
                or failed
                or retained
                or value["dataCompleteness"] != "none"
                or duration is not None
                or last is not None
                or oldest is not None
                or age is not None
                or cats
            )
        )
        or (state == "disabled" and configured != 0)
        or (
            state == "fresh"
            and (value["dataCompleteness"] != "complete" or last is None or failed or cats)
        )
        or (
            state == "stale"
            and (value["dataCompleteness"] != "partial" or not failed or not has_data)
        )
        or (state == "unavailable" and (value["dataCompleteness"] != "none" or has_data))
        or (has_data != (oldest is not None and age is not None))
    )
    if invalid:
        raise ValueError("snapshot state and values are contradictory")
    return dict(value), last, oldest


def render_metrics(producer, snapshot=None):
    if (
        not isinstance(producer, dict)
        or any(
            not isinstance(producer.get(k), str) or not IDENTITY.fullmatch(producer[k])
            for k in ("name", "application", "environment")
        )
        or type(producer.get("enabled")) is not bool
    ):
        raise ValueError("producer identity or enablement is invalid")
    labels = ",".join(f'{k}="{producer[k]}"' for k in ("application", "environment", "name"))
    lines = [
        "# HELP daniel_github_cache_monitoring_enabled Whether collection is authorized.",
        "# TYPE daniel_github_cache_monitoring_enabled gauge",
        f"daniel_github_cache_monitoring_enabled{{{labels}}} {int(producer['enabled'])}",
    ]
    if not producer["enabled"]:
        if snapshot is not None:
            raise ValueError("disabled producer cannot supply a snapshot")
        return "\n".join(lines) + "\n"
    if snapshot is None:
        return "\n".join(lines) + "\n"
    value, last, oldest = validate_snapshot(snapshot)

    def metric(name, number, label=""):
        lines.append(f"{name}{{{labels}{(','+label) if label else ''}}} {number:g}")

    metric("daniel_github_cache_enabled", int(value["enabled"]))
    for item in STATES:
        metric("daniel_github_cache_state", int(value["state"] == item), f'state="{item}"')
    for item in COMPLETENESS:
        metric(
            "daniel_github_cache_data_completeness",
            int(value["dataCompleteness"] == item),
            f'completeness="{item}"',
        )
    for item in CATEGORIES:
        metric(
            "daniel_github_cache_refresh_failure",
            int(item in value["failureCategories"]),
            f'category="{item}"',
        )
    for name, number in (
        ("last_success_unixtime_seconds", last or 0),
        ("oldest_data_unixtime_seconds", oldest or 0),
        ("retained_data_age_seconds", value["retainedDataAgeSeconds"] or 0),
        ("refresh_duration_milliseconds", value["refreshDurationMs"] or 0),
        ("configured_repositories", value["configuredRepositoryCount"]),
        ("successful_repositories", value["successfulRepositoryCount"]),
        ("failed_repositories", value["failedRepositoryCount"]),
        ("retained_repositories", value["retainedRepositoryCount"]),
    ):
        metric("daniel_github_cache_" + name, number)
    output = "\n".join(lines) + "\n"
    if len(output.encode()) > 8192:
        raise ValueError("metric output exceeds the bounded contract")
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--descriptor",
        type=Path,
        default=ROOT / "config/observability/danielsmith-github-cache.json",
    )
    p.add_argument("--environment", required=True, choices=("staging", "prod"))
    p.add_argument("--snapshot", type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args(argv)
    try:
        descriptor = json.loads(
            a.descriptor.read_text(),
            object_pairs_hook=validate_probe_quotas._reject_duplicate_json_fields,
        )
        validate_probe_quotas.validate_github_cache_contract(descriptor)
        producer = next(x for x in descriptor["producers"] if x["environment"] == a.environment)
        snapshot = (
            json.loads(
                a.snapshot.read_text(),
                object_pairs_hook=validate_probe_quotas._reject_duplicate_json_fields,
            )
            if a.snapshot
            else None
        )
        content = render_metrics(producer, snapshot)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, StopIteration) as exc:
        p.error(str(exc))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".daniel-github-cache.", dir=a.output.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o644)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, a.output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
