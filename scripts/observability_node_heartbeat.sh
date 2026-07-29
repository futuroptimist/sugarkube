#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${SUGARKUBE_HEARTBEAT_ROOT:-}"
SYSTEMD_DIR="${ROOT}/etc/systemd/system"
CREDENTIAL_DIR="${ROOT}/etc/sugarkube/node-heartbeat"
LIBEXEC_DIR="${ROOT}/usr/local/libexec"
INVENTORY="${REPO_ROOT}/clusters/staging/nodes.txt"
SYSTEMCTL="${SYSTEMCTL_BIN:-systemctl}"
HOSTNAME_CMD="${HOSTNAME_BIN:-hostname}"
TTY="${SUGARKUBE_HEARTBEAT_TTY:-/dev/tty}"
SERVICE=sugarkube-node-heartbeat.service
TIMER=sugarkube-node-heartbeat.timer

die() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }
require_tool() { command -v "$1" >/dev/null 2>&1 || die "required tool is missing: $1"; }
guard_env() {
  [[ "${1:-}" == staging ]] || die "env=staging is required; production and unknown environments are unsupported."
}
hostname_checked() {
  local host
  [[ -r "${INVENTORY}" ]] || die "staging node inventory is unavailable."
  host="$(${HOSTNAME_CMD} -s)" || die "could not resolve the local hostname."
  grep -Fxq -- "${host}" "${INVENTORY}" || die "hostname is not a canonical staging node."
  printf '%s' "${host}"
}
require_root() {
  if [[ -z "${ROOT}" && "${EUID}" -ne 0 ]]; then
    die "this mutation must run as root (use sudo)."
  fi
}
require_tty() {
  [[ -r "${TTY}" && -w "${TTY}" ]] || die "a readable controlling terminal is required."
  if [[ "${SUGARKUBE_HEARTBEAT_TEST_NONTTY:-0}" != 1 && ! -t 3 ]]; then
    die "a controlling terminal is required; piped stdin and environment secrets are refused."
  fi
}
reject_secret_env() {
  [[ -z "${HEALTHCHECKS_PING_URL:-}${HEALTHCHECK_PING_URL:-}${PING_URL:-}" ]] || \
    die "ping URLs in environment variables are refused."
}
validate_url() {
  local value="$1"
  local uuid='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}'
  [[ "${value}" =~ ^https://hc-ping\.com/${uuid}$ ]]
}
install_file() {
  local mode="$1" source="$2" destination="$3"
  if [[ -n "${ROOT}" ]]; then
    install -D -m "${mode}" "${source}" "${destination}"
  else
    install -D -o root -g root -m "${mode}" "${source}" "${destination}"
  fi
}
install_heartbeat() {
  local host secret tmp
  require_root; require_tool install; require_tool curl; require_tool "${SYSTEMCTL}"; reject_secret_env
  host="$(hostname_checked)"
  exec 3<"${TTY}"; require_tty
  printf 'Enter the rotated Healthchecks.io ping URL for %s (input hidden): ' "${host}" >&2
  IFS= read -r -s secret <&3 || die "could not read the ping URL from the controlling terminal."
  printf '\n' >&2
  validate_url "${secret}" || die "ping URL is invalid (value redacted)."
  if [[ -n "${ROOT}" ]]; then
    install -d -m 0700 "${CREDENTIAL_DIR}"
  else
    install -d -o root -g root -m 0700 "${CREDENTIAL_DIR}"
  fi
  tmp="$(mktemp "${CREDENTIAL_DIR}/.ping-url.XXXXXX")"
  trap 'rm -f "${tmp:-}"' RETURN
  chmod 0600 "${tmp}"
  [[ -n "${ROOT}" ]] || chown root:root "${tmp}"
  printf '%s\n' "${secret}" >"${tmp}"
  mv -f "${tmp}" "${CREDENTIAL_DIR}/ping-url"
  trap - RETURN
  install_file 0755 "${REPO_ROOT}/scripts/sugarkube-node-heartbeat" "${LIBEXEC_DIR}/sugarkube-node-heartbeat"
  install_file 0644 "${REPO_ROOT}/scripts/systemd/${SERVICE}" "${SYSTEMD_DIR}/${SERVICE}"
  install_file 0644 "${REPO_ROOT}/scripts/systemd/${TIMER}" "${SYSTEMD_DIR}/${TIMER}"
  "${SYSTEMCTL}" daemon-reload
  "${SYSTEMCTL}" enable "${TIMER}"
  "${SYSTEMCTL}" start "${TIMER}"
  printf 'Installed node heartbeat for %s; credential value remains redacted.\n' "${host}"
}
status_heartbeat() {
  local host credential_state=missing service_state=missing timer_state=missing
  require_tool "${SYSTEMCTL}"; require_tool stat; host="$(hostname_checked)"
  if [[ -f "${CREDENTIAL_DIR}/ping-url" ]]; then
    credential_state="present owner/mode=$(stat -c '%U:%G %a' "${CREDENTIAL_DIR}/ping-url") (content not inspected)"
  fi
  [[ -f "${SYSTEMD_DIR}/${SERVICE}" ]] && service_state="present mode=$(stat -c '%a' "${SYSTEMD_DIR}/${SERVICE}")"
  [[ -f "${SYSTEMD_DIR}/${TIMER}" ]] && timer_state="present mode=$(stat -c '%a' "${SYSTEMD_DIR}/${TIMER}")"
  printf 'Hostname: %s\nCredential: %s\nService asset: %s\nTimer asset: %s\n' \
    "${host}" "${credential_state}" "${service_state}" "${timer_state}"
  printf 'Timer enabled: %s\nTimer active: %s\nLast service result: %s\nCadence: boot + 30s, then every 1min (up to 5s randomized delay)\n' \
    "$("${SYSTEMCTL}" is-enabled "${TIMER}" 2>/dev/null || echo no)" \
    "$("${SYSTEMCTL}" is-active "${TIMER}" 2>/dev/null || echo no)" \
    "$("${SYSTEMCTL}" show "${SERVICE}" --property=Result --value 2>/dev/null || echo unavailable)"
}
verify_heartbeat() {
  local host deadline state
  require_tool "${SYSTEMCTL}"; host="$(hostname_checked)"
  "${SYSTEMCTL}" is-enabled --quiet "${TIMER}" || die "timer is not enabled."
  "${SYSTEMCTL}" is-active --quiet "${TIMER}" || die "timer is not active."
  "${SYSTEMCTL}" start "${SERVICE}" || die "heartbeat trigger failed (credential and URL redacted)."
  deadline=$((SECONDS + ${SUGARKUBE_HEARTBEAT_VERIFY_TIMEOUT:-25}))
  while ((SECONDS < deadline)); do
    state="$("${SYSTEMCTL}" show "${SERVICE}" --property=Result --value 2>/dev/null || true)"
    [[ "${state}" == success ]] && { printf 'Verified successful node heartbeat for %s; timer remains enabled.\n' "${host}"; return; }
    [[ "${state}" == failed ]] && die "heartbeat failed (inspect sanitized unit diagnostics)."
    sleep 1
  done
  die "heartbeat verification timed out after a bounded wait."
}
uninstall_heartbeat() {
  local host answer
  require_root; require_tool "${SYSTEMCTL}"; host="$(hostname_checked)"
  exec 3<"${TTY}"; require_tty
  printf 'Delete the local heartbeat credential and owned assets for %s? Type uninstall: ' "${host}" >&2
  IFS= read -r answer <&3 || die "confirmation was not read."
  [[ "${answer}" == uninstall ]] || die "uninstall cancelled."
  "${SYSTEMCTL}" disable --now "${TIMER}" 2>/dev/null || true
  rm -f "${SYSTEMD_DIR}/${SERVICE}" "${SYSTEMD_DIR}/${TIMER}" \
    "${LIBEXEC_DIR}/sugarkube-node-heartbeat" "${CREDENTIAL_DIR}/ping-url"
  rmdir "${CREDENTIAL_DIR}" 2>/dev/null || true
  "${SYSTEMCTL}" daemon-reload
  printf 'Removed node heartbeat assets for %s. Healthchecks.io and PagerDuty were not changed.\n' "${host}"
}

action="${1:-}"; env_name="${2:-}"
[[ $# -eq 2 ]] || die "usage: $0 install|status|verify|uninstall staging"
guard_env "${env_name}"
case "${action}" in
  install) install_heartbeat ;;
  status) status_heartbeat ;;
  verify) verify_heartbeat ;;
  uninstall) uninstall_heartbeat ;;
  *) die "unknown node heartbeat action." ;;
esac
