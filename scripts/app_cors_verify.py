#!/usr/bin/env python3
"""Verify an app-owned public CORS contract for a Sugarkube app."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app_verify import base_url_from_host, discover_host, env_flag, int_env, normalize_path

DEFAULT_ORIGIN = "https://cors-smoke.invalid"


def csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def curl_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def headers_from_bytes(raw: bytes) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    text = raw.decode("iso-8859-1", errors="replace").replace("\r\n", "\n")
    blocks = [block for block in text.split("\n\n") if block.strip()]
    block = blocks[-1] if blocks else text
    for line in block.split("\n"):
        if not line or line.lower().startswith("http/") or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers.setdefault(name.strip().lower(), []).append(value.strip())
    return headers


def single_header(headers: dict[str, list[str]], name: str) -> tuple[str, str]:
    values = headers.get(name.lower(), [])
    if not values:
        return "", f"missing {name}"
    normalized = {value.strip() for value in values}
    if len(values) != 1 or len(normalized) != 1:
        return "", f"duplicated/conflicting {name}: {values}"
    return values[0].strip(), ""


def contains_header_value(headers: dict[str, list[str]], name: str, expected: str) -> bool:
    wanted = expected.lower()
    for value in headers.get(name.lower(), []):
        if any(part.strip().lower() == wanted for part in value.split(",")):
            return True
    return False


def credentials_enabled(headers: dict[str, list[str]]) -> bool:
    return any(
        v.strip().lower() == "true" for v in headers.get("access-control-allow-credentials", [])
    )


def run_curl(args: list[str]) -> tuple[int, str, dict[str, list[str]], bytes, str]:
    connect_timeout = int_env("SUGARKUBE_APP_VERIFY_CURL_CONNECT_TIMEOUT", 10)
    max_time = int_env("SUGARKUBE_APP_VERIFY_CURL_MAX_TIME", 30)
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
                str(connect_timeout),
                "--max-time",
                str(max_time),
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
        body = body_path.read_bytes() if body_path.exists() else b""
        headers = headers_from_bytes(header_path.read_bytes() if header_path.exists() else b"")
        return proc.returncode, proc.stdout.strip() or "000", headers, body, proc.stderr.strip()
    finally:
        body_path.unlink(missing_ok=True)
        header_path.unlink(missing_ok=True)


def print_failure_context(
    app: str, env: str, host: str, path: str, origin: str, status: str, detail: str
) -> None:
    print("CORS verification failed.", file=sys.stderr)
    print(
        f"app={app} env={env} host={host or '<unknown>'} path={path} origin={origin} status={status}",
        file=sys.stderr,
    )
    print(f"incorrect header/status: {detail}", file=sys.stderr)
    print(f"Suggested next steps: just app-status app={app} env={env}", file=sys.stderr)
    print(f"Suggested next steps: just app-verify app={app} env={env}", file=sys.stderr)
    print(
        "Check that the intended immutable image tag containing the app-owned CORS fix was deployed.",
        file=sys.stderr,
    )


def assert_wildcard(headers: dict[str, list[str]], origin: str) -> str:
    acao, error = single_header(headers, "Access-Control-Allow-Origin")
    if error:
        return error
    if acao != "*":
        if acao == origin:
            return "Access-Control-Allow-Origin echoed the test Origin instead of literal *"
        return f"Access-Control-Allow-Origin must be literal *, got {acao!r}"
    if credentials_enabled(headers):
        return "Access-Control-Allow-Credentials must be absent or not true"
    return ""


def tokenplace_api_error(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "token.place API error response must be JSON"
    if not isinstance(data, dict) or not isinstance(data.get("error"), dict):
        return "token.place API error response must include a top-level error object"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origin", default=os.environ.get("SUGARKUBE_CORS_VERIFY_ORIGIN", DEFAULT_ORIGIN)
    )
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    app = os.environ["SUGARKUBE_APP"]
    env = os.environ["SUGARKUBE_ENV"]
    kube_context = f"sugar-{env}"
    path = normalize_path(os.environ.get("SUGARKUBE_CORS_VERIFY_PATH", "/"))
    method = os.environ.get("SUGARKUBE_CORS_VERIFY_METHOD", "POST").upper()
    request_headers = os.environ.get("SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS", "content-type")
    body = os.environ.get("SUGARKUBE_CORS_VERIFY_BODY", "{}")
    expected_statuses = {
        int(v) for v in csv(os.environ.get("SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES", "400,429"))
    }
    print_only = args.print_only or env_flag("SUGARKUBE_CORS_VERIFY_PRINT_ONLY")

    host, errors = discover_host(kube_context)
    base_url = base_url_from_host(host)
    url = f"{base_url or 'https://<host>'}{path}"

    preflight_args = [
        "-X",
        "OPTIONS",
        "-H",
        f"Origin: {args.origin}",
        "-H",
        f"Access-Control-Request-Method: {method}",
        "-H",
        f"Access-Control-Request-Headers: {request_headers}",
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
        if not base_url:
            for error in errors:
                print(error, file=sys.stderr)
            print(
                "Could not derive a host; generated commands use https://<host>.", file=sys.stderr
            )
        print("curl -i -sS " + " ".join(curl_quote(v) for v in preflight_args))
        print("curl -i -sS " + " ".join(curl_quote(v) for v in actual_args))
        return 0

    if not base_url:
        for error in errors:
            print(error, file=sys.stderr)
        print_failure_context(
            app, env, host, path, args.origin, "000", "could not derive public host"
        )
        return 1

    print(f"Verifying CORS for {app} env={env}")
    print(f"Host: {base_url}")
    print(f"Path: {path}")
    print(f"Origin: {args.origin}")

    rc, status, headers, _body, stderr = run_curl(preflight_args)
    if rc != 0 and status == "000":
        print_failure_context(
            app, env, base_url, path, args.origin, status, stderr or "network request failed"
        )
        return 1
    if not status.isdigit() or not (200 <= int(status) < 300):
        print_failure_context(
            app,
            env,
            base_url,
            path,
            args.origin,
            status,
            "preflight HTTP status must be successful",
        )
        return 1
    error = assert_wildcard(headers, args.origin)
    if not error and not contains_header_value(headers, "Access-Control-Allow-Methods", method):
        error = f"Access-Control-Allow-Methods must contain {method}"
    for header in csv(request_headers):
        if not error and not contains_header_value(headers, "Access-Control-Allow-Headers", header):
            error = f"Access-Control-Allow-Headers must contain {header}"
    if error:
        print_failure_context(app, env, base_url, path, args.origin, status, error)
        return 1

    rc, status, headers, actual_body, stderr = run_curl(actual_args)
    if rc != 0 and status == "000":
        print_failure_context(
            app, env, base_url, path, args.origin, status, stderr or "network request failed"
        )
        return 1
    status_int = int(status) if status.isdigit() else 0
    if status_int not in expected_statuses:
        print_failure_context(
            app,
            env,
            base_url,
            path,
            args.origin,
            status,
            f"actual status must be one of {sorted(expected_statuses)}",
        )
        return 1
    error = assert_wildcard(headers, args.origin)
    if not error and app == "tokenplace":
        error = tokenplace_api_error(actual_body)
    if error:
        print_failure_context(app, env, base_url, path, args.origin, status, error)
        return 1

    print(
        "CORS verification passed: preflight and actual API error response expose literal wildcard CORS without credentials."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
