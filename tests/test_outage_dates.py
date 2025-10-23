from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Final
from urllib import error as urlerror
from urllib import request


_WORLD_TIME_API: Final = "https://worldtimeapi.org/api/timezone/Etc/UTC"


def _fetch_utc_date_from_api() -> _dt.date | None:
    try:
        with request.urlopen(_WORLD_TIME_API, timeout=5) as response:
            payload = response.read().decode("utf-8")
    except (urlerror.URLError, TimeoutError, OSError):
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    utc_datetime = data.get("utc_datetime")
    if not isinstance(utc_datetime, str):
        return None

    try:
        parsed = _dt.datetime.fromisoformat(utc_datetime.replace("Z", "+00:00"))
    except ValueError:
        return None

    return parsed.date()


def _current_utc_date() -> _dt.date:
    return _fetch_utc_date_from_api() or _dt.datetime.utcnow().date()


def test_outage_dates_are_not_in_the_future() -> None:
    outages_dir = Path(__file__).resolve().parents[1] / "outages"
    current_date = _current_utc_date()

    for outage_file in sorted(outages_dir.glob("*.json")):
        if outage_file.name == "schema.json":
            continue

        data = json.loads(outage_file.read_text(encoding="utf-8"))
        outage_date = _dt.date.fromisoformat(data["date"])

        assert (
            outage_date <= current_date
        ), f"{outage_file.name} records future date {outage_date}"

        assert outage_file.name.startswith(
            data["date"]
        ), f"{outage_file.name} must start with its JSON date {data['date']}"
