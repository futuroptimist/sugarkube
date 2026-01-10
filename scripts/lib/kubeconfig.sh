#!/usr/bin/env bash
# shellcheck shell=bash

# Guard against multiple sourcing.
if [ -n "${SUGARKUBE_KUBECONFIG_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_KUBECONFIG_LIB_SOURCED=1

# Executes the given command with privilege escalation when necessary.
# Falls back to sudo if available, otherwise runs the command directly for
# best-effort behavior.
kubeconfig::_with_privilege() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return $?
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return $?
  fi

  "$@"
}

# Resolves the home directory for the target user, honoring the
# SUGARKUBE_KUBECONFIG_HOME override first, then the current user's HOME when
# applicable, and finally the system account entry.
kubeconfig::resolve_home() {
  local target_user
  target_user="$1"

  if [ -n "${SUGARKUBE_KUBECONFIG_HOME:-}" ]; then
    printf '%s' "${SUGARKUBE_KUBECONFIG_HOME}"
    return 0
  fi

  if [ "${target_user}" = "$(id -un)" ] && [ -n "${HOME:-}" ]; then
    printf '%s' "${HOME}"
    return 0
  fi

  getent passwd "${target_user}" 2>/dev/null | cut -d: -f6 | head -n1
}

# Ensures that the target user's kubeconfig file (~/.kube/config) exists and is
# properly owned.
#
# Behavior:
#   - If /etc/rancher/k3s/k3s.yaml is missing, does nothing and returns 0.
#   - Determines the target user using (in order): SUGARKUBE_KUBECONFIG_USER,
#     SUDO_USER, or current user.
#   - Determines the target home directory using SUGARKUBE_KUBECONFIG_HOME, or
#     system/user lookup.
#   - Creates ~/.kube directory if missing, copies k3s.yaml to ~/.kube/config if
#     missing or stale.
#   - Sets ownership and permissions on ~/.kube/config and ~/.kube.
#   - Adds 'export KUBECONFIG=$HOME/.kube/config' to ~/.bashrc if not present.
#
# Supported environment variables:
#   - SUGARKUBE_KUBECONFIG_USER: Username to own the kubeconfig.
#   - SUGARKUBE_KUBECONFIG_HOME: Home directory to use for kubeconfig.
#   - SUDO_USER: Used as fallback for target user if running under sudo.
#
# Return behavior:
#   - Always returns 0, even on failure, for graceful degradation.
#   - This allows scripts to proceed even if kubeconfig setup is incomplete.
kubeconfig::ensure_user_kubeconfig() {
  if [ ! -e /etc/rancher/k3s/k3s.yaml ]; then
    return 0
  fi

  local target_user target_home kubeconfig_path kube_dir bashrc_path uid gid

  target_user="${SUGARKUBE_KUBECONFIG_USER:-${SUDO_USER:-$(id -un)}}"
  target_home="$(kubeconfig::resolve_home "${target_user}")"

  if [ -z "${target_home}" ]; then
    return 0
  fi

  kube_dir="${target_home%/}/.kube"
  kubeconfig_path="${kube_dir}/config"
  bashrc_path="${target_home%/}/.bashrc"

  if ! uid="$(id -u "${target_user}" 2>/dev/null)"; then
    return 0
  fi
  if ! gid="$(id -g "${target_user}" 2>/dev/null)"; then
    return 0
  fi

  kubeconfig::_with_privilege mkdir -p "${kube_dir}"
  kubeconfig::_with_privilege chown "${uid}:${gid}" "${kube_dir}"

  if [ ! -f "${kubeconfig_path}" ]; then
    kubeconfig::_with_privilege cp /etc/rancher/k3s/k3s.yaml "${kubeconfig_path}"
  elif ! kubeconfig::_with_privilege cmp -s /etc/rancher/k3s/k3s.yaml \
    "${kubeconfig_path}" 2>/dev/null; then
    kubeconfig::_with_privilege cp /etc/rancher/k3s/k3s.yaml "${kubeconfig_path}"
  fi

  kubeconfig::_with_privilege chown "${uid}:${gid}" "${kubeconfig_path}"
  kubeconfig::_with_privilege chmod 600 "${kubeconfig_path}"
  kubeconfig::_with_privilege chmod 700 "${kube_dir}"

  if [ -n "${bashrc_path}" ]; then
    if [ ! -e "${bashrc_path}" ]; then
      kubeconfig::_with_privilege touch "${bashrc_path}"
      kubeconfig::_with_privilege chown "${uid}:${gid}" "${bashrc_path}"
    fi

    if ! grep -qE '^\s*export\s+KUBECONFIG=\$HOME/\.kube/config\s*$' "${bashrc_path}" 2>/dev/null; then
      kubeconfig::_with_privilege bash -c "printf '%s\\n' 'export KUBECONFIG=\\$HOME/.kube/config' >>'${bashrc_path}'"
      kubeconfig::_with_privilege chown "${uid}:${gid}" "${bashrc_path}"
    fi
  fi

  return 0
}
