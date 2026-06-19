#!/usr/bin/env python3
"""Verify an app-owned public CORS contract for a Sugarkube app."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from app_verify import base_url_from_host, discover_host, env_flag, int_env, normalize_path
except ModuleNotFoundError:  # pragma: no cover - package import path used by pytest
    from scripts.app_verify import (
        base_url_from_host,
        discover_host,
        env_flag,
        int_env,
        normalize_path,
    )

DEFAULT_ORIGIN = "https://cors-smoke.invalid"


def csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_headers(raw: bytes) -> dict[str, list[str]]:
    blocks = [
        block
        for block in raw.decode("iso-8859-1", errors="replace").replace("\r\n", "\n").split("\n\n")
        if block.strip()
    ]
    lines = [
        line.strip("\r") for line in (blocks[-1] if blocks else "").split("\n") if line.strip("\r")
    ]
    headers: dict[str, list[str]] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers.setdefault(name.strip().lower(), []).append(value.strip())
    return headers


def single_header(headers: dict[str, list[str]], name: str) -> str | None:
    values = headers.get(name.lower(), [])
    if len(values) != 1:
        return None
    return values[0]


def tokens(value: str) -> set[str]:
    return {part.strip().lower() for part in value.split(",") if part.strip()}


def require_wildcard(headers: dict[str, list[str]], origin: str) -> str:
    values = headers.get("access-control-allow-origin", [])
    if len(values) != 1:
        return "Access-Control-Allow-Origin must be present exactly once with literal '*'."
    value = values[0].strip()
    if value == origin:
        return "Access-Control-Allow-Origin echoes the supplied Origin instead of literal '*'."
    if value != "*":
        return "Access-Control-Allow-Origin must be literal '*'."
    return ""


def require_no_credentials(headers: dict[str, list[str]]) -> str:
    value = single_header(headers, "Access-Control-Allow-Credentials")
    if value is not None and value.strip().lower() == "true":
        return "Access-Control-Allow-Credentials must be absent or not true."
    return ""


def run_curl(args: list[str]) -> tuple[int, str, bytes, bytes, str]:
    with tempfile.NamedTemporaryFile(delete=False) as body_tmp, tempfile.NamedTemporaryFile(
        delete=False
    ) as header_tmp:
        body_path = Path(body_tmp.name)
        header_path = Path(header_tmp.name)
    try:
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "--connect-timeout",
                str(int_env("SUGARKUBE_APP_VERIFY_CURL_CONNECT_TIMEOUT", 10)),
                "--max-time",
                str(int_env("SUGARKUBE_APP_VERIFY_CURL_MAX_TIME", 30)),
                "-D",
                str(header_path),
                "-o",
                str(body_path),
                "-w",
                "%{http_code}",
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return (
            proc.returncode,
            proc.stdout.strip() or "000",
            header_path.read_bytes() if header_path.exists() else b"",
            body_path.read_bytes() if body_path.exists() else b"",
            proc.stderr.strip(),
        )
    finally:
        body_path.unlink(missing_ok=True)
        header_path.unlink(missing_ok=True)


def shell_cmd(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in ["curl", *args])


def fail(msg: str, *, app: str, env: str, host: str, path: str, origin: str, status: str) -> int:
    print(f"CORS verification failed for app={app} env={env}", file=sys.stderr)
    print(f"Host: {host or '<unresolved>'}", file=sys.stderr)
    print(f"Path: {path}", file=sys.stderr)
    print(f"Origin: {origin}", file=sys.stderr)
    print(f"HTTP status: {status}", file=sys.stderr)
    print(msg, file=sys.stderr)
    print("Suggested next steps:", file=sys.stderr)
    print(f"  just app-status app={app} env={env}", file=sys.stderr)
    print(f"  just app-verify app={app} env={env}", file=sys.stderr)
    print(
        "  Check that the intended immutable image tag containing the API CORS fix was deployed.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    app = os.environ["SUGARKUBE_APP"]
    env = os.environ["SUGARKUBE_ENV"]
    path = normalize_path(os.environ.get("SUGARKUBE_CORS_VERIFY_PATH", "/"))
    method = os.environ.get("SUGARKUBE_CORS_VERIFY_METHOD", "POST").upper()
    req_headers = os.environ.get("SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS", "content-type")
    body = os.environ.get("SUGARKUBE_CORS_VERIFY_BODY", "{}")
    expected = {
        int(item)
        for item in csv(os.environ.get("SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES", "400,429"))
    }
    print_only = args.print_only or env_flag("SUGARKUBE_APP_CORS_VERIFY_PRINT_ONLY")
    kube_context = f"sugar-{env}"

    host, errors = discover_host(kube_context)
    base = base_url_from_host(host)
    if not base:
        if print_only:
            placeholder = "https://<host>"
            path_url = f"{placeholder}{path}"
            preflight_args = [
                "-X",
                "OPTIONS",
                "-H",
                f"Origin: {args.origin}",
                "-H",
                f"Access-Control-Request-Method: {method}",
                "-H",
                f"Access-Control-Request-Headers: {req_headers}",
                path_url,
            ]
            actual_args = [
                "-X",
                method,
                "-H",
                f"Origin: {args.origin}",
                "-H",
                "Content-Type: application/json",
                "--data",
                body,
                path_url,
            ]
            for error in errors:
                print(error, file=sys.stderr)
            print(
                "Could not derive a public host; generated placeholder CORS commands.",
                file=sys.stderr,
            )
            print(shell_cmd(preflight_args))
            print(shell_cmd(actual_args))
            return 0
        for error in errors:
            print(error, file=sys.stderr)
        return fail(
            "Could not derive a public host.",
            app=app,
            env=env,
            host=host,
            path=path,
            origin=args.origin,
            status="000",
        )
    url = f"{base}{path}"

    preflight_args = [
        "-X",
        "OPTIONS",
        "-H",
        f"Origin: {args.origin}",
        "-H",
        f"Access-Control-Request-Method: {method}",
        "-H",
        f"Access-Control-Request-Headers: {req_headers}",
        url,
    ]
    actual_args = [
        "-X",
        method,
        "-H",
        f"Origin: {args.origin}",
        "-H",
        "Content-Type: application/json",
        "--data",
        body,
        url,
    ]
    if print_only:
        print(shell_cmd(preflight_args))
        print(shell_cmd(actual_args))
        return 0

    print(f"Verifying CORS for {app} env={env}")
    print(f"Host: {base}")
    print(f"Path: {path}")
    print(f"Origin: {args.origin}")

    rc, status, raw_headers, _body, stderr = run_curl(preflight_args)
    if rc != 0 or not status.isdigit() or not (200 <= int(status) < 300):
        return fail(
            f"Preflight OPTIONS must return a successful HTTP status. {stderr}".strip(),
            app=app,
            env=env,
            host=base,
            path=path,
            origin=args.origin,
            status=status,
        )
    headers = parse_headers(raw_headers)
    for msg in [require_wildcard(headers, args.origin), require_no_credentials(headers)]:
        if msg:
            return fail(
                msg, app=app, env=env, host=base, path=path, origin=args.origin, status=status
            )
    methods = single_header(headers, "Access-Control-Allow-Methods")
    if not methods or method.lower() not in tokens(methods):
        return fail(
            f"Access-Control-Allow-Methods must contain {method}.",
            app=app,
            env=env,
            host=base,
            path=path,
            origin=args.origin,
            status=status,
        )
    allowed_headers = single_header(headers, "Access-Control-Allow-Headers")
    for required in csv(req_headers):
        if not allowed_headers or required.lower() not in tokens(allowed_headers):
            return fail(
                f"Access-Control-Allow-Headers must contain {required.lower()}.",
                app=app,
                env=env,
                host=base,
                path=path,
                origin=args.origin,
                status=status,
            )

    rc, status, raw_headers, body_bytes, stderr = run_curl(actual_args)
    if not status.isdigit() or int(status) not in expected:
        return fail(
            f"Actual response must be one of {sorted(expected)} and not redirects, 403, 404, 405, or 5xx. {stderr}".strip(),
            app=app,
            env=env,
            host=base,
            path=path,
            origin=args.origin,
            status=status,
        )
    headers = parse_headers(raw_headers)
    for msg in [require_wildcard(headers, args.origin), require_no_credentials(headers)]:
        if msg:
            return fail(
                msg, app=app, env=env, host=base, path=path, origin=args.origin, status=status
            )
    if app == "tokenplace":
        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return fail(
                "token.place actual response must be JSON.",
                app=app,
                env=env,
                host=base,
                path=path,
                origin=args.origin,
                status=status,
            )
        if not isinstance(data, dict) or not isinstance(data.get("error"), dict):
            return fail(
                "token.place actual response must include a top-level API error object.",
                app=app,
                env=env,
                host=base,
                path=path,
                origin=args.origin,
                status=status,
            )
    print(
        "CORS verification passed: preflight and actual response use literal wildcard CORS without credentials."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
