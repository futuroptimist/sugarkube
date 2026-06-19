#!/usr/bin/env python3
"""Verify a Sugarkube app public API CORS contract without mutating cluster state."""

from __future__ import annotations

import argparse, json, os, shlex, subprocess, sys, tempfile
from pathlib import Path

try:
    from app_verify import base_url_from_host, discover_host, env_flag, int_env, normalize_path
except ModuleNotFoundError:
    from scripts.app_verify import (
        base_url_from_host,
        discover_host,
        env_flag,
        int_env,
        normalize_path,
    )

DEFAULT_ORIGIN = "https://cors-smoke.invalid"


def split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_headers(raw: bytes) -> dict[str, list[str]]:
    text = raw.decode("iso-8859-1", errors="replace").replace("\r\n", "\n")
    blocks = [b for b in text.split("\n\n") if b.strip()]
    block = blocks[-1] if blocks else text
    headers: dict[str, list[str]] = {}
    for line in block.split("\n"):
        if ":" not in line or line.lower().startswith("http/"):
            continue
        name, value = line.split(":", 1)
        headers.setdefault(name.strip().lower(), []).append(value.strip())
    return headers


def header_single(headers: dict[str, list[str]], name: str) -> str:
    values = headers.get(name.lower(), [])
    return values[0] if len(values) == 1 else ""


def contains_header_item(value: str, item: str) -> bool:
    return item.lower() in {part.strip().lower() for part in value.split(",")}


def validate_preflight(
    headers: dict[str, list[str]], method: str, req_headers: list[str], origin: str
) -> str:
    acao_values = headers.get("access-control-allow-origin", [])
    if len(acao_values) != 1 or acao_values[0] != "*":
        if acao_values == [origin]:
            return "Access-Control-Allow-Origin echoes the test Origin; expected literal *."
        return "Access-Control-Allow-Origin must appear exactly once with literal *."
    if headers.get("access-control-allow-credentials", [""])[0].lower() == "true":
        return "Access-Control-Allow-Credentials must be absent or not true."
    methods = header_single(headers, "access-control-allow-methods")
    if not contains_header_item(methods, method):
        return f"Access-Control-Allow-Methods must contain {method}."
    allowed = header_single(headers, "access-control-allow-headers")
    for item in req_headers:
        if not contains_header_item(allowed, item):
            return f"Access-Control-Allow-Headers must contain {item}."
    return ""


def validate_actual(
    app: str, status: str, headers: dict[str, list[str]], body: bytes, expected: set[int]
) -> str:
    if status == "000" or not status.isdigit():
        return f"actual response returned network HTTP status {status}."
    code = int(status)
    if code not in expected:
        return f"actual response HTTP status {status} is not one of {sorted(expected)}."
    acao_values = headers.get("access-control-allow-origin", [])
    if len(acao_values) != 1 or acao_values[0] != "*":
        return (
            "actual response Access-Control-Allow-Origin must appear exactly once with literal *."
        )
    if headers.get("access-control-allow-credentials", [""])[0].lower() == "true":
        return "actual response Access-Control-Allow-Credentials must be absent or not true."
    if app == "tokenplace":
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return "token.place actual error response must be JSON."
        if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
            return "token.place actual response must include a top-level API error object."
    return ""


def run_curl(args: list[str]) -> tuple[int, str, bytes, bytes, str]:
    with tempfile.NamedTemporaryFile(delete=False) as hp, tempfile.NamedTemporaryFile(
        delete=False
    ) as bp:
        header_path, body_path = Path(hp.name), Path(bp.name)
    try:
        cmd = [
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
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return (
            proc.returncode,
            proc.stdout.strip() or "000",
            header_path.read_bytes(),
            body_path.read_bytes(),
            proc.stderr.strip(),
        )
    finally:
        header_path.unlink(missing_ok=True)
        body_path.unlink(missing_ok=True)


def print_failure(app, env, host, path, origin, status, detail):
    print(f"CORS verification failed for app={app} env={env}", file=sys.stderr)
    print(f"host={host} path={path} origin={origin} http_status={status}", file=sys.stderr)
    print(f"missing/incorrect header: {detail}", file=sys.stderr)
    print(
        f"Suggested next steps: just app-status app={app} env={env}; just app-verify app={app} env={env}; check that the intended immutable image tag containing the app-owned CORS fix was deployed.",
        file=sys.stderr,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--origin", default="")
    ap.add_argument("--print-only", action="store_true")
    ns = ap.parse_args(argv)
    app = os.environ["SUGARKUBE_APP"]
    env = os.environ["SUGARKUBE_ENV"]
    kube_context = f"sugar-{env}"
    path = normalize_path(os.environ.get("SUGARKUBE_CORS_VERIFY_PATH", "/"))
    method = os.environ.get("SUGARKUBE_CORS_VERIFY_METHOD", "POST").upper()
    req_headers = split_csv(os.environ.get("SUGARKUBE_CORS_VERIFY_REQUEST_HEADERS", "content-type"))
    body = os.environ.get("SUGARKUBE_CORS_VERIFY_BODY", "{}")
    expected = {
        int(x)
        for x in split_csv(os.environ.get("SUGARKUBE_CORS_VERIFY_EXPECTED_STATUSES", "400,429"))
    }
    origin = ns.origin or os.environ.get("SUGARKUBE_CORS_VERIFY_ORIGIN") or DEFAULT_ORIGIN
    print_only = ns.print_only or env_flag("SUGARKUBE_APP_CORS_VERIFY_PRINT_ONLY")
    host, errors = discover_host(kube_context)
    base = base_url_from_host(host)
    url = f"{base}{path}" if base else f"https://<host>{path}"
    pre = [
        "-X",
        "OPTIONS",
        "-H",
        f"Origin: {origin}",
        "-H",
        f"Access-Control-Request-Method: {method}",
        "-H",
        f"Access-Control-Request-Headers: {','.join(req_headers)}",
        url,
    ]
    actual = [
        "-X",
        method,
        "-H",
        f"Origin: {origin}",
        "-H",
        "Content-Type: application/json",
        "--data",
        body,
        url,
    ]
    if print_only:
        print("curl " + " ".join(shlex.quote(x) for x in pre))
        print("curl " + " ".join(shlex.quote(x) for x in actual))
        return 0
    if not base:
        print_failure(
            app,
            env,
            "<unresolved>",
            path,
            origin,
            "000",
            "; ".join(errors) or "host discovery failed",
        )
        return 1
    rc, status, h, b, err = run_curl(pre)
    if rc != 0 or not status.isdigit() or int(status) < 200 or int(status) >= 300:
        print_failure(
            app, env, base, path, origin, status, err or "preflight HTTP status must be 2xx"
        )
        return 1
    detail = validate_preflight(parse_headers(h), method, req_headers, origin)
    if detail:
        print_failure(app, env, base, path, origin, status, detail)
        return 1
    rc, status, h, b, err = run_curl(actual)
    detail = (
        err
        if rc and status == "000"
        else validate_actual(app, status, parse_headers(h), b, expected)
    )
    if detail:
        print_failure(app, env, base, path, origin, status, detail)
        return 1
    print(f"CORS verification passed for {app} env={env} host={base} path={path} origin={origin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
