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

try:
    from app_verify import base_url_from_host, discover_host, env_flag, normalize_path
except ModuleNotFoundError:  # pragma: no cover - package import for tests
    from scripts.app_verify import base_url_from_host, discover_host, env_flag, normalize_path

DEFAULT_ORIGIN = "https://cors-smoke.invalid"


def csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def curl_common() -> list[str]:
    return [
        "curl",
        "-sS",
        "--connect-timeout",
        os.environ.get("SUGARKUBE_APP_VERIFY_CURL_CONNECT_TIMEOUT", "10"),
        "--max-time",
        os.environ.get("SUGARKUBE_APP_VERIFY_CURL_MAX_TIME", "30"),
    ]


def shell_join(args: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(arg) for arg in args)


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


def header_tokens(value: str) -> set[str]:
    return {part.strip().lower() for part in value.split(",") if part.strip()}


def cors_failure(
    headers: dict[str, list[str]], origin: str, *, method: str | None, req_headers: list[str] | None
) -> str:
    acao = single_header(headers, "access-control-allow-origin")
    if acao != "*":
        values = headers.get("access-control-allow-origin", [])
        if not values:
            return "missing Access-Control-Allow-Origin: *"
        if origin in values:
            return "Access-Control-Allow-Origin echoes the test Origin instead of literal *"
        return f"malformed or conflicting Access-Control-Allow-Origin values: {values!r}"
    creds = single_header(headers, "access-control-allow-credentials")
    if creds is not None and creds.lower() == "true":
        return "Access-Control-Allow-Credentials must be absent or not true"
    if method:
        allow_methods = single_header(headers, "access-control-allow-methods")
        if allow_methods is None or method.lower() not in header_tokens(allow_methods):
            return f"Access-Control-Allow-Methods must contain {method}"
    if req_headers:
        allow_headers = single_header(headers, "access-control-allow-headers")
        tokens = header_tokens(allow_headers or "")
        missing = [h for h in req_headers if h.lower() not in tokens]
        if missing:
            return "Access-Control-Allow-Headers must contain " + ", ".join(missing)
    return ""


def run_curl(args: list[str]) -> tuple[int, str, bytes, bytes, str]:
    with tempfile.NamedTemporaryFile(delete=False) as body_tmp, tempfile.NamedTemporaryFile(
        delete=False
    ) as headers_tmp:
        body_path = Path(body_tmp.name)
        headers_path = Path(headers_tmp.name)
    try:
        full = args + ["-D", str(headers_path), "-o", str(body_path), "-w", "%{http_code}"]
        proc = subprocess.run(full, capture_output=True, text=True, check=False)
        return (
            proc.returncode,
            proc.stdout.strip() or "000",
            headers_path.read_bytes(),
            body_path.read_bytes(),
            proc.stderr.strip(),
        )
    finally:
        body_path.unlink(missing_ok=True)
        headers_path.unlink(missing_ok=True)


def top_level_error(body: bytes) -> bool:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and isinstance(data.get("error"), dict)


def print_context(
    app: str, env: str, host: str, path: str, origin: str, status: str, problem: str
) -> None:
    print(f"CORS verification failed for app={app} env={env}", file=sys.stderr)
    print(f"Host: {host or '<unresolved>'}", file=sys.stderr)
    print(f"Path: {path}", file=sys.stderr)
    print(f"Origin: {origin}", file=sys.stderr)
    print(f"HTTP status: {status}", file=sys.stderr)
    print(f"Problem: {problem}", file=sys.stderr)
    print("Suggested next steps:", file=sys.stderr)
    print(f"  just app-status app={app} env={env}", file=sys.stderr)
    print(f"  just app-verify app={app} env={env}", file=sys.stderr)
    print(
        "  Check that the intended immutable image tag containing the API CORS fix was deployed.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)
    app = os.environ["SUGARKUBE_APP"]
    env = os.environ["SUGARKUBE_ENV"]
    path = normalize_path(os.environ.get("SUGARKUBE_CORS_VERIFY_PATH", "/"))
    method = os.environ.get("SUGARKUBE_CORS_VERIFY_METHOD", "POST").upper()
    request_headers = csv(os.environ.get("SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS", "content-type"))
    body = os.environ.get("SUGARKUBE_CORS_VERIFY_BODY", "{}")
    expected = {
        int(s)
        for s in csv(os.environ.get("SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES", "400,429"))
        if s.isdigit()
    }
    print_only = args.print_only or env_flag("SUGARKUBE_APP_CORS_VERIFY_PRINT_ONLY")
    kube_context = f"sugar-{env}"
    host, errors = discover_host(kube_context)
    base = base_url_from_host(host)
    url = f"{base}{path}" if base else f"https://<host>{path}"
    preflight = curl_common() + [
        "-X",
        "OPTIONS",
        "-H",
        f"Origin: {args.origin}",
        "-H",
        f"Access-Control-Request-Method: {method}",
        "-H",
        f"Access-Control-Request-Headers: {', '.join(request_headers)}",
        url,
    ]
    actual = curl_common() + [
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
        print(shell_join(preflight))
        print(shell_join(actual))
        return 0
    if not base:
        print_context(
            app,
            env,
            "",
            path,
            args.origin,
            "000",
            "; ".join(errors) or "could not derive public host",
        )
        return 1
    print(f"Verifying CORS for {app} env={env}")
    print(f"Host: {base}")
    rc, status, raw_headers, _body, stderr = run_curl(preflight)
    headers = parse_headers(raw_headers)
    if rc != 0 or not status.isdigit() or not (200 <= int(status) < 300):
        print_context(
            app,
            env,
            host,
            path,
            args.origin,
            status,
            stderr or "preflight HTTP status was not successful",
        )
        return 1
    problem = cors_failure(headers, args.origin, method=method, req_headers=request_headers)
    if problem:
        print_context(app, env, host, path, args.origin, status, problem)
        return 1
    print(f"Preflight OK (HTTP {status})")
    rc, status, raw_headers, body_bytes, stderr = run_curl(actual)
    headers = parse_headers(raw_headers)
    if rc != 0 and status == "000":
        print_context(app, env, host, path, args.origin, status, stderr or "network failure")
        return 1
    if not status.isdigit() or int(status) not in expected:
        print_context(
            app,
            env,
            host,
            path,
            args.origin,
            status,
            f"actual response must be one of {sorted(expected)}",
        )
        return 1
    problem = cors_failure(headers, args.origin, method=None, req_headers=None)
    if problem:
        print_context(app, env, host, path, args.origin, status, problem)
        return 1
    if app == "tokenplace" and not top_level_error(body_bytes):
        print_context(
            app,
            env,
            host,
            path,
            args.origin,
            status,
            "token.place actual response must be JSON with a top-level error object",
        )
        return 1
    print(f"Actual response OK (HTTP {status})")
    print("CORS verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
