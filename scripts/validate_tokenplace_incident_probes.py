#!/usr/bin/env python3
"""Validate the portable token.place incident Probe projection."""

from __future__ import annotations

import argparse

from tokenplace_incident_drill import DrillError, inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args(argv)
    try:
        inventory(args.environment)
    except (DrillError, OSError, ValueError):
        parser.error("token.place incident Probe inventory validation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
