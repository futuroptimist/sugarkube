#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"

current_uid="${EUID:-0}"
if [ "${ALLOW_NON_ROOT}" != "1" ] && [ "${current_uid}" -ne 0 ]; then
  echo "scripts/wipe_node.sh must be run as root (set ALLOW_NON_ROOT=1 to override)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"

printf 'Selected cluster=%s env=%s\n' "${CLUSTER}" "${ENVIRONMENT}"
if [ "${DRY_RUN}" = "1" ]; then
  echo "DRY_RUN=1: no changes will be made"
fi

declare -a SUMMARY=()

append_summary() {
    SUMMARY+=("$1")
}

run_uninstaller() {
  local name="$1"
  local cmd=""
  cmd="$(command -v "${name}" 2>/dev/null || true)"
  if [ -z "${cmd}" ]; then
    printf 'Skipping %s: not found on PATH\n' "${name}"
    append_summary "${name}:missing"
    return 0
  fi

  printf 'Found %s at %s\n' "${name}" "${cmd}"
  if [ "${DRY_RUN}" = "1" ]; then
    printf 'DRY_RUN=1: would run %s\n' "${cmd}"
    append_summary "${name}:dry-run"
    return 0
  fi

  if command -v sudo >/dev/null 2>&1; then
    if sudo -n "${cmd}" 2>/dev/null; then
      :
    else
      "${cmd}"
    fi
  else
    "${cmd}"
  fi
  append_summary "${name}:executed"
}

run_uninstaller "k3s-killall.sh"
run_uninstaller "k3s-uninstall.sh"
run_uninstaller "k3s-agent-uninstall.sh"

AVAHI_PRIMARY="/etc/avahi/services/k3s-${CLUSTER}-${ENVIRONMENT}.service"
AVAHI_GLOB="/etc/avahi/services/k3s-*.service"

remove_file() {
  local target="$1"
    if [ "${DRY_RUN}" = "1" ]; then
      printf 'DRY_RUN=1: would remove %s\n' "${target}"
      append_summary "rm:${target}"
      return 0
    fi
    if [ -e "${target}" ] || [ "${target}" != "${AVAHI_GLOB}" ]; then
      rm -f "${target}" || true
      append_summary "removed:${target}"
    else
      rm -f "${target}" || true
      append_summary "removed:${target}"
    fi
  }

remove_file "${AVAHI_PRIMARY}"
remove_file "${AVAHI_GLOB}"

cleanup_dynamic_publishers() {
  local svc
  svc="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
  if [ "${DRY_RUN}" = "1" ]; then
    printf 'DRY_RUN=1: would clean dynamic Avahi publishers for %s\n' "${svc}"
    append_summary "cleanup-mdns:dry-run"
    return 0
  fi
  if bash "${SCRIPT_DIR}/cleanup_mdns_publishers.sh"; then
    append_summary "cleanup-mdns:${svc}"
  else
    append_summary "cleanup-mdns:failed"
  fi
}

cleanup_dynamic_publishers

reload_avahi() {
  if [ "${DRY_RUN}" = "1" ]; then
    echo "DRY_RUN=1: would reload avahi-daemon"
    append_summary "systemctl:reload avahi-daemon"
    return 0
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl reload avahi-daemon || true
    append_summary "systemctl:reload avahi-daemon"
  else
    append_summary "systemctl:missing"
  fi
}

reload_avahi

if [ "${#SUMMARY[@]}" -gt 0 ]; then
  printf 'Summary:'
  for item in "${SUMMARY[@]}"; do
    printf ' %s;' "${item}"
  done
  printf '\n'
fi

printf 'Completed wipe for cluster=%s env=%s\n' "${CLUSTER}" "${ENVIRONMENT}"
