#!/usr/bin/env python3
"""Run public HTTP verification checks for a configured Sugarkube app."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from app_config import AppConfigError, load_config

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _normalize_named(value: str, name: str) -> str:
    value = (value or "").strip()
    prefix = f"{name}="
    while value.startswith(prefix):
        value = value[len(prefix) :].strip()
    return value


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def _is_falsey(value: str) -> bool:
    return value.strip().lower() in FALSE_VALUES


def _parse_paths(raw: str) -> list[str]:
    paths: list[str] = []
    for part in (raw or "/").split(","):
        path = re.sub(r"\s+", "", part)
        if not path:
            continue
        if not path.startswith("/"):
            path = f"/{path}"
        paths.append(path)
    return paths or ["/"]


def _run_text(args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _discover_host(config: dict[str, str], kube_context: str) -> tuple[str, list[str]]:
    errors: list[str] = []
    host = ""

    helm_rc, helm_out, helm_err = _run_text(
        [
            "helm",
            "--kube-context",
            kube_context,
            "get",
            "values",
            config["SUGARKUBE_RELEASE"],
            "--namespace",
            config["SUGARKUBE_NAMESPACE"],
            "--all",
            "--output",
            "json",
        ]
    )
    if helm_rc == 0:
        helper = Path(__file__).with_name("app_config.py")
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "host-value",
                    config.get("SUGARKUBE_STATUS_HOST_KEY", "ingress.host"),
                ],
                input=helm_out,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                host = proc.stdout.strip()
        except OSError as exc:
            errors.append(f"helm host parsing failed for context {kube_context}: {exc}")
    elif helm_rc != 127:
        errors.append(
            f"helm get values failed for context {kube_context}: "
            f"{helm_err.replace(chr(10), ' ').strip()}"
        )

    if host:
        return host, errors

    kubectl_rc, kubectl_out, kubectl_err = _run_text(
        [
            "kubectl",
            "--context",
            kube_context,
            "-n",
            config["SUGARKUBE_NAMESPACE"],
            "get",
            "ingress",
            "-o",
            "jsonpath={.items[0].spec.rules[0].host}",
        ]
    )
    if kubectl_rc == 0:
        host = kubectl_out.strip()
    elif kubectl_rc != 127:
        errors.append(
            f"kubectl ingress lookup failed for context {kube_context}: "
            f"{kubectl_err.replace(chr(10), ' ').strip()}"
        )

    return host, errors


def _print_commands(host: str, paths: list[str]) -> None:
    target = host or "<host>"
    for path in paths:
        print(f"curl -fsS https://{target}{path}")


def _body_preview(path: Path, limit: int) -> tuple[str, bool, bool]:
    data = path.read_bytes() if path.exists() else b""
    if not data:
        return "", False, False
    truncated = len(data) > limit
    preview = data[:limit]
    return preview.decode("utf-8", errors="replace"), truncated, True


def _run_curl(url: str, body_path: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-L", "-o", str(body_path), "-w", "%{http_code}", url],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, "000", str(exc)
    status = proc.stdout.strip() or "000"
    return proc.returncode, status, proc.stderr.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--config", default="")
    parser.add_argument("--print-only", default="")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.app, args.env, args.config or None)
    except AppConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    os.environ.setdefault("KUBECONFIG", str(Path.home() / ".kube" / "config"))
    kube_context = f"sugar-{config['SUGARKUBE_ENV']}"
    paths = _parse_paths(config.get("SUGARKUBE_VERIFY_PATHS", "/"))

    print_only_raw = os.environ.get("SUGARKUBE_APP_VERIFY_PRINT_ONLY", args.print_only)
    print_only_raw = _normalize_named(print_only_raw, "print_only")
    print_only = _is_truthy(print_only_raw)

    show_body_raw = os.environ.get("SUGARKUBE_APP_VERIFY_SHOW_BODY", "1")
    show_body = not _is_falsey(show_body_raw)
    try:
        preview_bytes = int(os.environ.get("SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES", "4000"))
    except ValueError:
        print(
            "ERROR: SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES must be a non-negative integer.",
            file=sys.stderr,
        )
        return 2
    if preview_bytes < 0:
        print(
            "ERROR: SUGARKUBE_APP_VERIFY_BODY_PREVIEW_BYTES must be a non-negative integer.",
            file=sys.stderr,
        )
        return 2

    host, discovery_errors = _discover_host(config, kube_context)
    if not host:
        print(
            f"Could not derive a host for {config['SUGARKUBE_APP']} using context {kube_context}.",
            file=sys.stderr,
        )
        for error in discovery_errors:
            print(error, file=sys.stderr)
        print(
            "Run `just app-status app={app} env={env}` or `just app-config app={app} env={env}` "
            "to inspect deployment details.".format(
                app=config["SUGARKUBE_APP"], env=config["SUGARKUBE_ENV"]
            ),
            file=sys.stderr,
        )
        print("Verification commands after replacing <host>:")
        _print_commands("", paths)
        return 0 if print_only else 1

    if print_only:
        _print_commands(host, paths)
        return 0

    print(f"Verifying {config['SUGARKUBE_APP']} env={config['SUGARKUBE_ENV']}")
    print(f"Host: https://{host}")

    failures: list[str] = []
    passed = 0
    for index, path in enumerate(paths, start=1):
        url = urljoin(f"https://{host}/", path.lstrip("/"))
        print()
        print(f"[{index}/{len(paths)}] GET {path}")
        print(f"  URL: {url}")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            body_path = Path(tmp.name)
        try:
            curl_exit, http_status, curl_error = _run_curl(url, body_path)
            http_ok = http_status.isdigit() and 200 <= int(http_status) < 400
            if curl_exit == 0 and http_ok:
                print(f"  Status: OK (HTTP {http_status})")
                passed += 1
            else:
                print(f"  Status: FAIL (HTTP {http_status or 'unknown'}, curl exit {curl_exit})")
                if curl_error:
                    print(f"  Error: {curl_error.replace(chr(10), ' ')}")
                failures.append(f"{path} ({url})")

            if show_body:
                preview, truncated, has_body = _body_preview(body_path, preview_bytes)
                if not has_body:
                    print("  Body: <empty>")
                else:
                    print(f"  {'Body preview' if truncated else 'Body'}:")
                    for line in preview.splitlines() or [""]:
                        print(f"  {line}")
                    if truncated:
                        print(f"  ... [truncated to {preview_bytes} bytes]")
            else:
                print("  Body: <suppressed by SUGARKUBE_APP_VERIFY_SHOW_BODY=0>")
        finally:
            body_path.unlink(missing_ok=True)

    print()
    if not failures:
        print(f"Verification passed: {passed}/{len(paths)} checks succeeded.")
        return 0

    failed = len(failures)
    print(
        f"Verification failed: {passed}/{len(paths)} checks succeeded; {failed} failed.",
        file=sys.stderr,
    )
    print("Failed paths:", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
