from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

TIME_SOURCES: Iterable[str] = (
    "https://worldtimeapi.org/api/timezone/Etc/UTC",
    "https://www.timeapi.io/api/Time/current/zone?timeZone=UTC",
)


def _fetch_authoritative_date() -> date:
    for url in TIME_SOURCES:
        try:
            request = Request(url, headers={"User-Agent": "sugarkube-outage-date-test"})
            with urlopen(request, timeout=5) as response:  # nosec: B310 (trusted domain)
                payload = json.load(response)
        except (URLError, TimeoutError, json.JSONDecodeError):
            continue

        # worldtimeapi.org exposes either `datetime` or `utc_datetime`.
        if "unixtime" in payload:
            return datetime.fromtimestamp(payload["unixtime"], tz=timezone.utc).date()
        for key in ("utc_datetime", "datetime", "dateTime"):
            if key in payload:
                dt_raw = payload[key]
                if isinstance(dt_raw, str):
                    dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                    return dt.date()
        # timeapi.io returns discrete components.
        if {"year", "month", "day"} <= payload.keys():
            return datetime(
                payload["year"],
                payload["month"],
                payload["day"],
                tzinfo=timezone.utc,
            ).date()
    return datetime.now(timezone.utc).date()


def _iter_outage_files() -> Iterable[Path]:
    outages_dir = Path("outages")
    yield from sorted(
        path for path in outages_dir.glob("*.json") if path.name != "schema.json"
    )


def test_outage_records_are_not_future_dated():
    today = _fetch_authoritative_date()
    for path in _iter_outage_files():
        record = json.loads(path.read_text())
        record_date = datetime.fromisoformat(record["date"]).date()
        slug = path.stem[11:]
        assert (
            record["id"] == f"{record['date']}-{slug}"
        ), f"{path.name} id mismatch for computed slug {slug}"
        assert (
            path.stem.startswith(record["date"])
        ), f"{path.name} filename prefix does not match declared date"
        assert (
            record_date <= today
        ), f"{path.name} has future date {record['date']} beyond authoritative {today}"
