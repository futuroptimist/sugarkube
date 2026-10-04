#!/usr/bin/env python3
"""Capture a renderer-backed dashboard PNG without placing credentials in arguments."""

import argparse
import getpass
import json
import os
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the Authorization header to another endpoint.
        return None


def instant(value, now):
    if value == "now":
        return now
    if value.isdecimal():
        return int(value)
    match = re.fullmatch(r"now-(\d+)([smhdw])", value)
    if not match:
        raise ValueError("Use epoch milliseconds, now, or now-N with s/m/h/d/w units.")
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return now - int(match[1]) * units[match[2]] * 1000


def capture(args, credential, opener=None, now=None):
    base = urllib.parse.urlsplit(args.url)
    if (
        base.scheme not in {"http", "https"}
        or not base.hostname
        or base.username is not None
        or base.query
        or base.fragment
    ):
        raise ValueError("Use a Grafana HTTP(S) base URL without credentials, query, or fragment.")
    if not credential or any(character in credential for character in "\r\n"):
        raise ValueError("A single-line Grafana service account credential is required.")
    if not 1 <= args.width <= 4096 or not 1 <= args.height <= 16000:
        raise ValueError("Width must be 1–4096 and height 1–16000 pixels.")
    if args.panel_id is not None and args.panel_id < 1:
        raise ValueError("Panel ID must be positive.")
    now = now or datetime.now(timezone.utc)
    end = instant(args.end, int(now.timestamp() * 1000))
    start = instant(args.start, int(now.timestamp() * 1000))
    if start < 0 or start >= end:
        raise ValueError("The capture start must precede the end and be nonnegative.")
    uid = f"sugarkube-{args.environment}-observability"
    route = "d-solo" if args.panel_id is not None else "d"
    query = {
        "from": start,
        "to": end,
        "width": args.width,
        "height": args.height,
        "tz": "UTC",
    }
    if args.panel_id is not None:
        query["panelId"] = args.panel_id
    url = args.url.rstrip("/") + f"/render/{route}/{uid}/observability?"
    request = urllib.request.Request(
        url + urllib.parse.urlencode(query),
        headers={"Authorization": "Bearer " + credential, "Accept": "image/png"},
    )
    opener = opener or urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=180) as response:
        if response.status != 200 or response.headers.get_content_type() != "image/png":
            raise ValueError("Grafana did not return a rendered PNG; check renderer availability.")
        content = response.read(MAX_IMAGE_BYTES + 1)
    if (
        len(content) > MAX_IMAGE_BYTES
        or len(content) < 33
        or not content.startswith(PNG_SIGNATURE)
        or content[12:16] != b"IHDR"
        or struct.unpack(">II", content[16:24]) != (args.width, args.height)
        or not content.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    ):
        raise ValueError("Grafana returned an incomplete, oversized, or unexpected PNG.")
    destination = Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = f"-panel-{args.panel_id}" if args.panel_id is not None else ""
    stem = uid + suffix + "-" + now.strftime("%Y%m%dT%H%M%S%fZ")
    image = destination / (stem + ".png")
    metadata = destination / (stem + ".json")
    manifest = {
        "captured_at": now.isoformat(),
        "grafana_url": args.url.rstrip("/"),
        "dashboard_uid": uid,
        "environment": args.environment,
        "panel_id": args.panel_id,
        **query,
    }
    created = []
    complete = False
    try:
        for path, payload in (
            (image, content),
            (metadata, (json.dumps(manifest, indent=2) + "\n").encode()),
        ):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        directory_descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        complete = True
    finally:
        if not complete:
            for path in reversed(created):
                path.unlink(missing_ok=True)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--from", dest="start", default="now-6h")
    parser.add_argument("--to", dest="end", default="now")
    parser.add_argument("--panel-id", type=int)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1200)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    credential = os.environ.get("GRAFANA_CAPTURE_CREDENTIAL") or getpass.getpass(
        "Grafana service account credential: "
    )
    try:
        image = capture(args, credential)
    except (ValueError, OSError, urllib.error.URLError):
        # Server diagnostics can include request headers; do not echo them.
        print("Capture failed; check URL, credentials, time range, and renderer.", file=sys.stderr)
        return 1
    print(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
