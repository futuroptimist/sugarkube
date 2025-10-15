#!/usr/bin/env bash
# spot_check.sh - Run Pi 5 + Bookworm readiness checks with JSON and Markdown summaries.
# Usage: scripts/spot_check.sh
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/spot-check"
mkdir -p "${ARTIFACT_DIR}"
SUMMARY_JSON="${ARTIFACT_DIR}/summary.json"
SUMMARY_MD="${ARTIFACT_DIR}/summary.md"
RAW_DIR="${ARTIFACT_DIR}/raw"
mkdir -p "${RAW_DIR}"

CHECKS_FILE="$(mktemp)"
trap 'rm -f "${CHECKS_FILE}"' EXIT

declare -a SUMMARY_LINES=()
FAILURES=0

symbol_for_status() {
  case "$1" in
    pass) printf '✅' ;;
    warn) printf '⚠️' ;;
    fail) printf '❌' ;;
    *) printf '❓' ;;
  esac
}

record_check() {
  local id="$1" label="$2" status="$3" required="$4" detail="$5" data="$6"
  detail="${detail//$'\n'/ }"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$id" "$label" "$status" "$required" "$detail" "$data" >>"${CHECKS_FILE}"
  SUMMARY_LINES+=("${status}|${label}|${detail}")
  if [[ "$status" == "fail" && "$required" == "true" ]]; then
    FAILURES=1
  fi
}

save_output() {
  local name="$1"
  local file="${RAW_DIR}/${name}.txt"
  shift
  "$@" >"${file}" 2>&1 || true
  echo "${file}"
}

check_system_baseline() {
  local uname_out kernel arch codename version hostname status detail
  uname_out="$(uname -a)"
  kernel="$(uname -r)"
  arch="$(uname -m)"
  hostname="$(hostname)"
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    codename="${VERSION_CODENAME:-unknown}"
    version="${PRETTY_NAME:-${NAME:-unknown}}"
  else
    codename="unknown"
    version="unknown"
  fi
  local kernel_ok=0
  IFS='.-' read -r k_major k_minor _ <<<"${kernel}"
  if [[ -n "${k_major}" && -n "${k_minor}" ]] && (( k_major > 6 || (k_major == 6 && k_minor >= 12) )); then
    kernel_ok=1
  fi
  if [[ "${arch}" == "aarch64" && "${codename}" == "bookworm" && ${kernel_ok} -eq 1 ]]; then
    status="pass"
  else
    status="fail"
  fi
  detail="${version} (${codename}) kernel ${kernel} on ${arch} host ${hostname}"
  printf '%s\n' "${uname_out}" >"${RAW_DIR}/uname.txt"
  record_check "system" "System baseline" "${status}" "true" "${detail}" "{}"
}

check_time_locale() {
  local tz ntp_sync lang status detail
  tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo unknown)"
  ntp_sync="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo no)"
  lang="$(locale | awk -F= '$1=="LANG" {print $2}' | head -n1)"
  local ok=true
  if [[ "${ntp_sync}" != "yes" ]]; then
    ok=false
  fi
  if [[ -z "${tz}" || "${tz}" == "n/a" ]]; then
    ok=false
  fi
  if [[ -z "${lang}" ]]; then
    ok=false
  fi
  if ${ok}; then
    status="pass"
  else
    status="fail"
  fi
  save_output "timedatectl" timedatectl status
  save_output "locale" locale
  detail="TZ=${tz} NTP=${ntp_sync} LANG=${lang:-unset}"
  record_check "time" "Time & locale" "${status}" "true" "${detail}" "{}"
}

build_storage_table() {
  python3 - <<'PY'
import json, subprocess
lsblk = subprocess.check_output([
    "lsblk", "--json", "-o", "NAME,TYPE,SIZE,MOUNTPOINT,FSTYPE"
], text=True)
data = json.loads(lsblk)
rows = []

def walk(entries, parent=None):
    for entry in entries:
        if entry.get("type") == "part":
            name = entry.get("name")
            device = f"/dev/{name}"
            fstype = entry.get("fstype") or ""
            size = entry.get("size") or ""
            mount = entry.get("mountpoint") or ""
            uuid = ""
            for key in ("PARTUUID", "UUID"):
                try:
                    uuid = subprocess.check_output(
                        ["blkid", "-s", key, "-o", "value", device],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip()
                except subprocess.CalledProcessError:
                    continue
                if uuid:
                    break
            rows.append({
                "device": device,
                "fstype": fstype,
                "size": size,
                "mount": mount,
                "uuid": uuid,
            })
        if entry.get("children"):
            walk(entry["children"], entry)

walk(data.get("blockdevices", []))
print(json.dumps(rows))
PY
}

check_storage() {
  local df_file lsblk_file table_json root_src boot_src status detail
  df_file="$(save_output "df" df -h)"
  lsblk_file="$(save_output "lsblk" lsblk -o NAME,TYPE,SIZE,MOUNTPOINT,FSTYPE)"
  table_json="$(build_storage_table)"
  printf '%s\n' "${table_json}" >"${ARTIFACT_DIR}/storage.json"
  root_src="$(findmnt -n -o SOURCE / || true)"
  boot_src="$(findmnt -n -o SOURCE /boot/firmware || true)"
  if [[ "${root_src}" == "/dev/mmcblk0p2" && "${boot_src}" == "/dev/mmcblk0p1" ]]; then
    status="pass"
  else
    status="fail"
  fi
  detail="root=${root_src:-unknown} boot=${boot_src:-unknown}"
  record_check "storage" "Storage layout" "${status}" "true" "${detail}" "${table_json}"
}

run_ping() {
  local host="$1" label="$2" outfile loss avg status
  outfile="${RAW_DIR}/ping-${label}.txt"
  if ping -c 4 -w 5 "${host}" >"${outfile}" 2>&1; then
    loss="$(awk -F',' '/packets transmitted/ {gsub(/%/, "", $3); gsub(/[^0-9.]/, "", $3); print $3}' "${outfile}" | head -n1)"
    avg="$(awk -F'/' 'END {print $5}' "${outfile}" || true)"
    if [[ -z "${loss}" ]]; then
      loss=0
    fi
    if (( ${loss%.*} == 0 )); then
      status="pass"
    else
      status="fail"
    fi
  else
    loss=100
    avg=0
    status="fail"
  fi
  printf '%s\t%s\t%s\n' "${label}" "${loss}" "${avg}" >>"${RAW_DIR}/ping-summary.tsv"
  echo "${status}|loss=${loss}% avg=${avg}ms"
}

check_network() {
  local gateway lan_result wan_result status detail
  rm -f "${RAW_DIR}/ping-summary.tsv"
  gateway="$(ip route | awk '/default/ {print $3; exit}')"
  if [[ -n "${gateway}" ]]; then
    lan_result="$(run_ping "${gateway}" "lan")"
  else
    lan_result="fail|no default gateway"
  fi
  wan_result="$(run_ping "1.1.1.1" "wan")"
  local lan_status="${lan_result%%|*}" lan_detail="${lan_result#*|}"
  local wan_status="${wan_result%%|*}" wan_detail="${wan_result#*|}"
  if [[ "${lan_status}" == "pass" && "${wan_status}" == "pass" ]]; then
    status="pass"
  else
    status="fail"
  fi
  detail="LAN ${lan_detail}; WAN ${wan_detail}"
  record_check "network" "Networking" "${status}" "true" "${detail}" "{}"
}

check_link_speed() {
  local speed status detail
  speed=""
  if command -v ethtool >/dev/null 2>&1; then
    speed="$(ethtool eth0 2>/dev/null | awk -F': ' '/Speed:/ {print $2}' | head -n1 | tr -d ' ')"
  fi
  if [[ -z "${speed}" ]] && command -v nmcli >/dev/null 2>&1; then
    speed="$(nmcli dev show eth0 2>/dev/null | awk -F': *' '/GENERAL.SPEED:/ {print $2}' | head -n1 | tr -d ' ')"
  fi
  if [[ -z "${speed}" ]]; then
    status="warn"
    detail="eth0 speed unavailable"
  else
    local numeric
    numeric="${speed//[^0-9]/}"
    if [[ -n "${numeric}" && ${numeric} -lt 1000 ]]; then
      status="warn"
    else
      status="pass"
    fi
    detail="eth0 ${speed}"
  fi
  record_check "link" "Ethernet link" "${status}" "false" "${detail}" "{}"
}

check_services_logs() {
  local offenders journal raw_journal filtered status detail
  offenders="$(systemctl list-units --type=service --state=running 2>/dev/null | grep -E 'flywheel|k3s|cloudflared|containerd' || true)"
  raw_journal="${RAW_DIR}/journal-priority-3.txt"
  journalctl -b -p 3 --no-pager >"${raw_journal}" 2>&1 || true
  filtered="$(grep -Ev -e 'Bluetooth:.*(vcp|mcp|bap)' -e 'wpa_supplicant: bgscan simple' "${raw_journal}" || true)"
  if [[ -n "${offenders}" ]]; then
    status="fail"
    detail="Unexpected services active"
  elif [[ -n "${filtered}" ]]; then
    status="fail"
    detail="Unexpected journal errors"
  else
    status="pass"
    detail="No unexpected services or errors"
  fi
  record_check "services" "Services & logs" "${status}" "true" "${detail}" "{}"
}

check_health() {
  local temp_line temp_c throttled mem_available status detail
  if command -v vcgencmd >/dev/null 2>&1; then
    temp_line="$(vcgencmd measure_temp 2>/dev/null || true)"
    temp_c="$(printf '%s' "${temp_line}" | sed -E 's/.*=([0-9.]+).*/\1/')"
  else
    temp_c=""
  fi
  if command -v vcgencmd >/dev/null 2>&1; then
    throttled="$(vcgencmd get_throttled 2>/dev/null | sed 's/throttled=//')"
  else
    throttled="unknown"
  fi
  mem_available="$(free --mebi | awk 'NR==2 {print $7}' 2>/dev/null || echo 0)"
  status="pass"
  if [[ -n "${temp_c}" && $(printf '%.0f' "${temp_c}") -ge 60 ]]; then
    status="fail"
  fi
  if [[ "${throttled}" != "0x0" ]]; then
    status="fail"
  fi
  if [[ "${mem_available}" -lt 7168 ]]; then
    status="fail"
  fi
  local mem_gi
  mem_gi=$(awk -v val="${mem_available}" 'BEGIN {printf "%.2f", val/1024}')
  detail="temp=${temp_c:-n/a}C throttle=${throttled:-n/a} mem_avail=${mem_gi}Gi"
  record_check "health" "Health" "${status}" "true" "${detail}" "{}"
}

check_repos() {
  local base="/home/pi" missing=()
  local repos=(sugarkube dspace token.place)
  for repo in "${repos[@]}"; do
    if [[ ! -d "${base}/${repo}" ]]; then
      missing+=("${repo}")
    fi
  done
  local status detail
  if [[ ${#missing[@]} -eq 0 ]]; then
    status="pass"
    detail="All expected repos present"
  else
    status="warn"
    detail="Missing repos: ${missing[*]}"
  fi
  record_check "repos" "Repo sync" "${status}" "false" "${detail}" "{}"
}

emit_reports() {
  python3 - "${CHECKS_FILE}" "${SUMMARY_JSON}" "${SUMMARY_MD}" <<'PY'
import json, sys, pathlib
checks_file, json_path, md_path = map(pathlib.Path, sys.argv[1:4])
rows = []
with checks_file.open("r", encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        check_id, label, status, required, detail, data = line.split("\t")
        payload = {
            "id": check_id,
            "label": label,
            "status": status,
            "required": required == "true",
            "detail": detail,
        }
        if data and data != "{}":
            try:
                payload["data"] = json.loads(data)
            except json.JSONDecodeError:
                payload["data"] = data
        rows.append(payload)
json_path.write_text(json.dumps({"checks": rows}, indent=2) + "\n", encoding="utf-8")
md_lines = ["| Check | Status | Detail |", "| --- | --- | --- |"]
for row in rows:
    emoji = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(row["status"], "❔")
    md_lines.append(f"| {row['label']} | {emoji} | {row['detail']} |")
md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
PY
}

print_summary() {
  echo "Raspberry Pi image spot check summary:"
  for summary_entry in "${SUMMARY_LINES[@]}"; do
    IFS='|' read -r status label detail <<<"${summary_entry}"
    printf '%s %s — %s\n' "$(symbol_for_status "${status}")" "${label}" "${detail}"
  done
}

check_system_baseline
check_time_locale
check_storage
check_network
check_link_speed
check_services_logs
check_health
check_repos
emit_reports
print_summary

if [[ ${FAILURES} -ne 0 ]]; then
  exit 1
fi
