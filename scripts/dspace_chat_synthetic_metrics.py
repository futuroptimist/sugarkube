#!/usr/bin/env python3
"""Convert one pinned, isolated DSPACE smoke result to node-exporter textfile metrics.

This consumer deliberately does not download or execute test code.  A scheduler must
run the externally supplied smoke runner with mutation disabled and intercepted
transport, then pass its bounded JSON result here.
"""

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
ALLOWED_KEYS = {
    "schemaVersion",
    "journey",
    "passed",
    "executedAt",
    "runnerRevision",
    "transport",
    "mutationEnabled",
}
MAX_FUTURE_SKEW_SECONDS = 60


def parse_result(
    path: Path, expected_runner: str, *, now: float | None = None
) -> tuple[int, int]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != ALLOWED_KEYS:
        raise ValueError("result does not match the exact bounded schema")
    if value != {
        **value,
        "schemaVersion": 1,
        "journey": "/chat",
        "runnerRevision": expected_runner,
        "transport": "intercepted",
        "mutationEnabled": False,
    }:
        raise ValueError("result is not from the pinned isolated non-mutating contract")
    if (
        type(value["passed"]) is not bool
        or type(value["executedAt"]) is not int
        or value["executedAt"] < 1
    ):
        raise ValueError("result status or timestamp is invalid")
    if now is None:
        now = time.time()
    if value["executedAt"] > int(now) + MAX_FUTURE_SKEW_SECONDS:
        raise ValueError("result timestamp exceeds the allowed clock skew")
    return int(value["passed"]), value["executedAt"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runner-revision", required=True)
    parser.add_argument("--environment", choices=("staging", "prod"), default="staging")
    args = parser.parse_args()
    if args.environment != "staging":
        parser.error("production publishing is intentionally unsupported")
    if not SHA.fullmatch(args.runner_revision):
        parser.error("runner revision must be a full immutable commit SHA")
    try:
        passed, timestamp = parse_result(args.result, args.runner_revision)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    labels = 'application="dspace",environment="staging",cluster="sugarkube-int"'
    content = (
        "# HELP dspace_chat_synthetic_success Last executed isolated /chat result.\n"
        "# TYPE dspace_chat_synthetic_success gauge\n"
        f"dspace_chat_synthetic_success{{{labels}}} {passed}\n"
        "# HELP dspace_chat_synthetic_timestamp_seconds Unix time of the last execution.\n"
        "# TYPE dspace_chat_synthetic_timestamp_seconds gauge\n"
        f"dspace_chat_synthetic_timestamp_seconds{{{labels}}} {timestamp}\n"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".dspace-chat.", dir=args.output.parent)
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
