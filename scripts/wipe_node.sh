#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

current_uid="${EUID:-0}"
if [ "${ALLOW_NON_ROOT}" != "1" ] && [ "${current_uid}" -ne 0 ]; then
  echo "scripts/wipe_node.sh must be run as root (set ALLOW_NON_ROOT=1 to override)." >&2
  exit 1
fi

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

# Explicitly clean up k3s token files that may persist after uninstallers
# These files can interfere with fresh bootstrap attempts if left behind
K3S_SERVER_TOKEN="${SUGARKUBE_K3S_SERVER_TOKEN_PATH:-/var/lib/rancher/k3s/server/token}"
K3S_NODE_TOKEN="${SUGARKUBE_NODE_TOKEN_PATH:-/var/lib/rancher/k3s/server/node-token}"
K3S_BOOT_TOKEN="${SUGARKUBE_BOOT_TOKEN_PATH:-/boot/sugarkube-node-token}"
K3S_DATA_DIR="${SUGARKUBE_K3S_DATA_DIR:-/var/lib/rancher/k3s}"

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

# Remove k3s token files explicitly
remove_file "${K3S_SERVER_TOKEN}"
remove_file "${K3S_NODE_TOKEN}"
remove_file "${K3S_BOOT_TOKEN}"

# Remove entire k3s data directory if it still exists after uninstallers
# This ensures a completely clean slate for fresh bootstrap
if [ "${DRY_RUN}" = "1" ]; then
  if [ -d "${K3S_DATA_DIR}" ]; then
    printf 'DRY_RUN=1: would remove directory %s\n' "${K3S_DATA_DIR}"
    append_summary "rm-dir:${K3S_DATA_DIR}"
  fi
else
  if [ -d "${K3S_DATA_DIR}" ]; then
    rm -rf "${K3S_DATA_DIR}" || true
    append_summary "removed-dir:${K3S_DATA_DIR}"
  fi
fi

cleanup_dynamic_publishers() {
  local svc
  svc="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
  if [ "${DRY_RUN}" = "1" ]; then
    printf 'DRY_RUN=1: would remove dynamic publishers for %s\n' "${svc}"
    append_summary "cleanup-mdns:${svc}"
    return 0
  fi
  local -a env_cmd=(
    "SUGARKUBE_CLUSTER=${CLUSTER}"
    "SUGARKUBE_ENV=${ENVIRONMENT}"
  )
  if [ -n "${SUGARKUBE_RUNTIME_DIR:-}" ]; then
    env_cmd+=("SUGARKUBE_RUNTIME_DIR=${SUGARKUBE_RUNTIME_DIR}")
  fi
  if env "${env_cmd[@]}" bash "${SCRIPT_DIR}/cleanup_mdns_publishers.sh"; then
    printf 'removed-dynamic: %s\n' "${svc}"
    append_summary "removed-dynamic:${svc}"
  else
    append_summary "cleanup-mdns:failed"
  fi
}

cleanup_dynamic_publishers

cleanup_runtime_state() {
  local runtime_dir="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
  
  if [ "${DRY_RUN}" = "1" ]; then
    if [ -d "${runtime_dir}" ]; then
      printf 'DRY_RUN=1: would remove runtime directory %s\n' "${runtime_dir}"
      append_summary "runtime-dir:${runtime_dir}"
    else
      printf 'DRY_RUN=1: runtime directory not found\n'
      append_summary "runtime-dir:not-found"
    fi
    return 0
  fi
  
  if [ -d "${runtime_dir}" ]; then
    # Remove cluster/environment-specific state files
    local state_pattern="${runtime_dir}/join-gate-${CLUSTER}-${ENVIRONMENT}.state"
    if [ -f "${state_pattern}" ]; then
      rm -f "${state_pattern}" || true
      append_summary "removed-join-gate-state:${state_pattern}"
    fi
    
    # Check if runtime dir is empty after cleanup, remove if so
    if [ -z "$(ls -A "${runtime_dir}" 2>/dev/null)" ]; then
      rmdir "${runtime_dir}" 2>/dev/null || true
      append_summary "removed-runtime-dir:${runtime_dir}"
    else
      append_summary "runtime-dir-not-empty:${runtime_dir}"
    fi
  else
    append_summary "runtime-dir:not-found"
  fi
}

cleanup_runtime_state

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
