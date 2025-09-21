#!/usr/bin/env python3
"""Publish anonymized sugarkube telemetry to a configurable endpoint."""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Iterable, List, Mapping, MutableMapping, Sequence

TELEMETRY_SCHEMA = "https://sugarkube.dev/telemetry/v1"
DEFAULT_TIMEOUT = 10.0
DEFAULT_VERIFIER_TIMEOUT = 120.0


class TelemetryError(RuntimeError):
    """Raised when telemetry generation or upload fails."""


def log(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def env_flag(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    value = value.strip().lower()
    return value in {"1", "true", "yes", "on"}


def parse_verifier_output(raw: str) -> List[Mapping[str, str]]:
    if not raw or not raw.strip():
        raise TelemetryError("verifier output was empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TelemetryError("verifier output was not valid JSON") from exc
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise TelemetryError("verifier output missing checks array")
    parsed: List[Mapping[str, str]] = []
    for entry in checks:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        status = entry.get("status")
        if isinstance(name, str) and isinstance(status, str):
            parsed.append({"name": name, "status": status})
    if not parsed:
        raise TelemetryError("verifier checks were empty after filtering")
    return parsed


def summarise_checks(checks: Iterable[Mapping[str, str]]) -> MutableMapping[str, object]:
    total = 0
    passed = 0
    failed: List[str] = []
    skipped = 0
    other = 0
    for check in checks:
        total += 1
        status = check.get("status", "")
        if status == "pass":
            passed += 1
        elif status == "fail":
            failed.append(check.get("name", "unknown"))
        elif status == "skip":
            skipped += 1
        else:
            other += 1
    return {
        "total": total,
        "passed": passed,
        "failed": len(failed),
        "skipped": skipped,
        "other": other,
        "failed_checks": failed,
    }


def read_text(path: Path) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    return data


def fingerprint_sources() -> List[str]:
    sources: List[str] = []
    for candidate in (
        Path("/etc/machine-id"),
        Path("/var/lib/dbus/machine-id"),
    ):
        data = read_text(candidate)
        if data:
            sources.append(f"{candidate}:{data}")
    cpuinfo = read_text(Path("/proc/cpuinfo"))
    if cpuinfo:
        for line in cpuinfo.splitlines():
            if line.lower().startswith("serial"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    serial = parts[1].strip()
                    if serial:
                        sources.append(f"cpu-serial:{serial}")
                break
    model = read_text(Path("/proc/device-tree/model"))
    if model:
        sources.append(f"model:{model}")
    return sources


def hashed_identifier(*, salt: str = "") -> str:
    sources = fingerprint_sources()
    if not sources:
        sources.append(f"uuid:{uuid.getnode():x}")
    digest = hashlib.sha256()
    if salt:
        digest.update(salt.encode("utf-8", errors="ignore"))
    digest.update("::".join(sources).encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def collect_os_release() -> Mapping[str, str]:
    path = Path("/etc/os-release")
    data = read_text(path)
    result: dict[str, str] = {}
    if not data:
        return result
    for line in data.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"')
        result[key] = value
    return result


def read_uptime() -> float | None:
    data = read_text(Path("/proc/uptime"))
    if not data:
        return None
    first = data.split()[0]
    try:
        return float(first)
    except ValueError:
        return None


def collect_environment() -> MutableMapping[str, object]:
    env: MutableMapping[str, object] = {}
    uptime = read_uptime()
    if uptime is not None:
        env["uptime_seconds"] = int(uptime)
    uname = os.uname()
    env["kernel"] = f"{uname.sysname} {uname.release}"
    hardware = read_text(Path("/proc/device-tree/model"))
    if hardware:
        env["hardware_model"] = hardware.replace("\x00", "")
    os_release = collect_os_release()
    if os_release:
        env["os_release"] = {
            key: os_release[key]
            for key in sorted(os_release)
            if key in {"ID", "ID_LIKE", "PRETTY_NAME", "VERSION", "VERSION_ID"}
        }
    return env


def parse_tags(raw: str | None) -> List[str]:
    if not raw:
        return []
    tags = []
    for piece in raw.split(","):
        cleaned = piece.strip()
        if cleaned:
            tags.append(cleaned)
    return tags


def build_payload(
    *,
    checks: Sequence[Mapping[str, str]],
    identifier: str,
    env_snapshot: Mapping[str, object],
    errors: Sequence[str],
    tags: Sequence[str],
) -> MutableMapping[str, object]:
    timestamp = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    summary = summarise_checks(checks)
    payload: MutableMapping[str, object] = {
        "schema": TELEMETRY_SCHEMA,
        "generated_at": timestamp,
        "instance": {"id": identifier},
        "verifier": {
            "summary": summary,
            "checks": list(checks),
        },
        "environment": dict(env_snapshot),
    }
    if errors:
        payload["errors"] = list(errors)
    if tags:
        payload["tags"] = list(tags)
    return payload


def discover_verifier_path(explicit: str | None) -> str | None:
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    env_value = os.environ.get("SUGARKUBE_TELEMETRY_VERIFIER")
    if env_value:
        candidates.append(env_value)
    script_dir = Path(__file__).resolve().parent
    candidates.extend(
        [
            str(script_dir / "pi_node_verifier.sh"),
            "/usr/local/sbin/pi_node_verifier.sh",
            "/usr/local/bin/pi_node_verifier.sh",
            "/opt/sugarkube/pi_node_verifier.sh",
            "pi_node_verifier.sh",
        ]
    )
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        resolved = shutil.which(candidate) if not path.is_absolute() else None
        if resolved:
            return resolved
    return None


def run_verifier(verifier_path: str, timeout: float) -> tuple[List[Mapping[str, str]], List[str]]:
    errors: List[str] = []
    try:
        result = subprocess.run(
            [verifier_path, "--json", "--no-log"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise TelemetryError(f"verifier not found at {verifier_path}") from exc
    except subprocess.TimeoutExpired:
        errors.append("verifier_timeout")
        return [], errors
    except subprocess.CalledProcessError as exc:
        errors.append(f"verifier_exit_{exc.returncode}")
        output = exc.stdout or ""
        if output:
            try:
                checks = parse_verifier_output(output)
                return checks, errors
            except TelemetryError as inner:
                errors.append(str(inner))
        return [], errors
    try:
        checks = parse_verifier_output(result.stdout)
    except TelemetryError as exc:
        errors.append(str(exc))
        checks = []
    return checks, errors


def send_payload(
    payload: Mapping[str, object],
    *,
    endpoint: str,
    auth_bearer: str | None,
    timeout: float,
) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "sugarkube-telemetry/1.0")
    if auth_bearer:
        request.add_header("Authorization", f"Bearer {auth_bearer}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Drain body to allow keep-alive reuse even though we discard it.
            response.read()
    except urllib.error.HTTPError as exc:
        raise TelemetryError(f"telemetry endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TelemetryError(f"telemetry upload failed: {exc.reason}") from exc


def _resolve_timeout(value: float | None, *, env_var: str, default: float) -> float:
    env_value = os.environ.get(env_var)
    if value is not None:
        return value
    if env_value is None:
        return default
    env_value = env_value.strip()
    if not env_value:
        raise TelemetryError(f"{env_var} must be numeric when set")
    try:
        return float(env_value)
    except ValueError as exc:
        raise TelemetryError(f"{env_var} must be numeric when set (got {env_value!r})") from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        help="Telemetry ingestion endpoint",
        default=os.environ.get("SUGARKUBE_TELEMETRY_ENDPOINT", ""),
    )
    parser.add_argument(
        "--token",
        dest="auth_bearer",
        help="Bearer token passed to the telemetry endpoint",
        default=os.environ.get("SUGARKUBE_TELEMETRY_TOKEN"),
    )
    parser.add_argument(
        "--salt",
        help="Additional salt mixed into the anonymized identifier",
        default=os.environ.get("SUGARKUBE_TELEMETRY_SALT", ""),
    )
    parser.add_argument(
        "--tags",
        help="Comma-separated tags describing this node or environment",
        default=os.environ.get("SUGARKUBE_TELEMETRY_TAGS", ""),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=("HTTP timeout in seconds " f"(default: {DEFAULT_TIMEOUT})"),
    )
    parser.add_argument(
        "--verifier-timeout",
        type=float,
        default=None,
        help=(
            "Timeout in seconds for pi_node_verifier execution "
            f"(default: {DEFAULT_VERIFIER_TIMEOUT})"
        ),
    )
    parser.add_argument(
        "--verifier",
        help="Path to pi_node_verifier.sh (auto-detected when omitted)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=env_flag(os.environ.get("SUGARKUBE_TELEMETRY_DRY_RUN")),
        help="Generate telemetry JSON without sending it",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even when SUGARKUBE_TELEMETRY_ENABLE is false",
    )
    parser.add_argument(
        "--print-payload",
        action="store_true",
        help="Print payload JSON after a successful upload",
    )
    args = parser.parse_args(argv)
    args.timeout = _resolve_timeout(
        args.timeout,
        env_var="SUGARKUBE_TELEMETRY_TIMEOUT",
        default=DEFAULT_TIMEOUT,
    )
    args.verifier_timeout = _resolve_timeout(
        args.verifier_timeout,
        env_var="SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT",
        default=DEFAULT_VERIFIER_TIMEOUT,
    )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    enabled = env_flag(os.environ.get("SUGARKUBE_TELEMETRY_ENABLE"))
    if not (args.force or args.dry_run or enabled):
        log("telemetry disabled (set SUGARKUBE_TELEMETRY_ENABLE=true to enable)")
        return 0
    verifier_path = discover_verifier_path(args.verifier)
    if not verifier_path:
        raise TelemetryError("pi_node_verifier.sh could not be located")
    checks, errors = run_verifier(verifier_path, args.verifier_timeout)
    identifier = hashed_identifier(salt=args.salt)
    env_snapshot = collect_environment()
    tags = parse_tags(args.tags)
    payload = build_payload(
        checks=checks,
        identifier=identifier,
        env_snapshot=env_snapshot,
        errors=errors,
        tags=tags,
    )
    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    endpoint = args.endpoint.strip()
    if not endpoint:
        raise TelemetryError(
            "telemetry endpoint not configured "
            "(set SUGARKUBE_TELEMETRY_ENDPOINT or pass --endpoint)"
        )
    send_payload(
        payload,
        endpoint=endpoint,
        auth_bearer=args.auth_bearer,
        timeout=args.timeout,
    )
    if args.print_payload:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except TelemetryError as exc:
        log(f"error: {exc}")
        raise SystemExit(1)
