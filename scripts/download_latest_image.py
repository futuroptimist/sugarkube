#!/usr/bin/env python3
"""Download the latest pi-image artifact from GitHub."""

import argparse
import fnmatch
import hashlib
import io
import os
import sys
import time
import zipfile
from datetime import datetime, timezone

import requests

API = "https://api.github.com"


def _request(
    session: requests.Session, method: str, url: str, **kwargs
) -> requests.Response:
    for attempt in range(6):
        resp = session.request(method, url, **kwargs)
        if resp.status_code < 500 and resp.status_code not in (429, 403):
            return resp
        time.sleep(2**attempt)
    resp.raise_for_status()
    return resp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="futuroptimist/sugarkube")
    parser.add_argument("--workflow", default="pi-image.yml")
    parser.add_argument("--artifact-pattern", default="*.img.xz")
    parser.add_argument("--max-age-hours", type=int, default=24)
    args = parser.parse_args(argv)

    token = os.getenv("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with requests.Session() as session:
        session.headers.update(headers)
        base = f"{API}/repos/{args.repo}/actions/workflows/"
        runs_url = f"{base}{args.workflow}/runs"
        runs_resp = _request(
            session,
            "GET",
            runs_url,
            params={"per_page": 1, "status": "success"},
        )
        runs = runs_resp.json().get("workflow_runs", [])
        if not runs:
            print("no successful workflow runs found", file=sys.stderr)
            return 1
        run = runs[0]
        ts = run["updated_at"].rstrip("Z")
        updated = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - updated
        age_hours = delta.total_seconds() / 3600
        if age_hours > args.max_age_hours:
            print("latest run too old", file=sys.stderr)
            return 1

        arts_resp = _request(session, "GET", run["artifacts_url"])
        artifacts = arts_resp.json().get("artifacts", [])
        target = None
        for art in artifacts:
            if fnmatch.fnmatch(f"{art['name']}.img.xz", args.artifact_pattern):
                target = art
                break
        if not target:
            print("no artifact matched pattern", file=sys.stderr)
            return 1

        download_resp = _request(
            session, "GET", target["archive_download_url"], stream=True
        )
        zf = zipfile.ZipFile(io.BytesIO(download_resp.content))
        img_name = None
        sha_file = None
        for name in zf.namelist():
            if name.endswith(".img.xz") and fnmatch.fnmatch(
                name, args.artifact_pattern
            ):
                img_name = name
            elif name.endswith(".sha256"):
                sha_file = name
        if not img_name or not sha_file:
            print("artifact missing image or checksum", file=sys.stderr)
            return 1
        zf.extract(img_name)
        zf.extract(sha_file)
        with open(img_name, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        with open(sha_file, "r", encoding="utf-8") as f:
            recorded = f.read().split()[0]
        if digest != recorded:
            print("checksum mismatch", file=sys.stderr)
            return 1
        print(f"{img_name} {digest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
