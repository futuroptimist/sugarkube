import json
import pathlib
from datetime import date, datetime, timezone
from urllib import error, request

import pytest


def _fetch_remote_utc_date() -> date:
    """Return today's UTC date, preferring trusted time services."""
    endpoints = [
        (
            "https://worldtimeapi.org/api/timezone/Etc/UTC",
            lambda payload: payload.get("utc_datetime") or payload.get("datetime"),
        ),
        (
            "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
            lambda payload: payload.get("dateTime") or payload.get("date"),
        ),
    ]

    for url, extractor in endpoints:
        try:
            with request.urlopen(url, timeout=5) as response:
                if getattr(response, "status", 200) >= 400:
                    continue
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            continue

        raw_value = extractor(payload)
        if not raw_value:
            continue

        if isinstance(raw_value, str):
            normalized = raw_value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized).astimezone(timezone.utc).date()
            except ValueError:
                try:
                    return date.fromisoformat(normalized[:10])
                except ValueError:
                    continue

    return datetime.now(timezone.utc).date()


def _iter_outage_files() -> list[pathlib.Path]:
    outages_dir = pathlib.Path(__file__).resolve().parents[1] / "outages"
    return sorted(p for p in outages_dir.glob("*.json") if p.name != "schema.json")


@pytest.mark.parametrize("outage_path", _iter_outage_files())
def test_outage_dates_are_not_in_future(outage_path: pathlib.Path) -> None:
    today = _fetch_remote_utc_date()

    data = json.loads(outage_path.read_text())
    outage_date = date.fromisoformat(data["date"])

    assert (
        outage_date <= today
    ), f"{outage_path.name} records {outage_date} which is later than {today}"
    assert outage_path.name.startswith(
        f"{data['date']}-"
    ), f"Filename {outage_path.name} does not start with {data['date']}"
