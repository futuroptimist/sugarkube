#!/usr/bin/env python3
"""Run generic Sugarkube app HTTP verification checks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def normalize_path(path: str) -> str:
    path = "".join(path.split()) or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def discover_host(kube_context: str) -> tuple[str, list[str]]:
    errors: list[str] = []
    release = os.environ["SUGARKUBE_RELEASE"]
    namespace = os.environ["SUGARKUBE_NAMESPACE"]
    host_key = os.environ.get("SUGARKUBE_STATUS_HOST_KEY", "ingress.host")

    if shutil_which("helm"):
        helm = run_capture(
            [
                "helm",
                "--kube-context",
                kube_context,
                "get",
                "values",
                release,
                "--namespace",
                namespace,
                "--all",
                "--output",
                "json",
            ]
        )
        if helm.returncode == 0:
            host = host_from_values(helm.stdout, host_key)
            if host:
                return host, errors
        else:
            errors.append(
                f"helm get values failed for context {kube_context}: {helm.stderr.replace(chr(10), ' ').strip()}"
            )

    if shutil_which("kubectl"):
        kubectl = run_capture(
            [
                "kubectl",
                "--context",
                kube_context,
                "-n",
                namespace,
                "get",
                "ingress",
                "-o",
                "jsonpath={.items[0].spec.rules[0].host}",
            ]
        )
        if kubectl.returncode == 0 and kubectl.stdout.strip():
            return kubectl.stdout.strip(), errors
        if kubectl.returncode != 0:
            errors.append(
                f"kubectl ingress lookup failed for context {kube_context}: {kubectl.stderr.replace(chr(10), ' ').strip()}"
            )
    return "", errors


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def host_from_values(raw: str, host_key: str) -> str:
    try:
        node: object = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    for part in host_key.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(part)
    return str(node) if node else ""


def base_url_from_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host:
        return ""
    if host.startswith("https://"):
        return host
    if host.startswith("http://"):
        host = host[len("http://") :]
    return f"https://{host}"


def print_placeholder_failure(
    app: str, env: str, kube_context: str, paths: list[str], errors: list[str]
) -> None:
    print(f"Could not derive a host for {app} using context {kube_context}.", file=sys.stderr)
    for error in errors:
        print(error, file=sys.stderr)
    print(
        f"Suggested next steps: just app-status app={app} env={env} or just app-config app={app} env={env}.",
        file=sys.stderr,
    )
    print("Generated verification commands with a placeholder host:", file=sys.stderr)
    for path in paths:
        print(f"  curl -fsS https://<host>{path}")


def preview_text(body: bytes, byte_limit: int, line_limit: int) -> tuple[list[str], bool]:
    truncated = False
    if byte_limit > 0 and len(body) > byte_limit:
        body = body[:byte_limit]
        truncated = True
    text = body.decode("utf-8", errors="replace")
    lines = text.splitlines() or ([text] if text else [])
    if line_limit > 0 and len(lines) > line_limit:
        lines = lines[:line_limit]
        truncated = True
    return lines, truncated


def int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def run_curl(url: str) -> tuple[int, str, bytes, str]:
    connect_timeout = int_env("SUGARKUBE_APP_VERIFY_CURL_CONNECT_TIMEOUT", 10)
    max_time = int_env("SUGARKUBE_APP_VERIFY_CURL_MAX_TIME", 30)
    with tempfile.NamedTemporaryFile(delete=False) as body_tmp:
        body_path = Path(body_tmp.name)
    try:
        curl = subprocess.run(
            [
                "curl",
                "-sS",
                "--connect-timeout",
                str(connect_timeout),
                "--max-time",
                str(max_time),
                "-o",
                str(body_path),
                "-w",
                "%{http_code}",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        body = body_path.read_bytes() if body_path.exists() else b""
        return curl.returncode, curl.stdout.strip() or "000", body, curl.stderr.strip()
    finally:
        body_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    app = os.environ["SUGARKUBE_APP"]
    env = os.environ["SUGARKUBE_ENV"]
    kube_context = f"sugar-{env}"
    paths = [
        normalize_path(path) for path in os.environ.get("SUGARKUBE_VERIFY_PATHS", "/").split(",")
    ]
    if app == "tokenplace" and env in {"staging", "prod"} and "/api/v1/meta" not in paths:
        paths.append("/api/v1/meta")
    print_only = args.print_only or env_flag("SUGARKUBE_APP_VERIFY_PRINT_ONLY")

    host, errors = discover_host(kube_context)
    base_url = base_url_from_host(host)
    if not base_url:
        print_placeholder_failure(app, env, kube_context, paths, errors)
        return 0 if print_only else 1

    if print_only:
        for path in paths:
            print(f"curl -fsS {base_url}{path}")
        return 0

    print(f"Verifying {app} env={env}")
    print(f"Host: {base_url}")

    show_body = env_flag("SUGARKUBE_APP_VERIFY_SHOW_BODY", default=True)
    byte_limit = int_env("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES", 4000)
    line_limit = int_env("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_LINES", 40)
    passed = 0
    failures: list[tuple[str, str]] = []
    total = len(paths)

    for index, path in enumerate(paths, start=1):
        url = f"{base_url}{path}"
        curl_rc, http_status, body, curl_stderr = run_curl(url)
        if curl_rc == 0 and http_status.isdigit() and int(http_status) >= 400:
            curl_rc = 22

        print(f"\n[{index}/{total}] GET {path}")
        print(f"  URL: {url}")
        http_suffix = (
            f" (HTTP {http_status})" if http_status.isdigit() and http_status != "000" else ""
        )
        if curl_rc == 0:
            print(f"  Status: OK{http_suffix}")
            if app == "tokenplace" and path == "/api/v1/meta":
                try:
                    meta = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    meta = {}
                label = str(meta.get("label", ""))
                version = str(meta.get("version", ""))
                if version == "dev" or label.endswith(" dev"):
                    print("  token.place metadata warning: deployment still reports dev metadata.")
                    print("  Expected staging labels to include the immutable image tag; prod should use a finalized release version.")
            passed += 1
        else:
            print(f"  Status: FAILED{http_suffix}")
            print(f"  curl exit status: {curl_rc}")
            if curl_stderr:
                print("  curl stderr:")
                for line in curl_stderr.splitlines():
                    print(f"  {line}")
            failures.append((path, url))

        if show_body:
            if body:
                lines, truncated = preview_text(body, byte_limit, line_limit)
                print("  Body preview:" if truncated else "  Body:")
                for line in lines:
                    print(f"  {line}")
                if truncated:
                    print("  ...")
            else:
                print("  Body: <empty>")

    if not failures:
        print(f"\nVerification passed: {passed}/{total} checks succeeded.")
        return 0

    print(f"\nVerification failed: {len(failures)}/{total} checks failed.", file=sys.stderr)
    print("Failed paths:", file=sys.stderr)
    for path, url in failures:
        print(f"  {path} ({url})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
