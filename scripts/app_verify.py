#!/usr/bin/env python3
"""Run Sugarkube app HTTP verification checks with operator-friendly output."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

DEFAULT_PREVIEW_BYTES = 4000
DEFAULT_PREVIEW_LINES = 40


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def split_paths(raw_paths: str) -> list[str]:
    paths = []
    for raw in (raw_paths or "/").split(","):
        path = raw.strip() or "/"
        if not path.startswith("/"):
            path = f"/{path}"
        paths.append(path)
    return paths or ["/"]


def base_url(host: str) -> str:
    host = host.strip().rstrip("/")
    if host.startswith(("http://", "https://")):
        return host
    return f"https://{host}"


def preview_body(body: bytes, byte_limit: int, line_limit: int) -> tuple[str, bool]:
    limited = body[:byte_limit]
    truncated = len(body) > byte_limit
    text = limited.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > line_limit:
        text = "\n".join(lines[:line_limit])
        truncated = True
    return text, truncated


def print_body(body: bytes, *, ok: bool) -> None:
    if not truthy(os.environ.get("SUGARKUBE_APP_VERIFY_SHOW_BODY", "1")):
        return
    try:
        byte_limit = int(
            os.environ.get("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES", DEFAULT_PREVIEW_BYTES)
        )
    except ValueError:
        byte_limit = DEFAULT_PREVIEW_BYTES
    try:
        line_limit = int(
            os.environ.get("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_LINES", DEFAULT_PREVIEW_LINES)
        )
    except ValueError:
        line_limit = DEFAULT_PREVIEW_LINES
    byte_limit = max(0, byte_limit)
    line_limit = max(0, line_limit)
    text, truncated = preview_body(body, byte_limit, line_limit)
    label = "Body preview:" if truncated else "Body:"
    print(f"  {label}")
    if text:
        for line in text.splitlines() or [text]:
            print(f"  {line}")
    else:
        print("  (empty)")
    if truncated:
        print("  ...")
    # Keep a visual break after even empty failure bodies.
    if not ok and not text and not truncated:
        return


def curl_check(url: str) -> tuple[int, str, bytes, str]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = Path(body_file.name)
    try:
        command = ["curl", "-sS", "-L", "-o", str(body_path), "-w", "%{http_code}", url]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        body = body_path.read_bytes() if body_path.exists() else b""
        return completed.returncode, completed.stdout.strip(), body, completed.stderr.strip()
    finally:
        try:
            body_path.unlink()
        except FileNotFoundError:
            pass


def is_http_success(http_status: str) -> bool:
    try:
        code = int(http_status)
    except ValueError:
        return False
    return 200 <= code < 400


def shell_quote_url(url: str) -> str:
    # Verification URLs come from public host/path config. Keep old readable output for normal URLs,
    # but quote defensively if an unusual character appears.
    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    safe_chars += "-._~:/?#[]@!$&'()*+,;=%<>"
    safe = set(safe_chars)
    if all(ch in safe for ch in url):
        return url
    return "'" + url.replace("'", "'\\''") + "'"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--paths", default="/")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    paths = split_paths(args.paths)
    root = base_url(args.host)
    urls = [(path, f"{root}{path}") for path in paths]

    if args.print_only:
        for _, url in urls:
            print(f"curl -fsS {shell_quote_url(url)}")
        return 0

    print(f"Verifying {args.app} env={args.env}")
    print(f"Host: {root}")

    failures: list[str] = []
    total = len(urls)
    for index, (path, url) in enumerate(urls, start=1):
        print()
        print(f"[{index}/{total}] GET {path}")
        print(f"  URL: {url}")
        curl_exit, http_status, body, stderr = curl_check(url)
        ok = curl_exit == 0 and is_http_success(http_status)
        print(f"  Status: {'OK' if ok else 'FAILED'}")
        if http_status:
            print(f"  HTTP status: {http_status}")
        if not ok:
            print(f"  curl exit status: {curl_exit}")
            if stderr:
                print("  curl stderr:")
                for line in stderr.splitlines():
                    print(f"  {line}")
            failures.append(path)
        print_body(body, ok=ok)

    print()
    passed = total - len(failures)
    if failures:
        print(f"Verification failed: {passed}/{total} checks succeeded.")
        print("Failing paths: " + ", ".join(failures))
        return 1
    print(f"Verification passed: {total}/{total} checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
