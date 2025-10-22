#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"
EXECUTE_COMMANDS="yes"
if [ "${DRY_RUN}" = "1" ] && [ "${ALLOW_NON_ROOT}" != "1" ]; then
  EXECUTE_COMMANDS="no"
fi

if [ "${ALLOW_NON_ROOT}" != "1" ]; then
  CURRENT_UID="$(id -u 2>/dev/null || printf '1')"
  if [ "${CURRENT_UID}" -ne 0 ]; then
    printf '%s\n' "scripts/wipe_node.sh must be run as root (set ALLOW_NON_ROOT=1 for CI or tests)" >&2
    exit 1
  fi
fi

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"

printf 'Selected cluster=%s env=%s\n' "${CLUSTER}" "${ENVIRONMENT}"

SUDO_PRESENT=0
if command -v sudo >/dev/null 2>&1; then
  SUDO_PRESENT=1
fi

run_action() {
  local description="$1"
  shift
  local -a command=("$@")

  if [ "${EXECUTE_COMMANDS}" = "no" ]; then
    printf 'DRY_RUN=1: would %s\n' "${description}"
    return 0
  fi

  if [ "${DRY_RUN}" = "1" ]; then
    printf 'DRY_RUN=1: %s\n' "${description}"
  else
    printf '%s\n' "${description}"
  fi

  if [ "${SUDO_PRESENT}" -eq 1 ]; then
    if ! sudo -n "${command[@]}"; then
      "${command[@]}"
    fi
  else
    "${command[@]}"
  fi
}

report_missing() {
  local name="$1"
  printf '%s not found; skipping.\n' "${name}"
}

TARGETED_UNINSTALLERS=()

if cmd="$(command -v k3s-killall.sh 2>/dev/null)"; then
  printf 'Found k3s-killall.sh at %s\n' "${cmd}"
  TARGETED_UNINSTALLERS+=("k3s-killall.sh")
  run_action "run ${cmd}" "${cmd}"
else
  report_missing "k3s-killall.sh"
fi

if cmd="$(command -v k3s-uninstall.sh 2>/dev/null)"; then
  printf 'Found k3s-uninstall.sh at %s\n' "${cmd}"
  TARGETED_UNINSTALLERS+=("k3s-uninstall.sh")
  run_action "run ${cmd}" "${cmd}"
else
  report_missing "k3s-uninstall.sh"
fi

if cmd="$(command -v k3s-agent-uninstall.sh 2>/dev/null)"; then
  printf 'Found k3s-agent-uninstall.sh at %s\n' "${cmd}"
  TARGETED_UNINSTALLERS+=("k3s-agent-uninstall.sh")
  run_action "run ${cmd}" "${cmd}"
else
  report_missing "k3s-agent-uninstall.sh"
fi

AVAHI_PRIMARY="/etc/avahi/services/k3s-${CLUSTER}-${ENVIRONMENT}.service"
run_action "remove ${AVAHI_PRIMARY}" rm -f "${AVAHI_PRIMARY}"
run_action "remove /etc/avahi/services/k3s-*.service" rm -f /etc/avahi/services/k3s-*.service

if command -v systemctl >/dev/null 2>&1; then
  run_action "reload avahi-daemon" systemctl reload avahi-daemon
else
  printf 'systemctl not available; skipping avahi-daemon reload.\n'
fi

if [ "${#TARGETED_UNINSTALLERS[@]}" -gt 0 ]; then
  printf 'Summary: cluster=%s env=%s; targeted uninstallers=%s; Avahi targets=%s and /etc/avahi/services/k3s-*.service\n' \
    "${CLUSTER}" "${ENVIRONMENT}" "${TARGETED_UNINSTALLERS[*]}" "${AVAHI_PRIMARY}"
else
  printf 'Summary: cluster=%s env=%s; targeted uninstallers=none; Avahi targets=%s and /etc/avahi/services/k3s-*.service\n' \
    "${CLUSTER}" "${ENVIRONMENT}" "${AVAHI_PRIMARY}"
fi
