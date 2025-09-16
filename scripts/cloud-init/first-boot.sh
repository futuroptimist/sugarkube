#!/usr/bin/env bash
set -euo pipefail

umask 077

LOG_DIR="/var/log/sugarkube"
STATE_DIR="/var/lib/sugarkube"
REPORT_DIR="/boot/first-boot-report"
REPORT_TEXT="/boot/first-boot-report.txt"
REPORT_JSON="${REPORT_DIR}/report.json"
REPORT_HTML="${REPORT_DIR}/report.html"
VERIFIER_JSON="${REPORT_DIR}/verifier.json"
LOG_FILE="${LOG_DIR}/first-boot.log"
STATE_FILE="${STATE_DIR}/first-boot.done"

mkdir -p "${LOG_DIR}" "${STATE_DIR}" "${REPORT_DIR}"
touch "${LOG_FILE}" "${REPORT_TEXT}"

log_line() {
  local timestamp message line
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  message="$*"
  line="${timestamp} ${message}"
  printf '%s\n' "${line}"
  printf '%s\n' "${line}" >>"${LOG_FILE}"
  printf '%s\n' "${line}" >>"${REPORT_TEXT}"
}

TIME_START="$(date +%s)"

cleanup() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    log_line "First boot sequence failed with exit code ${rc}"
  fi
}
trap cleanup EXIT

if [ -f "${STATE_FILE}" ]; then
  log_line "First boot tasks already completed; skipping"
  exit 0
fi

log_line "Starting Sugarkube first boot sequence"

expand_status="skipped"
expand_detail="raspi-config not available"
if command -v raspi-config >/dev/null 2>&1; then
  log_line "Expanding root filesystem with raspi-config"
  if raspi-config nonint do_expand_rootfs >>"${LOG_FILE}" 2>&1; then
    expand_status="ok"
    expand_detail="Root filesystem expansion requested"
    log_line "Root filesystem expansion invoked"
  else
    expand_status="failed"
    expand_detail="raspi-config failed"
    log_line "Root filesystem expansion failed; inspect /var/log/sugarkube/first-boot.log"
  fi
fi

network_status="skipped"
network_detail="network-online.target not present"
network_seconds=0
if systemctl list-unit-files network-online.target >/dev/null 2>&1; then
  network_status="waiting"
  network_detail="waiting for network-online.target"
  log_line "Waiting for network-online.target"
  start_wait="$(date +%s)"
  for _ in $(seq 1 150); do
    if systemctl is-active --quiet network-online.target; then
      network_status="ok"
      network_detail="network-online.target is active"
      break
    fi
    sleep 2
  done
  network_seconds=$(( $(date +%s) - start_wait ))
  if [ "${network_status}" != "ok" ]; then
    network_status="timeout"
    network_detail="network-online.target did not become active"
    log_line "Network did not become ready within ${network_seconds}s"
  else
    log_line "Network ready after ${network_seconds}s"
  fi
else
  log_line "network-online.target unavailable; skipping explicit wait"
fi

verifier_status="skipped"
verifier_detail="pi_node_verifier.sh not found"
if command -v pi_node_verifier.sh >/dev/null 2>&1; then
  tmp_json="$(mktemp)"
  tmp_err="$(mktemp)"
  if pi_node_verifier.sh --json >"${tmp_json}" 2>"${tmp_err}"; then
    mv "${tmp_json}" "${VERIFIER_JSON}"
    verifier_status="ok"
    verifier_detail="pi_node_verifier.sh executed"
    if [ -s "${tmp_err}" ]; then
      while IFS= read -r line; do
        log_line "verifier: ${line}"
      done <"${tmp_err}"
    fi
    log_line "pi_node_verifier.sh completed"
  else
    verifier_status="failed"
    verifier_detail="pi_node_verifier.sh exited with error"
    if [ -s "${tmp_json}" ]; then
      mv "${tmp_json}" "${VERIFIER_JSON}"
    fi
    if [ -s "${tmp_err}" ]; then
      while IFS= read -r line; do
        log_line "verifier: ${line}"
      done <"${tmp_err}"
    fi
    log_line "pi_node_verifier.sh failed"
  fi
  rm -f "${tmp_json}" "${tmp_err}"
fi

primary_ip=""
if command -v hostname >/dev/null 2>&1; then
  primary_ip="$(hostname -I 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+(\.[0-9]+){3}$/) {print $i; exit}}')"
fi
server_override=""
if [ -n "${primary_ip}" ]; then
  server_override="https://${primary_ip}:6443"
fi

kubeconfig_status="skipped"
kubeconfig_detail="k3s kubeconfig not found"
kubeconfig_src="/etc/rancher/k3s/k3s.yaml"
kubeconfig_dst="${REPORT_DIR}/kubeconfig.yaml"
kubeconfig_boot="/boot/sugarkube-kubeconfig.yaml"
if [ -f "${kubeconfig_src}" ]; then
  kubeconfig_status="ok"
  kubeconfig_detail="kubeconfig exported"
  tmp_kubeconfig="$(mktemp)"
  if [ -n "${server_override}" ]; then
    python3 - "$kubeconfig_src" "$tmp_kubeconfig" "$server_override" <<'PY'
import sys
from pathlib import Path
source = Path(sys.argv[1])
destination = Path(sys.argv[2])
override = sys.argv[3]
content = source.read_text()
content = content.replace("https://127.0.0.1:6443", override)
destination.write_text(content)
PY
  else
    cp "${kubeconfig_src}" "${tmp_kubeconfig}"
  fi
  install -m 0600 "${tmp_kubeconfig}" "${kubeconfig_dst}"
  install -m 0600 "${tmp_kubeconfig}" "${kubeconfig_boot}"
  rm -f "${tmp_kubeconfig}"
  log_line "Kubeconfig exported to ${kubeconfig_boot}"
else
  log_line "k3s kubeconfig missing; skipping export"
fi

node_token_status="skipped"
node_token_detail="node token not found"
node_token_src="/var/lib/rancher/k3s/server/node-token"
node_token_dst="${REPORT_DIR}/node-token"
node_token_boot="/boot/sugarkube-node-token"
if [ -f "${node_token_src}" ]; then
  node_token_status="ok"
  node_token_detail="node token exported"
  install -m 0600 "${node_token_src}" "${node_token_dst}"
  install -m 0600 "${node_token_src}" "${node_token_boot}"
  log_line "Cluster token exported to ${node_token_boot}"
else
  log_line "k3s node token missing; skipping export"
fi

report_generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
report_hostname="$(hostname 2>/dev/null || echo unknown)"

if command -v python3 >/dev/null 2>&1; then
  env -i \
    REPORT_JSON_PATH="${REPORT_JSON}" \
    REPORT_HTML_PATH="${REPORT_HTML}" \
    REPORT_GENERATED_AT="${report_generated_at}" \
    REPORT_HOSTNAME="${report_hostname}" \
    EXPAND_STATUS="${expand_status}" \
    EXPAND_DETAIL="${expand_detail}" \
    NETWORK_STATUS="${network_status}" \
    NETWORK_DETAIL="${network_detail}" \
    NETWORK_SECONDS="${network_seconds}" \
    VERIFIER_STATUS="${verifier_status}" \
    VERIFIER_DETAIL="${verifier_detail}" \
    VERIFIER_JSON_PATH="${VERIFIER_JSON}" \
    KUBECONFIG_STATUS="${kubeconfig_status}" \
    KUBECONFIG_DETAIL="${kubeconfig_detail}" \
    NODE_TOKEN_STATUS="${node_token_status}" \
    NODE_TOKEN_DETAIL="${node_token_detail}" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

def load_verifier(path: Path):
    if path.is_file() and path.stat().st_size > 0:
        return json.loads(path.read_text())
    return None

report = {
    "generated_at": os.environ["REPORT_GENERATED_AT"],
    "hostname": os.environ["REPORT_HOSTNAME"],
    "tasks": {
        "expand_rootfs": {
            "status": os.environ["EXPAND_STATUS"],
            "detail": os.environ["EXPAND_DETAIL"],
        },
        "network_wait": {
            "status": os.environ["NETWORK_STATUS"],
            "detail": os.environ["NETWORK_DETAIL"],
            "seconds": int(os.environ["NETWORK_SECONDS"] or 0),
        },
        "verifier": {
            "status": os.environ["VERIFIER_STATUS"],
            "detail": os.environ["VERIFIER_DETAIL"],
        },
        "kubeconfig_export": {
            "status": os.environ["KUBECONFIG_STATUS"],
            "detail": os.environ["KUBECONFIG_DETAIL"],
            "path": os.environ.get("KUBECONFIG_STATUS") == "ok" and "/boot/sugarkube-kubeconfig.yaml" or None,
        },
        "node_token_export": {
            "status": os.environ["NODE_TOKEN_STATUS"],
            "detail": os.environ["NODE_TOKEN_DETAIL"],
            "path": os.environ.get("NODE_TOKEN_STATUS") == "ok" and "/boot/sugarkube-node-token" or None,
        },
    },
}

verifier_path = Path(os.environ["VERIFIER_JSON_PATH"])
verifier_data = load_verifier(verifier_path)
if verifier_data is not None:
    report["verifier"] = verifier_data

report_path = Path(os.environ["REPORT_JSON_PATH"])
report_path.write_text(json.dumps(report, indent=2) + "\n")

html_path = Path(os.environ["REPORT_HTML_PATH"])
rows = []
for key, value in report["tasks"].items():
    rows.append(
        f"<tr><th>{key}</th><td>{value['status']}</td><td>{value['detail']}</td></tr>"
    )
if "verifier" in report:
    checks_html = "".join(
        f"<li>{check['name']}: {check['status']}</li>" for check in report["verifier"].get("checks", [])
    )
else:
    checks_html = "<li>No verifier data captured</li>"
html_path.write_text(
    """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>Sugarkube First Boot Report</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 2rem; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
      th, td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; }
      th { background: #f8f8f8; }
    </style>
  </head>
  <body>
    <h1>Sugarkube First Boot Report</h1>
    <p><strong>Generated:</strong> {generated}</p>
    <p><strong>Hostname:</strong> {hostname}</p>
    <table>
      <thead>
        <tr><th>Task</th><th>Status</th><th>Detail</th></tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
    <h2>Verifier Checks</h2>
    <ul>{checks}</ul>
  </body>
</html>
""".format(
        generated=report["generated_at"],
        hostname=report["hostname"],
        rows="".join(rows),
        checks=checks_html,
    )
)
PY
else
  log_line "python3 missing; skipping JSON and HTML first boot report generation"
fi

install -m 0644 /dev/null "${STATE_FILE}"
echo "completed $(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${STATE_FILE}"

runtime=$(( $(date +%s) - TIME_START ))
log_line "Sugarkube first boot sequence finished in ${runtime}s"
