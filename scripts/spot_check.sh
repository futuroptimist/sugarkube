#!/usr/bin/env bash
# Purpose: Perform a Raspberry Pi 5 Bookworm readiness spot check with artifact summaries.
# Usage: sudo ./scripts/spot_check.sh
set -euo pipefail
IFS=$'\n\t'

log_info()  { echo "[info]  $*"; }
log_warn()  { echo "[warn]  $*"; }
log_fail()  { echo "[fail]  $*"; }
float_lte() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a<=b)}'; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts/spot-check"
LOG_DIR="${ARTIFACT_DIR}"
LOG_FILE="${LOG_DIR}/spot-check.log"
JSON_FILE="${LOG_DIR}/summary.json"
MD_FILE="${LOG_DIR}/summary.md"
mkdir -p "${LOG_DIR}"

exec > >(tee "${LOG_FILE}") 2>&1

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo so hardware and journal data are accessible." >&2
  exit 1
fi

RESULT_DATA=()
PASSED=0
FAILED=0
WARNED=0
INFO=0
REQUIRED_FAILURES=0
START_TIME=$(date --iso-8601=seconds)

status_emoji() {
  case "$1" in
    pass) echo "✅" ;;
    fail) echo "❌" ;;
    warn) echo "⚠️" ;;
    info) echo "ℹ️" ;;
    *) echo "❔" ;;
  esac
}

add_result() {
  local name="$1" status="$2" required="$3" details="$4"
  local encoded
  encoded=$(printf '%s' "$details" | base64 -w0)
  RESULT_DATA+=("${name}|${status}|${required}|${encoded}")
  case "$status" in
    pass) PASSED=$((PASSED + 1)) ;;
    fail)
      FAILED=$((FAILED + 1))
      if [[ "$required" == "true" ]]; then
        REQUIRED_FAILURES=$((REQUIRED_FAILURES + 1))
      fi
      ;;
    warn) WARNED=$((WARNED + 1)) ;;
    info) INFO=$((INFO + 1)) ;;
  esac
  printf '%s %s: %s\n' "$(status_emoji "$status")" "$name" "$details"
}

sanitize_for_log() {
  sed -e 's/[[:space:]]\+$//' <<<"$1"
}

# 1. System baseline
check_system_baseline() {
  local uname_out os_name kernel_version arch ok message
  uname_out=$(uname -a)
  arch=$(uname -m)
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    os_name="${PRETTY_NAME:-${NAME:-unknown}}"
    codename="${VERSION_CODENAME:-unknown}"
  else
    os_name="unknown"
    codename="unknown"
  fi
  kernel_version=$(uname -r | cut -d- -f1)
  IFS='.' read -r kernel_major kernel_minor _ <<<"${kernel_version}.0"
  ok=true
  message="OS=${os_name}; kernel=${kernel_version}; arch=${arch}"
  if [[ "${codename}" != "bookworm" ]]; then
    ok=false
    message+="; expected bookworm codename"
  fi
  if [[ "${arch}" != "aarch64" ]]; then
    ok=false
    message+="; expected aarch64"
  fi
  if [[ ${kernel_major} -lt 6 || ( ${kernel_major} -eq 6 && ${kernel_minor} -lt 12 ) ]]; then
    ok=false
    message+="; kernel must be >= 6.12"
  fi
  if [[ "$ok" == true ]]; then
    add_result "System baseline" "pass" "true" "${message}"
  else
    add_result "System baseline" "fail" "true" "${message}"
  fi
  printf '\n[debug] uname -a\n%s\n' "${uname_out}" >>"${LOG_FILE}" || true
}

# 2. Time and locale
check_time_locale() {
  local timedate_output locale_output ntp timezone lang ok message
  timedate_output=$(timedatectl 2>&1 || true)
  locale_output=$(locale 2>&1 || true)
  ntp=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo "no")
  timezone=$(timedatectl show -p Timezone --value 2>/dev/null || echo "unknown")
  lang=$(printf '%s\n' "${locale_output}" | awk -F= '/^LANG=/{print $2}' | head -n1)
  ok=true
  message="NTP=${ntp}; TZ=${timezone}; LANG=${lang:-unset}"
  if [[ "${ntp}" != "yes" ]]; then
    ok=false
    message+="; enable NTP"
  fi
  if [[ -z "${timezone}" || "${timezone}" == "n/a" ]]; then
    ok=false
    message+="; timezone missing"
  fi
  if [[ -z "${lang}" ]]; then
    ok=false
    message+="; locale LANG unset"
  fi
  if [[ "$ok" == true ]]; then
    add_result "Time & locale" "pass" "true" "${message}"
  else
    add_result "Time & locale" "fail" "true" "${message}"
  fi
  printf '\n[debug] timedatectl\n%s\n' "${timedate_output}" >>"${LOG_FILE}" || true
  printf '\n[debug] locale\n%s\n' "${locale_output}" >>"${LOG_FILE}" || true
}

# 3. Storage overview
check_storage() {
  local storage_json_path storage_vars root_device boot_device root_uuid boot_uuid message ok df_out
  storage_json_path="${LOG_DIR}/storage.json"
  storage_vars=$(python3 - "${storage_json_path}" <<'PY'
import json, subprocess, sys, re

out_path = sys.argv[1]
lsblk_raw = subprocess.check_output([
    "lsblk", "-J", "-o", "NAME,TYPE,SIZE,MOUNTPOINT,FSTYPE"
], text=True)
data = json.loads(lsblk_raw)
blkid_lines = subprocess.check_output(["blkid"], text=True).splitlines()
info_map = {}
for line in blkid_lines:
    if ':' not in line:
        continue
    dev, rest = line.split(':', 1)
    kv = dict(re.findall(r'(\w+)="([^"]*)"', rest))
    info_map[dev] = {
        "UUID": kv.get("UUID"),
        "PARTUUID": kv.get("PARTUUID")
    }

entries = []

def walk(dev):
    name = dev.get("name")
    path = f"/dev/{name}" if name else None
    entry = {
        "device": path,
        "type": dev.get("type"),
        "size": dev.get("size"),
        "mount": dev.get("mountpoint"),
        "fstype": dev.get("fstype"),
        "uuid": info_map.get(path, {}).get("UUID"),
        "partuuid": info_map.get(path, {}).get("PARTUUID"),
    }
    entries.append(entry)
    for child in dev.get("children") or []:
        walk(child)

for device in data.get("blockdevices", []):
    walk(device)

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(entries, fh, indent=2)

root = next((e for e in entries if e.get("mount") == "/"), None)
boot = next((e for e in entries if e.get("mount") == "/boot/firmware"), None)
print(f"ROOT_DEVICE={root.get('device','') if root else ''}")
print(f"ROOT_UUID={root.get('uuid') or root.get('partuuid') if root else ''}")
print(f"BOOT_DEVICE={boot.get('device','') if boot else ''}")
print(f"BOOT_UUID={boot.get('uuid') or boot.get('partuuid') if boot else ''}")
print(f"TABLE_PATH={out_path}")
PY
)
  eval "${storage_vars}"
  df_out=$(df -h)
  printf '\n[debug] df -h\n%s\n' "${df_out}" >>"${LOG_FILE}" || true
  ok=true
  message="/boot/firmware=${BOOT_DEVICE}; /=${ROOT_DEVICE}"
  if [[ "${ROOT_DEVICE}" != "/dev/mmcblk0p2" ]]; then
    ok=false
    message+="; expected /dev/mmcblk0p2"
  fi
  if [[ "${BOOT_DEVICE}" != "/dev/mmcblk0p1" ]]; then
    ok=false
    message+="; expected /dev/mmcblk0p1"
  fi
  if [[ -z "${BOOT_UUID}" || -z "${ROOT_UUID}" ]]; then
    ok=false
    message+="; UUID capture incomplete"
  fi
  if [[ "$ok" == true ]]; then
    add_result "Storage layout" "pass" "true" "${message}"
  else
    add_result "Storage layout" "fail" "true" "${message}"
  fi
}

_parse_ping_summary() {
  local host="$1" out loss avg
  out="$(LC_ALL=C ping -n -q -c 4 -w 5 "$host" 2>&1 || true)"

  local summary rtt
  summary="$(grep -E 'packets transmitted' <<<"$out" || true)"
  rtt="$(grep -E 'min/avg/max' <<<"$out" || true)"

  local loss_pct="100" avg_ms="9999"
  if [[ -n "$summary" ]]; then
    loss_pct="$(awk -F',' '{gsub(/%| /,"",$3); print $3}' <<<"$summary")"
    [[ -z "$loss_pct" ]] && loss_pct="100"
  fi
  if [[ -n "$rtt" ]]; then
    avg_ms="$(awk -F'/' '{print $5}' <<<"$rtt")"
    [[ -z "$avg_ms" ]] && avg_ms="9999"
  fi

  printf '\n[debug] ping %s\n%s\n' "$host" "$out" >>"${LOG_FILE}" || true

  echo "$loss_pct $avg_ms"
}

check_ping_target() {
  local label="$1" host="$2" max_avg_ms="$3" strict="$4"
  read -r loss avg < <(_parse_ping_summary "$host")

  local status msg="loss=${loss}%; avg=${avg}ms"
  if [[ "$strict" == "true" ]]; then
    if [[ "$loss" == "0" ]] && float_lte "$avg" "$max_avg_ms"; then
      status="ok"
    else
      status="fail"
    fi
  else
    if (( loss <= 5 )) && float_lte "$avg" "$max_avg_ms"; then
      status="ok"
    else
      status="warn"
    fi
  fi
  echo "$status|$label $msg"
}

# 4. Networking health
check_networking() {
  local lan_status lan_msg wan_status wan_msg
  local LAN_GATEWAY WAN_TARGET LAN_MAX_AVG_MS WAN_MAX_AVG_MS

  LAN_GATEWAY="${LAN_GATEWAY:-$(ip route | awk '/default/ {print $3; exit}')}"
  WAN_TARGET="${WAN_TARGET:-1.1.1.1}"
  LAN_MAX_AVG_MS="${LAN_MAX_AVG_MS:-10}"
  WAN_MAX_AVG_MS="${WAN_MAX_AVG_MS:-100}"

  if [[ -z "$LAN_GATEWAY" ]]; then
    lan_status="fail"
    lan_msg="LAN loss=100%; avg=9999ms (default gateway unknown)"
  else
    IFS='|' read -r lan_status lan_msg < <(check_ping_target "LAN" "$LAN_GATEWAY" "$LAN_MAX_AVG_MS" true)
  fi
  IFS='|' read -r wan_status wan_msg < <(check_ping_target "WAN" "$WAN_TARGET" "$WAN_MAX_AVG_MS" true)

  local net_required_fail=false overall_status overall_message
  if [[ "$lan_status" == "fail" || "$wan_status" == "fail" ]]; then
    net_required_fail=true
  fi

  overall_message="${lan_msg}; ${wan_msg}"
  if $net_required_fail; then
    overall_status="fail"
  elif [[ "$lan_status" == "warn" || "$wan_status" == "warn" ]]; then
    overall_status="warn"
  else
    overall_status="pass"
  fi

  add_result "Networking" "$overall_status" "true" "$overall_message"
}

_read_link_speed_mbps() {
  local ifname="${1:-eth0}"
  local sys_speed="/sys/class/net/${ifname}/speed"
  if [[ -r "$sys_speed" ]]; then
    cat "$sys_speed" 2>/dev/null || true
    return
  fi
  if command -v ethtool >/dev/null 2>&1; then
    ethtool "$ifname" 2>/dev/null | awk -F': ' '/Speed:/ {gsub(/Mb\/s/,"",$2); print $2; exit}'
  fi
}

check_link_speed() {
  local ifname="${1:-eth0}"
  local min="${MIN_LINK_MBPS:-100}"
  local rec="${RECOMMENDED_LINK_MBPS:-1000}"
  local speed
  speed="$(_read_link_speed_mbps "$ifname")"
  local label="Link speed: ${ifname}=${speed:-unknown}Mb/s; expected >= ${min}Mb/s (recommended ${rec}Mb/s)"

  if [[ -z "$speed" || "$speed" == "unknown" || "$speed" == "0" || "$speed" == "-1" ]]; then
    add_result "Link speed" "fail" "false" "$label"
    return
  fi

  if [[ "$speed" =~ ^[0-9]+$ ]]; then
    if (( speed < min )); then
      add_result "Link speed" "warn" "false" "$label"
      return
    fi

    if (( speed < rec )); then
      add_result "Link speed" "pass" "false" "$label"
      return
    fi
  fi

  add_result "Link speed" "pass" "false" "$label"
}

# 6. Services and logs
check_services_logs() {
  local service_hits log_output
  service_hits=$(systemctl list-unit-files --type=service 2>/dev/null | \
    grep -E 'flywheel|k3s|cloudflared|containerd' || true)
  if [[ -n "${service_hits}" ]]; then
    local service_list
    service_list=$(echo "${service_hits}" | awk '{print $1}' | paste -sd',' -)
    if grep -q 'enabled' <<<"${service_hits}"; then
      add_result "Service inventory" "fail" "true" \
        "Unexpected services enabled: ${service_list}"
    else
      add_result "Service inventory" "warn" "false" \
        "Services present but disabled: ${service_list}"
    fi
  else
    add_result "Service inventory" "pass" "true" "No flywheel/k3s/cloudflared/containerd services"
  fi

  log_output=$(journalctl -b -p3 --no-pager 2>&1 || true)
  local allow='(bluetoothd.*(Failed to init (vcp|mcp|bap) plugin|sap.*(Operation not permitted|driver initialization failed))|wpa_supplicant.*(nl80211: kernel reports: Registration to specific type not supported|bgscan simple: Failed to enable signal strength monitoring))'
  local filtered
  filtered="$(grep -Ev "$allow" <<<"${log_output}" || true)"

  if [[ -n "$filtered" ]]; then
    add_result "Boot errors" "fail" "true" "journalctl -p3 contains unexpected entries (see log)"
  elif [[ -n "$log_output" ]]; then
    add_result "Boot errors" "warn" "true" "Only known benign bluetoothd/wpa_supplicant entries detected"
  else
    add_result "Boot errors" "pass" "true" "No err+ messages in journal"
  fi
  printf '\n[debug] journalctl -b -p3\n%s\n' "${log_output}" >>"${LOG_FILE}" || true
}

# 7. System health
check_health() {
  local temp_output temp_value mem_available throttled_output throttled status message ok
  if command -v vcgencmd >/dev/null 2>&1; then
    temp_output=$(vcgencmd measure_temp 2>&1 || true)
  else
    temp_output="vcgencmd not found"
  fi
  mem_available=$(free -b | awk '/^Mem:/ {print $7}')
  throttled_output=$(vcgencmd get_throttled 2>&1 || true)
  temp_value=$(printf '%s' "${temp_output}" | sed -E 's/[^0-9.]+//g')
  throttled=$(printf '%s' "${throttled_output}" | sed -E 's/.*=//' )
  ok=true
  local avail_mib
  if [[ -n "${mem_available}" ]]; then
    avail_mib=$((mem_available/1024/1024))
  else
    avail_mib=0
  fi
  message="temp=${temp_value:-unknown}°C; available=${avail_mib}MiB; throttled=${throttled}"
  if [[ -z "${temp_value}" ]]; then
    ok=false
    message+="; unable to read temperature"
  elif (( ${temp_value%%.*} >= 60 )); then
    ok=false
    message+="; temp >= 60°C"
  fi
  if [[ -z "${mem_available}" || "${mem_available}" -lt 7516192768 ]]; then
    ok=false
    message+="; available RAM < 7Gi"
  fi
  if [[ "${throttled}" != "0x0" ]]; then
    ok=false
    message+="; throttling detected"
  fi
  if [[ "$ok" == true ]]; then
    add_result "System health" "pass" "true" "${message}"
  else
    add_result "System health" "fail" "true" "${message}"
  fi
  printf '\n[debug] vcgencmd measure_temp\n%s\n' "${temp_output}" >>"${LOG_FILE}" || true
  printf '\n[debug] vcgencmd get_throttled\n%s\n' "${throttled_output}" >>"${LOG_FILE}" || true
}

# 8. Repo sync check (optional)
check_repo_sync() {
  local missing=()
  for repo in sugarkube dspace token.place; do
    local path="/home/pi/${repo}"
    if [[ -d "${path}" ]]; then
      continue
    fi
    missing+=("${repo}")
  done
  if (( ${#missing[@]} == 0 )); then
    add_result "Repo sync" "info" "false" "sugarkube/dspace/token.place present"
  else
    add_result "Repo sync" "warn" "false" "Missing repos: ${missing[*]}"
  fi
}

write_summaries() {
  local end_time
  end_time=$(date --iso-8601=seconds)
  python3 - "$JSON_FILE" "$MD_FILE" "$START_TIME" "$end_time" \
    "${PASSED}" "${FAILED}" "${WARNED}" "${INFO}" "${REQUIRED_FAILURES}" \
    "${RESULT_DATA[@]}" <<'PY'
import base64
import json
import sys
from textwrap import dedent

json_path = sys.argv[1]
md_path = sys.argv[2]
started = sys.argv[3]
ended = sys.argv[4]
passed = int(sys.argv[5])
failed = int(sys.argv[6])
warned = int(sys.argv[7])
info = int(sys.argv[8])
required_failures = int(sys.argv[9])
entries = []
for raw in sys.argv[10:]:
    name, status, required, encoded = raw.split('|', 3)
    details = base64.b64decode(encoded.encode()).decode()
    entries.append({
        "name": name,
        "status": status,
        "required": required.lower() == "true",
        "details": details,
    })
summary = {
    "started_at": started,
    "finished_at": ended,
    "counts": {
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "info": info,
    },
    "required_failures": required_failures,
    "checks": entries,
}
with open(json_path, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=2)
lines = [
    f"# Raspberry Pi spot check",
    "",
    f"* Started: {started}",
    f"* Finished: {ended}",
    "",
    "| Status | Required | Check | Details |",
    "|--------|----------|-------|---------|",
]
status_map = {
    "pass": "✅",
    "fail": "❌",
    "warn": "⚠️",
    "info": "ℹ️",
}
for entry in entries:
    status_icon = status_map.get(entry["status"], "❔")
    required = "yes" if entry["required"] else "no"
    details = entry["details"].replace("\n", "<br>")
    lines.append(f"| {status_icon} | {required} | {entry['name']} | {details} |")
with open(md_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
PY
}

main() {
  printf '\n=== Raspberry Pi 5 Bookworm spot check ===\n'
  check_system_baseline
  check_time_locale
  check_storage
  check_networking
  check_link_speed
  check_services_logs
  check_health
  check_repo_sync
  write_summaries
  if (( REQUIRED_FAILURES > 0 )); then
    printf '\n❌ Required checks failed (%d). See %s.\n' "${REQUIRED_FAILURES}" "${LOG_FILE}"
    exit 1
  fi
  printf '\n✅ Spot check complete. Artifacts: %s\n' "${ARTIFACT_DIR}"
}

main "$@"
