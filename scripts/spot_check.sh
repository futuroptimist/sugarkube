#!/usr/bin/env bash
# spot_check.sh — run Pi 5 Bookworm baseline validation and emit JSON/Markdown summaries.
# Usage: just spot-check (rerunnable; exits non-zero when required checks fail).

set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo --preserve-env=ARTIFACT_ROOT "$0" "$@"
fi

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_ROOT_DIR="${ARTIFACT_ROOT:-${REPO_ROOT}/artifacts}"
ARTIFACT_DIR="${ARTIFACT_ROOT_DIR}/spot-check"
SUMMARY_JSON="${ARTIFACT_DIR}/summary.json"
SUMMARY_MD="${ARTIFACT_DIR}/summary.md"
LOG_FILE="${ARTIFACT_DIR}/spot-check.log"
TMP_DATA_FILE="${ARTIFACT_DIR}/checks.tsv"

mkdir -p "${ARTIFACT_DIR}"
: >"${TMP_DATA_FILE}"
touch "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

declare -a CHECK_STORE=()
REQUIRED_FAILURES=0

cleanup() {
  local exit_code=$?
  generate_summaries "${exit_code}"
}
trap cleanup EXIT

generate_summaries() {
  local exit_code="$1"
  python3 - <<'PY' "${TMP_DATA_FILE}" "${SUMMARY_JSON}" "${SUMMARY_MD}" "${REQUIRED_FAILURES}" "${exit_code}"
import base64
import json
import sys
from pathlib import Path

checks_path = Path(sys.argv[1])
summary_json = Path(sys.argv[2])
summary_md = Path(sys.argv[3])
required_failures = int(sys.argv[4])
exit_code = int(sys.argv[5])
checks = []
if checks_path.exists():
    for raw in checks_path.read_text().splitlines():
        if not raw:
            continue
        cid, status, required, msg_b64, detail_b64 = raw.split('\t')
        message = base64.b64decode(msg_b64.encode()).decode(errors="replace")
        details = base64.b64decode(detail_b64.encode()).decode(errors="replace")
        checks.append({
            "id": cid,
            "status": status,
            "required": required == "true",
            "message": message,
            "details": details,
        })
summary = {
    "required_failures": required_failures,
    "exit_code": exit_code,
    "checks": checks,
}
summary_json.write_text(json.dumps(summary, indent=2) + "\n")

lines = ["| Check | Status | Message |", "| --- | --- | --- |"]
for check in checks:
    icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(check["status"], "❔")
    lines.append(f"| {check['id']} | {icon} | {check['message']} |")
summary_md.write_text("\n".join(lines) + "\n")
PY
}

record_check() {
  local id="$1" status="$2" required="$3" message="$4" details="${5:-}"
  local icon="❔"
  case "${status}" in
    pass) icon="✅" ;;
    warn) icon="⚠️" ;;
    fail) icon="❌" ;;
  esac
  printf '%s %s: %s\n' "${icon}" "${id}" "${message}"
  if [[ "${status}" == "fail" && "${required}" == "true" ]]; then
    REQUIRED_FAILURES=$((REQUIRED_FAILURES + 1))
  fi
  local message_b64 details_b64
  message_b64=$(printf '%s' "${message}" | base64 -w0)
  details_b64=$(printf '%s' "${details}" | base64 -w0)
  printf '%s\t%s\t%s\t%s\t%s\n' "${id}" "${status}" "${required}" "${message_b64}" "${details_b64}" >>"${TMP_DATA_FILE}"
}

version_ge() {
  local left="$1" right="$2"
  dpkg --compare-versions "${left}" ge "${right}"
}

# System baseline
uname_full=$(uname -a)
uname_kernel=$(uname -r)
kernel_base="${uname_kernel%%-*}"
arch=$(uname -m)
. /etc/os-release
os_info="${PRETTY_NAME} (${VERSION_CODENAME})"
base_details=$(printf 'uname: %s\nos-release: %s\narch: %s\n' "${uname_full}" "${os_info}" "${arch}")
if [[ "${arch}" == "aarch64" ]] && version_ge "${kernel_base}" "6.12" && [[ "${VERSION_CODENAME}" == "bookworm" ]]; then
  record_check "system" "pass" "true" "Bookworm aarch64 kernel ${uname_kernel}" "${base_details}"
else
  record_check "system" "fail" "true" "Unexpected base system (want Bookworm aarch64 ≥6.12)" "${base_details}"
fi

# Time and locale
Timedate_file="${ARTIFACT_DIR}/timedatectl.txt"
Locale_file="${ARTIFACT_DIR}/locale.txt"
timedatectl status >"${Timedate_file}" || true
locale >"${Locale_file}" || true
ntp_sync=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)
timezone=$(timedatectl show -p Timezone --value 2>/dev/null || true)
if [[ -z "${ntp_sync}" ]]; then
  ntp_sync=$(grep -E 'System clock synchronized' "${Timedate_file}" | awk '{print $4}' | tail -n1)
fi
if [[ "${ntp_sync}" =~ ^(yes|1)$ ]] && [[ -n "${timezone}" && "${timezone}" != "n/a" ]]; then
  record_check "time" "pass" "true" "NTP synced (timezone ${timezone})" "timedatectl=$(<"${Timedate_file}")"
else
  record_check "time" "fail" "true" "Clock or timezone not set (NTP=${ntp_sync:-no})" "timedatectl=$(<"${Timedate_file}")"
fi

# Storage
DF_file="${ARTIFACT_DIR}/df-h.txt"
LSBLK_file="${ARTIFACT_DIR}/lsblk.txt"
BLKID_file="${ARTIFACT_DIR}/blkid.txt"
df -h >"${DF_file}"
lsblk -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINT,UUID >"${LSBLK_file}"
blkid >"${BLKID_file}" || true
lsblk_json=$(lsblk -J -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINT,UUID)
printf '%s\n' "${lsblk_json}" >"${ARTIFACT_DIR}/lsblk.json"
boot_mount=$(echo "${lsblk_json}" | jq -r '..|objects|select(.name=="mmcblk0p1")|.mountpoint // empty' | head -n1)
root_mount=$(echo "${lsblk_json}" | jq -r '..|objects|select(.name=="mmcblk0p2")|.mountpoint // empty' | head -n1)
boot_uuid=$(echo "${lsblk_json}" | jq -r '..|objects|select(.name=="mmcblk0p1")|.uuid // empty' | head -n1)
root_uuid=$(echo "${lsblk_json}" | jq -r '..|objects|select(.name=="mmcblk0p2")|.uuid // empty' | head -n1)
storage_table=$(echo "${lsblk_json}" | jq -r '["DEVICE","FSTYPE","SIZE","MOUNT","UUID"], (..|objects|select(.type=="disk" or .type=="part")|[.name, .fstype // "-", .size // "-", .mountpoint // "-", .uuid // "-"])|@tsv')
printf '%s\n' "${storage_table}" >"${ARTIFACT_DIR}/storage.tsv"
if [[ "${boot_mount}" == "/boot/firmware" && "${root_mount}" == "/" ]]; then
  record_check "storage" "pass" "true" "/boot/firmware=${boot_uuid} / = ${root_uuid}" "$(<"${ARTIFACT_DIR}/storage.tsv")"
else
  record_check "storage" "fail" "true" "Unexpected mounts (boot=${boot_mount:-none} root=${root_mount:-none})" "$(<"${ARTIFACT_DIR}/storage.tsv")"
fi

# Networking - ping LAN and WAN
PING_DIR="${ARTIFACT_DIR}/ping"
mkdir -p "${PING_DIR}"
default_gw=$(ip route | awk '/default/ {print $3; exit}')
run_ping() {
  local host="$1" label="$2" required="$3"
  local outfile="${PING_DIR}/${label}.txt"
  if ping -c 3 -q "$host" >"${outfile}" 2>&1; then
    local loss avg
    loss=$(awk -F', ' 'NR==2 {print $3}' "${outfile}" | awk '{print $1}')
    avg=$(awk -F'/' 'END{print $5}' "${outfile}")
    if [[ "${loss}" == "0%" || "${loss}" == "0.0%" ]]; then
      record_check "ping-${label}" "pass" "${required}" "${label} latency avg ${avg:-unknown} ms" "$(<"${outfile}")"
    else
      record_check "ping-${label}" "fail" "${required}" "Packet loss ${loss:-unknown} to ${label}" "$(<"${outfile}")"
    fi
  else
    record_check "ping-${label}" "fail" "${required}" "Ping to ${label} failed" "$(<"${outfile}" 2>/dev/null || true)"
  fi
}
if [[ -n "${default_gw}" ]]; then
  run_ping "${default_gw}" "lan" "true"
else
  record_check "ping-lan" "fail" "true" "No default gateway detected" "ip route returned no default"
fi
run_ping "1.1.1.1" "wan" "true"

# Link speed
link_details=""
link_speed=""
if command -v ethtool >/dev/null 2>&1; then
  link_details=$(ethtool eth0 2>&1 || true)
  link_speed=$(printf '%s\n' "${link_details}" | awk -F': ' '/Speed:/ {print $2; exit}')
elif command -v nmcli >/dev/null 2>&1; then
  link_details=$(nmcli dev show eth0 2>&1 || true)
  link_speed=$(printf '%s\n' "${link_details}" | awk -F': ' '/GENERAL.SPEED/ {print $2; exit}')
fi
if [[ -n "${link_speed}" ]]; then
  if [[ "${link_speed}" =~ 1000 ]]; then
    record_check "link" "pass" "false" "eth0 ${link_speed}" "${link_details}"
  else
    record_check "link" "warn" "false" "eth0 ${link_speed:-unknown}" "${link_details}"
  fi
else
  record_check "link" "warn" "false" "Unable to determine eth0 speed" "${link_details:-No ethtool/nmcli output}"
fi

# Services and logs
svc_file="${ARTIFACT_DIR}/services.txt"
log_file="${ARTIFACT_DIR}/journal.txt"
systemctl list-unit-files --type=service >"${svc_file}" || true
journalctl -b -p 3 --no-pager >"${log_file}" 2>&1 || true
svc_hits=$(grep -E '^(flywheel|k3s|cloudflared|containerd).*enabled' "${svc_file}" || true)
filtered_logs=$(grep -Ev '(bluetoothd.*(Failed to set|Failed to load)|wpa_supplicant.*bgscan simple)' "${log_file}" || true)
if [[ -n "${svc_hits}" ]]; then
  record_check "services" "fail" "true" "Unexpected services enabled" "${svc_hits}"
else
  record_check "services" "pass" "true" "No flywheel/k3s/cloudflared/containerd services active" "$(<"${svc_file}")"
fi
if [[ -n "${filtered_logs}" ]]; then
  record_check "logs" "warn" "false" "Review journal priority 3 entries" "${filtered_logs}"
else
  record_check "logs" "pass" "false" "No unexpected journal errors" "$(<"${log_file}")"
fi

# Health metrics
health_dir="${ARTIFACT_DIR}/health"
mkdir -p "${health_dir}"
temp_raw=$(vcgencmd measure_temp 2>&1 || true)
throttle_raw=$(vcgencmd get_throttled 2>&1 || true)
free_raw=$(free -b 2>&1 || true)
printf '%s\n' "${temp_raw}" >"${health_dir}/temp.txt"
printf '%s\n' "${throttle_raw}" >"${health_dir}/throttle.txt"
printf '%s\n' "${free_raw}" >"${health_dir}/free.txt"
avail_bytes=$(printf '%s\n' "${free_raw}" | awk '/Mem:/ {print $7}')
if [[ -z "${avail_bytes}" ]]; then
  avail_bytes=0
fi
temp_c=$(printf '%s\n' "${temp_raw}" | sed -E 's/.*=([0-9.]+).*/\1/' )
if [[ -n "${temp_c}" && "${temp_c%.*}" -lt 60 ]]; then
  record_check "temp" "pass" "true" "Idle temp ${temp_c}°C" "${temp_raw}"
else
  record_check "temp" "fail" "true" "High idle temp ${temp_c:-unknown}" "${temp_raw}"
fi
if [[ "${avail_bytes}" -ge 7516192768 ]]; then
  record_check "memory" "pass" "true" "Available memory $((avail_bytes / 1024 / 1024)) MiB" "${free_raw}"
else
  record_check "memory" "warn" "false" "Available memory below 7GiB ($((avail_bytes / 1024 / 1024)) MiB)" "${free_raw}"
fi
throttle_flag=$(printf '%s\n' "${throttle_raw}" | sed -E 's/throttled=//' )
if [[ "${throttle_flag}" == "0x0" ]]; then
  record_check "throttle" "pass" "true" "No throttling detected" "${throttle_raw}"
else
  record_check "throttle" "warn" "false" "Throttle flags ${throttle_flag}" "${throttle_raw}"
fi

# Optional repo sync
expected_repos=(sugarkube dspace token.place)
found_repos=()
missing_repos=()
for repo in "${expected_repos[@]}"; do
  if compgen -G "/home/*/${repo}" >/dev/null 2>&1; then
    found_repos+=("${repo}")
  else
    missing_repos+=("${repo}")
  fi
fi
repo_message="Found: ${found_repos[*]:-none}; Missing: ${missing_repos[*]:-none}"
record_check "repos" "warn" "false" "${repo_message}" "checked /home/* paths"

# Final exit code is based on required failures tracked in record_check
if (( REQUIRED_FAILURES > 0 )); then
  exit 1
fi
exit 0
