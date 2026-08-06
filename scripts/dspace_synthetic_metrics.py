#!/usr/bin/env python3
"""Publish a bounded DSPACE runtime-verifier result for a Prometheus textfile collector."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path

REVISION = re.compile(r"[0-9a-f]{40}")
FORBIDDEN_ENV = tuple(
    name + "_" + "KEY" for name in ("OPENAI_API", "TOKEN_PLACE_API", "DSPACE_API")
)


def render(document: object, now: int) -> str:
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise ValueError("runtime verifier result is malformed")
    environment = document.get("environment")
    revision = document.get("runtimeSourceRevision")
    journeys = document.get("journeys")
    if (
        environment not in {"staging", "prod"}
        or not isinstance(revision, str)
        or not REVISION.fullmatch(revision)
    ):
        raise ValueError("runtime verifier identity is malformed")
    if not isinstance(journeys, list):
        raise ValueError("runtime verifier journeys are malformed")
    chat = [item for item in journeys if isinstance(item, dict) and item.get("name") == "/chat"]
    if len(chat) != 1 or type(chat[0].get("passed")) is not bool:  # noqa: E721
        raise ValueError("runtime verifier must report exactly one bounded /chat result")
    labels = f'application="dspace",environment="{environment}",revision="{revision}"'
    success = 1 if chat[0]["passed"] else 0
    return (
        "# HELP dspace_chat_synthetic_success Last non-mutating /chat check result.\n"
        "# TYPE dspace_chat_synthetic_success gauge\n"
        f"dspace_chat_synthetic_success{{{labels}}} {success}\n"
        "# HELP dspace_chat_synthetic_timestamp_seconds Unix time of the last executed check.\n"
        "# TYPE dspace_chat_synthetic_timestamp_seconds gauge\n"
        f"dspace_chat_synthetic_timestamp_seconds{{{labels}}} {now}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timestamp", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(os.environ.get(name) for name in FORBIDDEN_ENV):
        parser.error("credential environment variables are refused")
    document = json.loads(args.result.read_text(encoding="utf-8"))
    payload = render(document, int(time.time()) if args.timestamp is None else args.timestamp)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{args.output.name}.", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
