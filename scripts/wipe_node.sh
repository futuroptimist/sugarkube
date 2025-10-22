#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"

if [ "${ALLOW_NON_ROOT}" != "1" ] && [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "scripts/wipe_node.sh must be run as root (set ALLOW_NON_ROOT=1 for non-root dry runs)" >&2
  exit 1
fi

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENV="${SUGARKUBE_ENV:-dev}"

printf 'Selected cluster=%s env=%s\n' "${CLUSTER}" "${ENV}"

invoke_with_sudo_fallback() {
  local target="$1"
  shift || true
  if [ "${DRY_RUN}" = "1" ]; then
    printf '[dry-run] sudo -n %s || %s\n' "${target}" "${target}"
    return 0
  fi
  if command -v sudo >/dev/null 2>&1; then
    if sudo -n "${target}" "$@"; then
      return 0
    fi
  fi
  "${target}" "$@"
}

handle_uninstaller() {
  local name="$1"
  local cmd=""
  if cmd="$(command -v "${name}" 2>/dev/null)"; then
    printf 'Found %s at %s\n' "${name}" "${cmd}"
    if [ "${DRY_RUN}" = "1" ]; then
      printf '[dry-run] sudo -n %s || %s\n' "${cmd}" "${cmd}"
    else
      if ! invoke_with_sudo_fallback "${cmd}"; then
        local status="$?"
        printf 'Warning: %s exited with status %s\n' "${cmd}" "${status}" >&2
      fi
    fi
  else
    printf 'Skipping %s (not found)\n' "${name}"
  fi
}

handle_uninstaller "k3s-killall.sh"
handle_uninstaller "k3s-uninstall.sh"
handle_uninstaller "k3s-agent-uninstall.sh"

avahi_primary="/etc/avahi/services/k3s-${CLUSTER}-${ENV}.service"
printf 'Targeting Avahi services: %s and /etc/avahi/services/k3s-*.service\n' "${avahi_primary}"
if [ "${DRY_RUN}" = "1" ]; then
  printf '[dry-run] rm -f %s\n' "${avahi_primary}"
  printf '[dry-run] rm -f %s\n' "/etc/avahi/services/k3s-*.service"
else
  rm -f "${avahi_primary}" || true
  rm -f /etc/avahi/services/k3s-*.service || true
fi

if [ "${DRY_RUN}" = "1" ]; then
  printf '[dry-run] systemctl reload avahi-daemon\n'
else
  if command -v systemctl >/dev/null 2>&1; then
    systemctl reload avahi-daemon || true
  fi
fi

printf 'Completed wipe for cluster=%s env=%s\n' "${CLUSTER}" "${ENV}"
