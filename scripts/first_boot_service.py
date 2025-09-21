#!/usr/bin/env python3
"""First boot automation for sugarkube images.

This helper expands the root filesystem when possible, waits for cloud-init to finish,
invokes ``pi_node_verifier.sh`` until it succeeds (or attempts are exhausted), and writes
machine- as well as human-readable status reports under ``/boot/first-boot-report``.

Environment variables provide overridable paths so unit tests can exercise the logic
without needing root privileges:

``FIRST_BOOT_REPORT_DIR``
    Directory that will receive ``summary.json``, ``summary.md``, ``summary.html``, and
    supporting log files. Defaults to ``/boot/first-boot-report``.
``FIRST_BOOT_LOG_PATH``
    Destination for the legacy Markdown log appended by ``pi_node_verifier``. Defaults to
    ``/boot/first-boot-report.txt``.
``FIRST_BOOT_STATE_DIR``
    Directory that stores ``first-boot.ok``/``first-boot.failed`` markers and the
    ``rootfs-expanded`` flag. Defaults to ``/var/log/sugarkube``.
``FIRST_BOOT_VERIFIER``
    Path to the verifier executable. Defaults to ``/usr/local/sbin/pi_node_verifier.sh``.
``FIRST_BOOT_ATTEMPTS``
    Number of verifier attempts before giving up. Defaults to ``3``.
``FIRST_BOOT_RETRY_DELAY``
    Seconds to sleep between attempts. Defaults to ``30``.
``FIRST_BOOT_SKIP_LOG``
    When set to ``1`` the script skips the additional ``--log`` invocation. Useful for
    tests that stub the verifier.
``FIRST_BOOT_CLOUD_INIT_TIMEOUT``
    Timeout (seconds) for ``cloud-init status --wait --long``. Defaults to ``300``.
"""

from __future__ import annotations

import html
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class VerifierResult:
    data: dict
    exit_code: int
    stdout: str
    stderr: str
    attempts: int


def _log(message: str) -> None:
    print(f"[first-boot] {message}")


def _warn(message: str) -> None:
    print(f"[first-boot] warning: {message}", file=sys.stderr)


def _expand_rootfs(marker: Path) -> None:
    if marker.exists():
        _log("root filesystem already expanded (marker present)")
        return

    raspi_config = shutil.which("raspi-config")
    if not raspi_config:
        _warn("raspi-config not found; skipping root filesystem expansion")
        return

    _log("expanding root filesystem via raspi-config")
    result = subprocess.run(
        [raspi_config, "nonint", "do_expand_rootfs"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            "raspi-config failed to expand rootfs" + (f": {stderr}" if stderr else "")
        )

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    _log("root filesystem expansion flagged")


def _gather_cloud_init(timeout: int) -> tuple[Optional[str], Optional[int]]:
    cloud_init = shutil.which("cloud-init")
    if not cloud_init:
        _warn("cloud-init not installed; skipping status capture")
        return None, None

    _log("waiting for cloud-init to finish")
    try:
        result = subprocess.run(
            [cloud_init, "status", "--wait", "--long"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _warn("cloud-init status timed out after %ss; partial logs captured" % timeout)
        return (exc.stdout or ""), None

    stdout = result.stdout.strip()
    if not stdout:
        stdout = "cloud-init did not produce status output"
    return stdout, result.returncode


def _run_verifier(
    verifier: Path,
    attempts: int,
    delay: int,
) -> VerifierResult:
    if attempts < 1:
        raise ValueError("FIRST_BOOT_ATTEMPTS must be >= 1")

    last_stdout = ""
    last_stderr = ""
    last_data: Optional[dict] = None
    exit_code = 1

    for attempt in range(1, attempts + 1):
        _log(f"running verifier attempt {attempt}/{attempts}")
        process = subprocess.run(
            [str(verifier), "--json", "--no-log"],
            capture_output=True,
            text=True,
            check=False,
        )
        last_stdout = process.stdout.strip()
        last_stderr = process.stderr.strip()
        exit_code = process.returncode

        if last_stdout:
            try:
                last_data = json.loads(last_stdout)
            except json.JSONDecodeError as exc:
                _warn(f"failed to parse verifier JSON output: {exc}")
                last_data = None
        else:
            last_data = None

        if exit_code == 0 and last_data is not None:
            return VerifierResult(last_data, exit_code, last_stdout, last_stderr, attempt)

        if attempt < attempts:
            _warn("verifier did not succeed (exit %s); retrying after %ss" % (exit_code, delay))
            time.sleep(delay)

    if last_data is None:
        raise RuntimeError("pi_node_verifier did not emit valid JSON output")

    return VerifierResult(last_data, exit_code, last_stdout, last_stderr, attempts)


def _invoke_verifier_log(verifier: Path, log_path: Path) -> int:
    _log("appending verifier report to %s" % log_path)
    process = subprocess.run(
        [str(verifier), "--log", str(log_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.stderr.strip():
        _warn(f"verifier --log stderr: {process.stderr.strip()}")
    return process.returncode


def _render_summary(result: VerifierResult, metadata: dict, cloud_init_text: Optional[str]) -> dict:
    checks = result.data.get("checks", [])
    status_map = {}
    for entry in checks:
        name = entry.get("name")
        status = entry.get("status", "unknown")
        if name:
            status_map[name] = status

    summary = {
        "cloud_init": status_map.get("cloud_init", "unknown"),
        "k3s": status_map.get("k3s_node_ready", "unknown"),
        "projects_compose": status_map.get("projects_compose_active", "unknown"),
        "token_place": status_map.get("token_place_http", "unknown"),
        "dspace": status_map.get("dspace_http", "unknown"),
    }

    statuses = summary.values()
    if any(status == "fail" for status in statuses):
        overall = "fail"
    elif all(status == "pass" for status in statuses):
        overall = "pass"
    else:
        overall = "mixed"

    rendered = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "kernel": platform.uname().release,
        "attempts": result.attempts,
        "verifier_exit_code": result.exit_code,
        "summary": summary,
        "overall": overall,
        "checks": checks,
    }

    rendered.update(metadata)

    if cloud_init_text is not None:
        rendered["cloud_init_status"] = cloud_init_text

    return rendered


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Sugarkube First Boot Summary",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Hostname: `{payload['hostname']}`",
        f"- Kernel: `{payload['kernel']}`",
        f"- Verifier exit code: `{payload['verifier_exit_code']}`",
        f"- Attempts: `{payload['attempts']}`",
        f"- Overall status: **{payload['overall'].upper()}**",
        "",
        "## Key Components",
        "",
        "| Component | Status |",
        "| --- | --- |",
    ]

    summary = payload.get("summary", {})
    label_map = {
        "cloud_init": "cloud-init",
        "k3s": "k3s node",
        "projects_compose": "projects-compose",
        "token_place": "token.place",
        "dspace": "dspace",
    }
    for key, label in label_map.items():
        status = summary.get(key, "unknown")
        lines.append(f"| {label} | {status} |")

    lines.extend(
        [
            "",
            "## Detailed Checks",
            "",
            "| Check | Status |",
            "| --- | --- |",
        ]
    )

    for entry in payload.get("checks", []):
        name = entry.get("name", "unknown")
        status = entry.get("status", "unknown")
        lines.append(f"| {name} | {status} |")

    cloud_init_status = payload.get("cloud_init_status")
    if cloud_init_status:
        lines.extend(
            [
                "",
                "## cloud-init Status",
                "",
                "```",
                cloud_init_status,
                "```",
            ]
        )

    path.write_text("\n".join(lines) + "\n")


def _write_html(path: Path, payload: dict) -> None:
    def td(text: str) -> str:
        return f"<td>{html.escape(text)}</td>"

    summary_rows = []
    label_map = {
        "cloud_init": "cloud-init",
        "k3s": "k3s node",
        "projects_compose": "projects-compose",
        "token_place": "token.place",
        "dspace": "dspace",
    }
    for key, label in label_map.items():
        status = str(payload.get("summary", {}).get(key, "unknown"))
        summary_rows.append(f"<tr>{td(label)}{td(status)}</tr>")

    check_rows = []
    for entry in payload.get("checks", []):
        name = str(entry.get("name", "unknown"))
        status = str(entry.get("status", "unknown"))
        check_rows.append(f"<tr>{td(name)}{td(status)}</tr>")

    meta_items = [
        ("Generated at", payload.get("generated_at", "")),
        ("Hostname", payload.get("hostname", "")),
        ("Kernel", payload.get("kernel", "")),
        ("Attempts", str(payload.get("attempts", ""))),
        ("Verifier exit code", str(payload.get("verifier_exit_code", ""))),
        ("Overall status", payload.get("overall", "")),
    ]
    meta_rows = [f"<tr>{td(label)}{td(str(value))}</tr>" for label, value in meta_items]

    cloud_init_status = payload.get("cloud_init_status")
    cloud_init_block = (
        "<section><h2>cloud-init Status</h2><pre>%s</pre></section>"
        % html.escape(cloud_init_status)
        if cloud_init_status
        else ""
    )

    html_body = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Sugarkube First Boot Summary</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 2rem;
    }}
    table {{
      border-collapse: collapse;
      margin-bottom: 1.5rem;
      min-width: 20rem;
    }}
    th, td {{
      border: 1px solid #ccc;
      padding: 0.5rem 0.75rem;
      text-align: left;
    }}
    th {{
      background: #f2f2f2;
    }}
    h1 {{
      margin-top: 0;
    }}
    pre {{
      background: #f8f8f8;
      padding: 1rem;
      overflow-x: auto;
    }}
  </style>
</head>
<body>
  <h1>Sugarkube First Boot Summary</h1>
  <table>
    <thead><tr><th>Field</th><th>Value</th></tr></thead>
    <tbody>
      {''.join(meta_rows)}
    </tbody>
  </table>
  <section>
    <h2>Key Components</h2>
    <table>
      <thead><tr><th>Component</th><th>Status</th></tr></thead>
      <tbody>
        {''.join(summary_rows)}
      </tbody>
    </table>
  </section>
  <section>
    <h2>Detailed Checks</h2>
    <table>
      <thead><tr><th>Check</th><th>Status</th></tr></thead>
      <tbody>
        {''.join(check_rows)}
      </tbody>
    </table>
  </section>
  {cloud_init_block}
</body>
</html>
"""
    path.write_text(textwrap.dedent(html_body))


def _write_verifier_stderr(path: Path, stderr: str) -> None:
    if not stderr:
        if path.exists():
            path.unlink()
        return
    path.write_text(stderr + "\n")


def main() -> int:
    report_dir = Path(os.environ.get("FIRST_BOOT_REPORT_DIR", "/boot/first-boot-report"))
    log_path = Path(os.environ.get("FIRST_BOOT_LOG_PATH", "/boot/first-boot-report.txt"))
    state_dir = Path(os.environ.get("FIRST_BOOT_STATE_DIR", "/var/log/sugarkube"))
    verifier = Path(os.environ.get("FIRST_BOOT_VERIFIER", "/usr/local/sbin/pi_node_verifier.sh"))
    attempts = int(os.environ.get("FIRST_BOOT_ATTEMPTS", "3"))
    delay = int(os.environ.get("FIRST_BOOT_RETRY_DELAY", "30"))
    skip_log = os.environ.get("FIRST_BOOT_SKIP_LOG", "0") == "1"
    cloud_init_timeout = int(os.environ.get("FIRST_BOOT_CLOUD_INIT_TIMEOUT", "300"))

    ok_marker = Path(os.environ.get("FIRST_BOOT_OK_MARKER", state_dir / "first-boot.ok"))
    fail_marker = Path(os.environ.get("FIRST_BOOT_FAIL_MARKER", state_dir / "first-boot.failed"))
    expand_marker = Path(os.environ.get("FIRST_BOOT_EXPAND_MARKER", state_dir / "rootfs-expanded"))

    report_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    if ok_marker.exists():
        _log("first-boot already completed successfully; exiting")
        return 0

    _expand_rootfs(expand_marker)
    cloud_init_text, cloud_init_exit = _gather_cloud_init(cloud_init_timeout)

    metadata = {}
    if cloud_init_exit is not None:
        metadata["cloud_init_exit_code"] = cloud_init_exit

    result = _run_verifier(verifier, attempts, delay)
    _write_verifier_stderr(report_dir / "verifier.stderr", result.stderr)

    log_exit = 0
    if not skip_log:
        log_exit = _invoke_verifier_log(verifier, log_path)

    payload = _render_summary(result, metadata, cloud_init_text)
    _write_json(report_dir / "summary.json", payload)
    _write_markdown(report_dir / "summary.md", payload)
    _write_html(report_dir / "summary.html", payload)

    if cloud_init_text is not None:
        (report_dir / "cloud-init.log").write_text(cloud_init_text + "\n")

    overall_exit = result.exit_code if result.exit_code != 0 else log_exit
    if overall_exit != 0:
        fail_marker.write_text(f"verifier exit code {result.exit_code}; log exit code {log_exit}\n")
        if ok_marker.exists():
            ok_marker.unlink()
        return overall_exit or 1

    if fail_marker.exists():
        fail_marker.unlink()
    ok_marker.write_text("ok\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(main())
    except Exception as exc:  # pylint: disable=broad-except
        _warn(str(exc))
        raise
