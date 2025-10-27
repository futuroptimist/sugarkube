"""Regression coverage for outage metadata integrity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, date
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen


_TIME_API_URL = "https://worldtimeapi.org/api/timezone/Etc/UTC"


def _resolve_current_utc_date() -> date:
    """Return today's UTC date using a stable source with system time fallback."""

    try:
        with urlopen(_TIME_API_URL, timeout=5) as response:  # nosec: trusted time endpoint
            if response.status == 200:
                payload = json.load(response)
                raw_datetime: Optional[str] = payload.get("utc_datetime")
                if raw_datetime:
                    # worldtimeapi returns ISO 8601 strings with fractional seconds and trailing Z
                    normalized = raw_datetime.replace("Z", "+00:00")
                    return datetime.fromisoformat(normalized).date()
    except URLError:
        pass
    except TimeoutError:
        pass
    except Exception:
        # Treat malformed responses as a signal to fall back on system time.
        pass

    return datetime.now(UTC).date()


def test_outage_dates_are_not_in_the_future() -> None:
    """Outage entries should never carry a future date or mismatched filename prefix."""

    outages_dir = Path("outages")
    assert outages_dir.is_dir(), "outages/ directory must exist for outage records"

    today = _resolve_current_utc_date()

    for outage_file in sorted(outages_dir.glob("*.json")):
        if outage_file.name == "schema.json":
            continue

        content = json.loads(outage_file.read_text(encoding="utf-8"))
        recorded_date = content.get("date")
        assert recorded_date, f"{outage_file} is missing a date field"

        try:
            outage_date = datetime.strptime(recorded_date, "%Y-%m-%d").date()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise AssertionError(f"{outage_file} has invalid date: {recorded_date}") from exc

        assert (
            outage_date <= today
        ), f"{outage_file} has future date {recorded_date}; current UTC date is {today.isoformat()}"

        filename_prefix = outage_file.stem.split("-", 3)
        assert len(filename_prefix) >= 3, f"{outage_file} should start with YYYY-MM-DD"
        expected_prefix = "-".join(filename_prefix[:3])
        assert (
            expected_prefix == recorded_date
        ), f"Filename {outage_file.name} should start with outage date {recorded_date}"


def test_markdown_outages_require_json_companions() -> None:
    """Every long-form outage narrative must have a JSON record and link back to it."""

    outages_dir = Path("outages")
    assert outages_dir.is_dir(), "outages/ directory must exist for outage records"

    for md_file in sorted(outages_dir.glob("*.md")):
        json_file = md_file.with_suffix(".json")
        assert json_file.exists(), f"Missing JSON outage record for {md_file.name}"

        payload = json.loads(json_file.read_text(encoding="utf-8"))
        long_form = payload.get("longForm")
        assert long_form, f"{json_file.name} must declare its long-form companion"
        assert (
            Path(long_form).name == md_file.name
        ), f"{json_file.name} should reference {md_file.name} via longForm"
