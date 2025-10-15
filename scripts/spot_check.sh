#!/usr/bin/env bash
# spot_check.sh - Automated Raspberry Pi 5 image validation spot check.
# Usage: sudo ./scripts/spot_check.sh
# Runs baseline health checks, records machine-readable summaries under artifacts/spot-check,
# and exits non-zero when required checks fail.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/artifacts/spot-check"
LOG_FILE="${ARTIFACT_DIR}/spot-check.log"
RESULTS_TSV="${ARTIFACT_DIR}/results.tsv"
SUMMARY_JSON="${ARTIFACT_DIR}/summary.json"
SUMMARY_MD="${ARTIFACT_DIR}/summary.md"
REQUIRED_FAILURE=0

mkdir -p "${ARTIFACT_DIR}"
: >"${LOG_FILE}"
: >"${RESULTS_TSV}"

log() {
  local message="$1"
  printf '%s\n' "${message}" | tee -a "${LOG_FILE}" >/dev/null
}

add_check() {
  local name="$1"
  local status="$2"
  local required="$3"
  local message="$4"
  local details_json="$5"

  message="${message//$'\n'/ }"
  message="${message//$'\t'/ }"
  details_json="${details_json//$'\n'/ }"
  details_json="${details_json//$'\t'/ }"

  case "${status}" in
    pass) icon="✅" ;;
    warn) icon="⚠️" ;;
    fail)
      icon="❌"
      if [ "${required}" = "true" ]; then
        REQUIRED_FAILURE=1
      fi
      ;;
    *) icon="❓" ;;
  esac

  printf '%s\t%s\t%s\t%s\t%s\n' \
    "${name}" "${status}" "${required}" "${message}" "${details_json}" >>"${RESULTS_TSV}"
  printf '%s %s: %s\n' "${icon}" "${name}" "${message}" | tee -a "${LOG_FILE}"
}

check_system_baseline() {
  local uname_out os_release arch status message
  if ! uname_out=$(uname -a 2>&1); then
    add_check "System baseline" "fail" "true" "Unable to read kernel info" "{}"
    return
  fi
  if ! os_release=$(cat /etc/os-release 2>&1); then
    add_check "System baseline" "fail" "true" "Unable to read /etc/os-release" "{}"
    return
  fi
  arch="$(uname -m)"
  local os_name version codename
  os_name=$(printf '%s\n' "${os_release}" | awk -F'=' '/^NAME=/{gsub(/"/,"",$2); print $2}')
  version=$(printf '%s\n' "${os_release}" | awk -F'=' '/^VERSION=/{gsub(/"/,"",$2); print $2}')
  codename=$(printf '%s\n' "${os_release}" | awk -F'=' '/^VERSION_CODENAME=/{gsub(/"/,"",$2); print $2}')
  status="pass"
  message="${os_name} ${version} (${arch})"
  if [ "${arch}" != "aarch64" ]; then
    status="fail"
    message="Unexpected architecture ${arch}"
  elif [ "${codename}" != "bookworm" ]; then
    status="warn"
    message="VERSION_CODENAME=${codename} (expected bookworm)"
  fi
  local details_json
  details_json=$(python3 - "${uname_out}" "${os_release}" "${arch}" "${codename}" <<'PY'
import json, sys
uname, os_release, arch, codename = sys.argv[1:5]
print(json.dumps({
    "uname": uname,
    "os_release": os_release,
    "arch": arch,
    "codename": codename,
}))
PY
  )
  add_check "System baseline" "${status}" "true" "${message}" "${details_json}"
}

check_time_locale() {
  local timedate_out locale_out message status ntp_active tz_line locale_line
  if ! timedate_out=$(timedatectl 2>&1); then
    add_check "Time & locale" "fail" "true" "timedatectl unavailable" "{}"
    return
  fi
  if ! locale_out=$(locale 2>&1); then
    add_check "Time & locale" "fail" "true" "locale command failed" "{}"
    return
  fi
  ntp_active=$(printf '%s\n' "${timedate_out}" | awk -F': ' '/NTP service:/{print $2}' | tr '[:upper:]' '[:lower:]')
  if [ -z "${ntp_active}" ]; then
    ntp_active=$(printf '%s\n' "${timedate_out}" | awk -F': ' '/System clock synchronized:/{print $2}' | tr '[:upper:]' '[:lower:]')
  fi
  tz_line=$(printf '%s\n' "${timedate_out}" | awk -F': ' '/Time zone:/{print $2}')
  locale_line=$(printf '%s\n' "${locale_out}" | awk -F'=' '/^LANG=/{print $2}')
  status="pass"
  if [ "${ntp_active}" != "active" ] && [ "${ntp_active}" != "yes" ]; then
    status="fail"
  fi
  message="NTP=${ntp_active:-unknown}, TZ=${tz_line:-unset}, LANG=${locale_line:-unset}"
  local details_json
  details_json=$(python3 - "${timedate_out}" "${locale_out}" "${ntp_active}" "${tz_line}" "${locale_line}" <<'PY'
import json, sys
print(json.dumps({
    "timedatectl": sys.argv[1],
    "locale": sys.argv[2],
    "ntp_active": sys.argv[3],
    "timezone": sys.argv[4],
    "lang": sys.argv[5],
}))
PY
  )
  add_check "Time & locale" "${status}" "true" "${message}" "${details_json}"
}

check_storage() {
  local df_out lsblk_json blkid_out status message root_match boot_match
  if ! df_out=$(df -h 2>&1); then
    add_check "Storage layout" "fail" "true" "df failed" "{}"
    return
  fi
  if ! lsblk_json=$(lsblk -J -o NAME,SIZE,FSTYPE,MOUNTPOINT,TYPE,UUID 2>/dev/null); then
    add_check "Storage layout" "fail" "true" "lsblk -J failed" "{}"
    return
  fi
  if ! blkid_out=$(blkid 2>/dev/null); then
    blkid_out=""
  fi
  root_match=$(printf '%s' "${lsblk_json}" | python3 - <<'PY'
import json, sys
nodes = json.load(sys.stdin)["blockdevices"]
found_root = False
found_boot = False
parts = []
for node in nodes:
    if node.get("type") != "disk":
        continue
    for child in node.get("children", []):
        if child.get("type") != "part":
            continue
        entry = {
            "device": f"/dev/{child['name']}",
            "size": child.get("size"),
            "fstype": child.get("fstype"),
            "mountpoint": child.get("mountpoint") or "",
            "uuid": child.get("uuid") or "",
        }
        parts.append(entry)
        if child.get("mountpoint") == "/":
            found_root = child["name"].startswith("mmcblk0p2")
        if child.get("mountpoint") == "/boot/firmware":
            found_boot = child["name"].startswith("mmcblk0p1")
print(json.dumps({"parts": parts, "root_ok": found_root, "boot_ok": found_boot}))
PY
  )
  status="pass"
  local parsed
  parsed="${root_match}"
  local root_ok boot_ok
  root_ok=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['root_ok'])" "${parsed}")
  boot_ok=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['boot_ok'])" "${parsed}")
  if [ "${root_ok}" != "True" ] || [ "${boot_ok}" != "True" ]; then
    status="fail"
  fi
  message="root mmcblk0p2=${root_ok}, boot mmcblk0p1=${boot_ok}"
  local details_json
  details_json=$(python3 - "${df_out}" "${lsblk_json}" "${blkid_out}" "${parsed}" <<'PY'
import json, sys
print(json.dumps({
    "df": sys.argv[1],
    "lsblk": json.loads(sys.argv[2]),
    "blkid": sys.argv[3],
    "table": json.loads(sys.argv[4])["parts"],
}))
PY
  )
  add_check "Storage layout" "${status}" "true" "${message}" "${details_json}"
}

ping_host() {
  local host="$1"
  if command -v ping >/dev/null 2>&1; then
    ping -c 4 -q "${host}" 2>&1
  else
    echo "ping unavailable"
    return 1
  fi
}

parse_ping() {
  python3 - "$1" <<'PY'
import json, re, sys
text = sys.argv[1]
loss = re.search(r"([0-9.]+)% packet loss", text)
match = re.search(r"= ([0-9.]+)/([0-9.]+)/([0-9.]+)/", text)
result = {
  "raw": text,
  "loss_percent": float(loss.group(1)) if loss else None,
  "avg_ms": float(match.group(2)) if match else None,
}
print(json.dumps(result))
PY
}

check_networking() {
  local gateway ping_gateway ping_wan status message gw_stats wan_stats
  gateway=$(ip route 2>/dev/null | awk '/default/ {print $3; exit}')
  if [ -z "${gateway}" ]; then
    gateway=""
  fi
  if [ -n "${gateway}" ]; then
    if ping_gateway=$(ping_host "${gateway}"); then
      gw_stats=$(parse_ping "${ping_gateway}")
    else
      gw_stats=$(parse_ping "${ping_gateway}")
    fi
  else
    gw_stats='{"raw":"no gateway detected","loss_percent":null,"avg_ms":null}'
  fi
  if ping_wan=$(ping_host "1.1.1.1"); then
    wan_stats=$(parse_ping "${ping_wan}")
  else
    wan_stats=$(parse_ping "${ping_wan}")
  fi
  status="pass"
  local gw_loss wan_loss
  gw_loss=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('loss_percent'))" "${gw_stats}")
  wan_loss=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('loss_percent'))" "${wan_stats}")
  if [ "${wan_loss}" = "None" ] || [ "${wan_loss}" = "null" ]; then
    status="fail"
    message="WAN ping unavailable"
  elif (( $(python3 -c "import sys; print(1 if float(sys.argv[1] or 100) == 0 else 0)" "${wan_loss}") == 0 )); then
    status="fail"
    message="WAN ping loss ${wan_loss}%"
  else
    message="WAN ${wan_loss}% loss, avg $(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('avg_ms'))" "${wan_stats}") ms"
    if [ "${gw_loss}" != "None" ] && [ "${gw_loss}" != "null" ]; then
      message="LAN ${gw_loss}% loss, ${message}"
      if (( $(python3 -c "import sys; print(1 if float(sys.argv[1] or 100) == 0 else 0)" "${gw_loss}") == 0 )); then
        status="fail"
      fi
    fi
  fi
  local details_json
  details_json=$(python3 - "${gateway}" "${gw_stats}" "${wan_stats}" <<'PY'
import json, sys
print(json.dumps({
    "gateway": sys.argv[1],
    "lan": json.loads(sys.argv[2]),
    "wan": json.loads(sys.argv[3]),
}))
PY
  )
  add_check "Networking" "${status}" "true" "${message}" "${details_json}"
}

check_link_speed() {
  local speed status message details_json ethtool_out
  if command -v ethtool >/dev/null 2>&1; then
    if ethtool_out=$(ethtool eth0 2>&1); then
      speed=$(printf '%s\n' "${ethtool_out}" | awk -F': ' '/Speed:/{print $2; exit}')
    else
      ethtool_out="$(nmcli dev show eth0 2>&1 || true)"
      speed=$(printf '%s\n' "${ethtool_out}" | awk -F': ' '/SPEED/{print $2; exit}')
    fi
  else
    ethtool_out="$(nmcli dev show eth0 2>&1 || true)"
    speed=$(printf '%s\n' "${ethtool_out}" | awk -F': ' '/SPEED/{print $2; exit}')
  fi
  if [ -z "${speed}" ]; then
    status="warn"
    message="Unable to determine eth0 speed"
  else
    status="pass"
    message="eth0 speed ${speed}"
    if [[ "${speed}" =~ [0-9]+ ]] && [ "${speed%%Mb/s}" -lt 1000 ]; then
      status="warn"
      message="eth0 speed ${speed} (<1000Mb/s)"
    fi
  fi
  details_json=$(python3 - "${ethtool_out:-}" "${speed:-}" "${status}" <<'PY'
import json, sys
print(json.dumps({
    "output": sys.argv[1],
    "speed": sys.argv[2],
    "status": sys.argv[3],
}))
PY
  )
  add_check "Link speed" "${status}" "false" "${message}" "${details_json}"
}

check_services_logs() {
  local services journal status message filtered err_lines
  services=$(systemctl list-unit-files --type=service 2>/dev/null | grep -E 'flywheel|k3s|cloudflared|containerd' || true)
  if [ -n "${services}" ]; then
    status="warn"
    message="Unexpected services present"
  else
    status="pass"
    message="flywheel/k3s/cloudflared/containerd absent"
  fi
  journal=$(journalctl -b -p 3 --no-pager 2>&1 || true)
  filtered=$(printf '%s\n' "${journal}" | grep -v -E 'bluetooth|vcp|mcp|bap|bgscan simple' || true)
  err_lines=$(printf '%s' "${filtered}" | sed '/^--/d;/^$/d')
  if [ -n "${err_lines}" ]; then
    status="fail"
    message="High-priority journal errors detected"
  fi
  local details_json
  details_json=$(python3 - "${services}" "${journal}" "${filtered}" "${err_lines}" <<'PY'
import json, sys
print(json.dumps({
    "services": sys.argv[1],
    "journal_raw": sys.argv[2],
    "journal_filtered": sys.argv[3],
    "unexpected_errors": sys.argv[4],
}))
PY
  )
  add_check "Services & logs" "${status}" "true" "${message}" "${details_json}"
}

check_health() {
  local temp_out temp_value mem_out avail_bytes throttle_out throttle_value status message warnings
  warnings=()
  if command -v vcgencmd >/dev/null 2>&1; then
    temp_out=$(vcgencmd measure_temp 2>&1 || true)
    temp_value=$(printf '%s' "${temp_out}" | grep -Eo '[0-9.]+')
    if [ -n "${temp_value}" ]; then
      if (( $(python3 -c "import sys; print(1 if float(sys.argv[1]) < 60 else 0)" "${temp_value}") == 1 )); then
        :
      else
        warnings+=("temp ${temp_value}C >= 60")
      fi
    else
      warnings+=("temp unavailable")
    fi
  else
    temp_out="vcgencmd missing"
    warnings+=("vcgencmd missing")
  fi
  mem_out=$(free --bytes 2>/dev/null || free -b 2>/dev/null || true)
  avail_bytes=$(printf '%s' "${mem_out}" | awk '/Mem:/ {print $7}')
  if [ -n "${avail_bytes}" ]; then
    if [ "${avail_bytes}" -lt $((7 * 1024 * 1024 * 1024)) ]; then
      warnings+=("available memory < 7 GiB")
    fi
  else
    warnings+=("free output missing")
  fi
  if command -v vcgencmd >/dev/null 2>&1; then
    throttle_out=$(vcgencmd get_throttled 2>&1 || true)
    throttle_value=$(printf '%s' "${throttle_out}" | awk -F'=' '{print $2}')
    if [ "${throttle_value}" != "0x0" ]; then
      warnings+=("throttled=${throttle_value}")
    fi
  else
    throttle_out="vcgencmd missing"
  fi
  status="pass"
  if [ "${#warnings[@]}" -gt 0 ]; then
    if printf '%s\n' "${warnings[@]}" | grep -q 'available memory'; then
      status="fail"
    else
      status="warn"
    fi
  fi
  message="Temp=${temp_value:-n/a}C, MemAvail=$(python3 -c "import sys; print('{:.2f} GiB'.format(int(sys.argv[1]) / 1024**3))" "${avail_bytes:-0}" 2>/dev/null || echo 'n/a'), Throttle=${throttle_value:-n/a}"
  local details_json
  details_json=$(python3 - "${temp_out}" "${mem_out}" "${avail_bytes:-0}" "${throttle_out:-}" "${warnings[*]}" <<'PY'
import json, sys
print(json.dumps({
    "temperature_raw": sys.argv[1],
    "free_output": sys.argv[2],
    "available_bytes": int(sys.argv[3]) if sys.argv[3].isdigit() else None,
    "throttled_raw": sys.argv[4],
    "warnings": sys.argv[5].split() if sys.argv[5] else [],
}))
PY
  )
  add_check "Health" "${status}" "true" "${message}" "${details_json}"
}

check_repo_presence() {
  local missing=()
  local repos=("sugarkube" "dspace" "token.place")
  for repo in "${repos[@]}"; do
    if [ ! -d "${HOME}/${repo}" ] && [ ! -d "${ROOT_DIR}/../${repo}" ]; then
      missing+=("${repo}")
    fi
  done
  local status message
  if [ "${#missing[@]}" -eq 0 ]; then
    status="pass"
    message="All optional repos present"
  else
    status="warn"
    message="Missing repos: ${missing[*]}"
  fi
  local details_json
  details_json=$(python3 - "$HOME" "${ROOT_DIR}" "${missing[*]}" <<'PY'
import json, os, sys
missing = sys.argv[3].split()
print(json.dumps({
    "home": os.path.expanduser("~"),
    "missing": missing,
}))
PY
  )
  add_check "Repo sync" "${status}" "false" "${message}" "${details_json}"
}

finalize() {
  local exit_status=$1
  python3 - "${RESULTS_TSV}" "${SUMMARY_JSON}" "${SUMMARY_MD}" <<'PY'
import csv, datetime, json, os, sys
results_path, summary_json_path, summary_md_path = sys.argv[1:4]
checks = []
counts = {"pass": 0, "warn": 0, "fail": 0}
required_failures = 0
with open(results_path, newline='') as fh:
    reader = csv.reader(fh, delimiter='\t')
    for row in reader:
        if not row:
            continue
        name, status, required_str, message, details_json = row
        required = required_str.lower() == 'true'
        try:
            details = json.loads(details_json) if details_json else {}
        except json.JSONDecodeError:
            details = {"raw": details_json}
        checks.append({
            "name": name,
            "status": status,
            "required": required,
            "message": message,
            "details": details,
        })
        counts[status] = counts.get(status, 0) + 1
        if required and status == 'fail':
            required_failures += 1
summary = {
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "hostname": os.uname().nodename,
    "checks": checks,
    "counts": counts,
    "required_failures": required_failures,
}
with open(summary_json_path, 'w', encoding='utf-8') as fh:
    json.dump(summary, fh, indent=2)
lines = ["# Spot check summary", "", "| Status | Check | Message |", "| --- | --- | --- |"]
icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
for check in checks:
    lines.append(f"| {icon.get(check['status'], check['status'])} | {check['name']} | {check['message']} |")
lines.append("")
lines.append(f"Pass: {counts.get('pass', 0)}  ")
lines.append(f"Warn: {counts.get('warn', 0)}  ")
lines.append(f"Fail: {counts.get('fail', 0)}  ")
with open(summary_md_path, 'w', encoding='utf-8') as fh:
    fh.write("\n".join(lines) + "\n")
print(json.dumps(summary))
PY
  log "Summary written to ${SUMMARY_JSON} and ${SUMMARY_MD}"
  if [ ${REQUIRED_FAILURE} -ne 0 ]; then
    exit_status=1
  fi
  exit "${exit_status}"
}

trap 'finalize $?' EXIT

log "Starting Raspberry Pi 5 spot check"
check_system_baseline
check_time_locale
check_storage
check_networking
check_link_speed
check_services_logs
check_health
check_repo_presence

log "Spot check complete"
