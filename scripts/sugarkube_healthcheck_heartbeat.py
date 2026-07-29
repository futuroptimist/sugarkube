#!/usr/bin/env python3
"""Send one secret-safe Healthchecks.io node heartbeat."""

from __future__ import annotations

import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL_RE = re.compile(
    r"https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 7
OVERALL_TIMEOUT_SECONDS = 25


def load_url() -> str:
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not directory:
        raise ValueError("systemd credential directory is unavailable")
    raw = (Path(directory) / "ping-url").read_bytes()
    try:
        url = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("credential is not ASCII") from exc
    if raw.endswith(b"\n"):
        url = url[:-1]
    if not url or "\n" in url or "\r" in url or URL_RE.fullmatch(url) is None:
        raise ValueError("credential is not an allowed Healthchecks.io ping URL")
    return url


def deliver(url: str) -> None:
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "sugarkube-node-heartbeat/1"}
    )
    last_error: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                if 200 <= response.status < 300:
                    return
                raise RuntimeError("remote endpoint returned a non-success response")
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < ATTEMPTS:
                time.sleep(1)
    raise RuntimeError(
        "heartbeat delivery failed after bounded retries"
    ) from last_error


def main() -> int:
    signal.alarm(OVERALL_TIMEOUT_SECONDS)
    try:
        deliver(load_url())
    except (OSError, ValueError, RuntimeError, TimeoutError):
        print(
            "ERROR: node heartbeat failed; inspect network, credential format, and unit configuration",
            file=sys.stderr,
        )
        return 1
    finally:
        signal.alarm(0)
    print("Node heartbeat delivered successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
