#!/usr/bin/env python3
"""Generate first boot health reports for sugarkube Pi images."""
from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPORT_DIR = Path("/boot/first-boot-report")
SUCCESS_FLAG = Path("/var/log/sugarkube/first-boot.ok")
VERIFIER_CANDIDATES = [
    Path("/usr/local/bin/pi_node_verifier.sh"),
    Path("/usr/local/sbin/pi_node_verifier.sh"),
    Path("/usr/bin/pi_node_verifier.sh"),
]
SUMMARY_PATH = REPORT_DIR / "summary.md"
SUMMARY_TEXT = Path("/boot/first-boot-report.txt")
VERIFIER_JSON = REPORT_DIR / "verifier.json"
STATUS_JSON = REPORT_DIR / "status.json"
INDEX_HTML = REPORT_DIR / "index.html"
LOG_PATH = REPORT_DIR / "first-boot.log"


class FirstBootError(Exception):
    """Raised when a critical step fails."""


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{timestamp}] {message}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_command(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    log(f"$ {' '.join(shlex_quote(part) for part in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        log(result.stdout.strip())
    if result.stderr:
        log(result.stderr.strip())
    if check and result.returncode != 0:
        raise FirstBootError(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def shlex_quote(value: str) -> str:
    if value.isalnum() or value in {"/", "-", "_", "."}:
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def ensure_dirs() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.touch(exist_ok=True)
    SUCCESS_FLAG.parent.mkdir(parents=True, exist_ok=True)


def expand_root_filesystem() -> Dict[str, Any]:
    info: Dict[str, Any] = {"changed": False, "method": None, "details": []}
    root_proc = run_command(["findmnt", "-n", "-o", "SOURCE", "/"])
    root_device = root_proc.stdout.strip()
    if not root_device.startswith("/dev/"):
        info["details"].append(f"Unsupported root device: {root_device}")
        return info

    partnum_proc = run_command(["lsblk", "-no", "PARTNUM", root_device])
    pkname_proc = run_command(["lsblk", "-no", "PKNAME", root_device])
    try:
        partnum = partnum_proc.stdout.strip()
        parent = pkname_proc.stdout.strip()
    except AttributeError:  # pragma: no cover
        partnum = ""
        parent = ""
    if not partnum or not parent:
        info["details"].append("Could not determine partition metadata")
        return info

    disk = f"/dev/{parent}"
    resize_method: Optional[str] = None

    if shutil.which("growpart"):
        resize_method = "growpart"
        result = run_command(["growpart", disk, partnum])
        combined = f"{result.stdout} {result.stderr}".strip()
        if "NOCHANGE" in combined.upper():
            info["details"].append("Partition already maximized")
        elif result.returncode == 0:
            info["changed"] = True
        else:
            info["details"].append("growpart failed; falling back if possible")
            resize_method = None
    if resize_method is None and shutil.which("raspi-config"):
        resize_method = "raspi-config"
        result = run_command(["raspi-config", "nonint", "do_expand_rootfs"])
        if result.returncode == 0:
            info["changed"] = True
        else:
            info["details"].append("raspi-config failed to expand rootfs")
            resize_method = None

    info["method"] = resize_method
    if info["changed"] and shutil.which("resize2fs"):
        run_command(["resize2fs", root_device])
    return info


def locate_verifier() -> Path:
    for candidate in VERIFIER_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FirstBootError("pi_node_verifier.sh not found in expected locations")


def run_verifier() -> Dict[str, Any]:
    verifier_path = locate_verifier()

    if SUMMARY_PATH.exists():
        SUMMARY_PATH.unlink()
    SUMMARY_PATH.touch()

    proc = run_command(
        [str(verifier_path), "--json", "--log", str(SUMMARY_PATH)],
        check=True,
    )

    VERIFIER_JSON.write_text(proc.stdout, encoding="utf-8")
    SUMMARY_TEXT.write_text(SUMMARY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return json.loads(proc.stdout)


def get_systemd_status(unit: str) -> Dict[str, Any]:
    result = run_command(["systemctl", "is-active", unit])
    status = result.stdout.strip() or "unknown"
    return {"unit": unit, "status": status, "returncode": result.returncode}


def kubectl_command() -> Optional[List[str]]:
    if shutil.which("kubectl"):
        return ["kubectl"]
    if shutil.which("k3s"):
        return ["k3s", "kubectl"]
    return None


def get_k3s_status() -> Dict[str, Any]:
    status = get_systemd_status("k3s.service")
    cmd = kubectl_command()
    nodes: List[Dict[str, Any]] = []
    ready = None
    details: List[str] = []
    if cmd:
        result = run_command(cmd + ["get", "nodes", "-o", "json"])
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                items = data.get("items", [])
                ready = True if items else False
                for item in items:
                    name = item.get("metadata", {}).get("name", "unknown")
                    conditions = item.get("status", {}).get("conditions", [])
                    ready_cond = next(
                        (c for c in conditions if c.get("type") == "Ready"),
                        None,
                    )
                    is_ready = ready_cond and ready_cond.get("status") == "True"
                    if ready is True and not is_ready:
                        ready = False
                    nodes.append(
                        {
                            "name": name,
                            "ready": bool(is_ready),
                            "message": ready_cond.get("message") if ready_cond else None,
                        }
                    )
            except json.JSONDecodeError as exc:
                details.append(f"kubectl JSON parse error: {exc}")
        else:
            details.append("kubectl get nodes failed")
    else:
        details.append("kubectl not available")
    status.update({"nodes": nodes, "ready": ready, "details": details})
    return status


def docker_status(name: str) -> Dict[str, Any]:
    if not shutil.which("docker"):
        return {"name": name, "available": False, "status": "docker-missing"}
    inspect = run_command(["docker", "inspect", "--format", "{{.State.Status}}", name])
    if inspect.returncode == 0:
        state = inspect.stdout.strip()
        return {"name": name, "available": True, "status": state}
    listing = run_command(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Status}}"],
    )
    state = listing.stdout.strip() if listing.stdout else "not-found"
    return {"name": name, "available": True, "status": state}


def compose_status() -> Dict[str, Any]:
    status = get_systemd_status("projects-compose.service")
    tokenplace = docker_status("tokenplace")
    dspace = docker_status("dspace")
    status.update({"tokenplace": tokenplace, "dspace": dspace})
    return status


def read_verifier_status(verifier: Dict[str, Any], name: str) -> Optional[str]:
    for check in verifier.get("checks", []):
        if check.get("name") == name:
            return check.get("status")
    return None


def write_status(verifier: Dict[str, Any], fs_info: Dict[str, Any]) -> Dict[str, Any]:
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    k3s = get_k3s_status()
    compose = compose_status()
    data = {
        "generated_at": generated,
        "filesystem": fs_info,
        "cloud_init": read_verifier_status(verifier, "cloud_init"),
        "k3s": k3s,
        "projects_compose": compose,
        "verifier": verifier,
    }
    STATUS_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def write_html(status: Dict[str, Any]) -> None:
    generated = html.escape(status["generated_at"])
    cloud_init = html.escape(str(status.get("cloud_init", "unknown")))
    fs_method = html.escape(str(status["filesystem"].get("method")))
    fs_changed = "Yes" if status["filesystem"].get("changed") else "No"
    k3s_ready = status["k3s"].get("ready")
    if k3s_ready is True:
        k3s_label = "Ready"
    elif k3s_ready is False:
        k3s_label = "Not Ready"
    else:
        k3s_label = "Unknown"
    compose_status = html.escape(status["projects_compose"].get("status", "unknown"))

    node_rows = "".join(
        f"<tr><td>{html.escape(node['name'])}</td><td>{'Yes' if node['ready'] else 'No'}</td>"
        f"<td>{html.escape(str(node.get('message') or ''))}</td></tr>"
        for node in status["k3s"].get("nodes", [])
    )
    if not node_rows:
        node_rows = "<tr><td colspan=3>No nodes reported</td></tr>"

    def service_cell(service: Dict[str, Any]) -> str:
        state = html.escape(service.get("status", "unknown"))
        available = "Yes" if service.get("available") else "No"
        return f"<td>{available}</td><td>{state}</td>"

    tokenplace = status["projects_compose"].get("tokenplace", {})
    dspace = status["projects_compose"].get("dspace", {})

    html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>Sugarkube First Boot Report</title>
  <style>
    body {{ font-family: sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
    th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; }}
    th {{ background: #f5f5f5; }}
  </style>
</head>
<body>
  <h1>Sugarkube First Boot Report</h1>
  <p>Generated at <strong>{generated}</strong></p>
  <h2>Summary</h2>
  <table>
    <tr><th>Check</th><th>Result</th><th>Details</th></tr>
    <tr><td>cloud-init</td><td>{cloud_init}</td><td>&nbsp;</td></tr>
    <tr><td>Filesystem expanded</td><td>{fs_changed}</td><td>{fs_method}</td></tr>
    <tr><td>k3s readiness</td><td>{k3s_label}</td><td>{compose_status}</td></tr>
  </table>
  <h2>k3s Nodes</h2>
  <table>
    <tr><th>Name</th><th>Ready</th><th>Message</th></tr>
    {node_rows}
  </table>
  <h2>Projects Compose Services</h2>
  <table>
    <tr><th>Service</th><th>Docker Available</th><th>Status</th></tr>
    <tr><td>token.place</td>{service_cell(tokenplace)}</tr>
    <tr><td>dspace</td>{service_cell(dspace)}</tr>
  </table>
  <p>Machine-readable output is stored in <code>status.json</code> and
     <code>verifier.json</code>.</p>
</body>
</html>
"""
    INDEX_HTML.write_text(html_doc, encoding="utf-8")


def main() -> int:
    ensure_dirs()
    try:
        fs_info = expand_root_filesystem()
    except Exception as exc:  # pragma: no cover
        log(f"Filesystem expansion error: {exc}")
        fs_info = {"changed": False, "method": None, "details": [str(exc)]}

    try:
        verifier = run_verifier()
    except Exception as exc:
        log(f"Verifier failed: {exc}")
        verifier = {"checks": [], "error": str(exc)}

    status = write_status(verifier, fs_info)
    write_html(status)

    if not status.get("verifier", {}).get("error"):
        SUCCESS_FLAG.write_text(
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
