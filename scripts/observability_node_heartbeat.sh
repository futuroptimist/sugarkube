#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_ROOT="${SUGARKUBE_HEARTBEAT_ROOT:-}"
SYSTEMCTL="${SUGARKUBE_SYSTEMCTL:-systemctl}"
INVENTORY="${ROOT}/config/staging-nodes.txt"
UNIT_DIR="${DEST_ROOT}/etc/systemd/system"
LIBEXEC_DIR="${DEST_ROOT}/usr/local/libexec"
CREDENTIAL_DIR="${DEST_ROOT}/etc/sugarkube"
CREDENTIAL="${CREDENTIAL_DIR}/healthchecks-heartbeat.url"
SERVICE=sugarkube-healthchecks-heartbeat.service
TIMER=sugarkube-healthchecks-heartbeat.timer

die() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-2}"; }
validate_env() {
  [[ "${1:-}" == staging ]] || die "pass env=staging explicitly; production and unknown environments are unsupported"
}
hostname_short() { "${SUGARKUBE_HOSTNAME_CMD:-hostname}" -s 2>/dev/null || "${SUGARKUBE_HOSTNAME_CMD:-hostname}"; }
validate_host() {
  HOST="$(hostname_short)" || die "could not resolve hostname"
  grep -Fxq -- "${HOST}" "${INVENTORY}" || die "host is not a canonical staging node"
}
require_tool() { command -v "$1" >/dev/null 2>&1 || die "required tool is unavailable: $1"; }
as_root() {
  if [[ -n "${DEST_ROOT}" || "$(id -u)" -eq 0 ]]; then "$@"; else sudo "$@"; fi
}
validate_url() {
  local value=$1
  [[ "${value}" =~ ^https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]
}
install_heartbeat() {
  [[ -t 0 && -t 1 && -r /dev/tty ]] || die "installation requires an interactive controlling terminal"
  local url tmp extra=''
  IFS= read -r -s -p 'Rotated Healthchecks.io ping URL: ' url </dev/tty
  # Reject a pasted second line without ever displaying either line.
  IFS= read -r -s -t 0.1 extra </dev/tty || true
  printf '\n' >/dev/tty
  [[ -z "${extra}" ]] || die "ping URL rejected (value redacted)"
  validate_url "${url}" || die "ping URL rejected (value redacted)"
  require_tool install; require_tool "${SYSTEMCTL}"
  as_root install -d -m 0755 "${UNIT_DIR}" "${LIBEXEC_DIR}"
  as_root install -d -m 0700 -o root -g root "${CREDENTIAL_DIR}"
  as_root install -m 0755 "${ROOT}/scripts/healthchecks-heartbeat.sh" "${LIBEXEC_DIR}/sugarkube-healthchecks-heartbeat"
  as_root install -m 0644 "${ROOT}/scripts/systemd/${SERVICE}" "${UNIT_DIR}/${SERVICE}"
  as_root install -m 0644 "${ROOT}/scripts/systemd/${TIMER}" "${UNIT_DIR}/${TIMER}"
  tmp="${CREDENTIAL}.new.$$"
  trap '[[ -z "${tmp:-}" ]] || as_root rm -f "${tmp}"' EXIT
  umask 077
  printf '%s\n' "${url}" | as_root tee "${tmp}" >/dev/null
  as_root chown root:root "${tmp}"
  as_root chmod 0600 "${tmp}"
  as_root mv -f "${tmp}" "${CREDENTIAL}"
  tmp=''
  trap - EXIT
  unset url
  as_root "${SYSTEMCTL}" daemon-reload
  as_root "${SYSTEMCTL}" enable "${TIMER}"
  as_root "${SYSTEMCTL}" start "${TIMER}"
  printf 'Installed heartbeat for %s; credential value redacted.\n' "${HOST}"
}
status_heartbeat() {
  printf 'hostname: %s\n' "${HOST}"
  for path in "${CREDENTIAL}" "${UNIT_DIR}/${SERVICE}" "${UNIT_DIR}/${TIMER}" "${LIBEXEC_DIR}/sugarkube-healthchecks-heartbeat"; do
    if [[ -e "${path}" ]]; then
      printf 'asset: present %s owner=%s mode=%s\n' "${path}" \
        "$(stat -c %U:%G "${path}")" "$(stat -c %a "${path}")"
    else
      printf 'asset: missing %s\n' "${path}"
    fi
  done
  printf 'timer enabled: %s\n' "$("${SYSTEMCTL}" is-enabled "${TIMER}" 2>/dev/null || printf inactive)"
  printf 'timer active: %s\n' "$("${SYSTEMCTL}" is-active "${TIMER}" 2>/dev/null || printf inactive)"
  printf 'last service result: %s\n' "$("${SYSTEMCTL}" show "${SERVICE}" -p Result --value 2>/dev/null || printf unavailable)"
  printf 'timing: boot=30s period=1min accuracy=5s\n'
}
verify_heartbeat() {
  "${SYSTEMCTL}" is-enabled --quiet "${TIMER}" || die "timer is not enabled"
  "${SYSTEMCTL}" is-active --quiet "${TIMER}" || die "timer is not active"
  as_root "${SYSTEMCTL}" start "${SERVICE}" || die "heartbeat failed (diagnostics redacted)" 4
  local result
  for _ in {1..15}; do
    result="$("${SYSTEMCTL}" show "${SERVICE}" -p Result --value 2>/dev/null || true)"
    [[ "${result}" == success ]] && { printf 'Heartbeat verification succeeded for %s; timer remains enabled.\n' "${HOST}"; return; }
    sleep 1
  done
  die "heartbeat did not complete successfully within 15 seconds (details redacted)" 4
}
uninstall_heartbeat() {
  [[ "${SUGARKUBE_HEARTBEAT_CONFIRM:-}" == REMOVE ]] || die "set SUGARKUBE_HEARTBEAT_CONFIRM=REMOVE to confirm destructive credential deletion"
  require_tool "${SYSTEMCTL}"
  as_root "${SYSTEMCTL}" disable --now "${TIMER}" 2>/dev/null || true
  as_root rm -f "${UNIT_DIR}/${SERVICE}" "${UNIT_DIR}/${TIMER}" "${LIBEXEC_DIR}/sugarkube-healthchecks-heartbeat" "${CREDENTIAL}"
  as_root "${SYSTEMCTL}" daemon-reload
  printf 'Removed repository-owned heartbeat assets for %s. Remote Healthchecks.io and PagerDuty configuration was not deleted.\n' "${HOST}"
}

action="${1:-}"; env="${2:-}"
validate_env "${env}"; validate_host
case "${action}" in
  install) install_heartbeat ;;
  status) require_tool "${SYSTEMCTL}"; status_heartbeat ;;
  verify) require_tool "${SYSTEMCTL}"; verify_heartbeat ;;
  uninstall) uninstall_heartbeat ;;
  *) die "usage: $0 {install|status|verify|uninstall} staging" ;;
esac
