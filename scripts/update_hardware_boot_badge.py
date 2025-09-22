#!/usr/bin/env python3
"""Update the hardware boot conformance badge JSON for shields.io."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_STATUS = "pass"
STATUS_PRESETS = {
    "pass": {"label": "passing", "color": "brightgreen"},
    "warn": {"label": "attention", "color": "orange"},
    "fail": {"label": "failing", "color": "red"},
    "unknown": {"label": "unknown", "color": "lightgrey"},
}


def _default_output() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "status" / "hardware-boot.json"


def _parse_timestamp(value: str | None) -> _dt.datetime:
    if not value or value.lower() == "now":
        return _dt.datetime.now(tz=_dt.timezone.utc)

    parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def _normalise_links(values: Iterable[str]) -> Sequence[str]:
    links = [v for v in values if v]
    if not links:
        return ()
    if len(links) > 2:
        raise ValueError("Shields.io supports up to two links; received %s" % len(links))
    return tuple(links)


def build_badge_payload(
    *,
    status: str,
    timestamp: _dt.datetime,
    notes: str | None,
    label: str,
    description: str | None,
    links: Sequence[str],
    cache_seconds: int,
) -> dict:
    preset = STATUS_PRESETS.get(status)
    if not preset:
        valid = ", ".join(sorted(STATUS_PRESETS))
        raise ValueError(f"Unsupported status '{status}'. Expected one of: {valid}")

    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    message = f"{preset['label']} • {formatted_time}"
    if notes:
        message = f"{message} • {notes}"

    payload: dict[str, object] = {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": preset["color"],
        "namedLogo": "raspberry-pi",
        "cacheSeconds": cache_seconds,
    }
    if description:
        payload["description"] = description
    if links:
        payload["link"] = list(links)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate shields.io endpoint JSON describing the last hardware boot run.",
    )
    parser.add_argument(
        "--status",
        default=DEFAULT_STATUS,
        choices=sorted(STATUS_PRESETS),
        help="Overall outcome: pass (default), warn, fail, or unknown.",
    )
    parser.add_argument(
        "--timestamp",
        default="now",
        help="ISO-8601 timestamp (UTC recommended). Defaults to the current time.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Optional short annotation appended to the badge message (e.g. host name).",
    )
    parser.add_argument(
        "--label",
        default="hardware boot",
        help="Badge label text. Defaults to 'hardware boot'.",
    )
    parser.add_argument(
        "--description",
        default=None,
        help="Optional tooltip description rendered by shields.io.",
    )
    parser.add_argument(
        "--link",
        action="append",
        default=[],
        help="Optional badge hyperlink (can be set twice for left/right).",
    )
    parser.add_argument(
        "--cache-seconds",
        type=int,
        default=900,
        help="Cache control for shields.io consumers (default: 900).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output(),
        help="Destination JSON file. Defaults to docs/status/hardware-boot.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated JSON instead of writing the output file.",
    )

    args = parser.parse_args()

    timestamp = _parse_timestamp(args.timestamp)
    links = _normalise_links(args.link)
    payload = build_badge_payload(
        status=args.status,
        timestamp=timestamp,
        notes=args.notes,
        label=args.label,
        description=args.description,
        links=links,
        cache_seconds=args.cache_seconds,
    )

    json_payload = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if args.dry_run:
        print(json_payload, end="")
        return

    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_payload, encoding="utf-8")
    print(f"Wrote {output_path} with message: {payload['message']}")


if __name__ == "__main__":
    main()
