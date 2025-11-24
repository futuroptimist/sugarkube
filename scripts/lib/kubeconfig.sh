#!/usr/bin/env bash
# shellcheck shell=bash

# Guard against multiple sourcing.
if [ -n "${SUGARKUBE_KUBECONFIG_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_KUBECONFIG_LIB_SOURCED=1

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

kubeconfig::ensure_user_kubeconfig() {
  if [ ! -r /etc/rancher/k3s/k3s.yaml ]; then
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

  if [ ! -r "${kubeconfig_path}" ]; then
    kubeconfig::_with_privilege cp /etc/rancher/k3s/k3s.yaml "${kubeconfig_path}"
  fi

  kubeconfig::_with_privilege chown "${uid}:${gid}" "${kubeconfig_path}"
  kubeconfig::_with_privilege chmod 600 "${kubeconfig_path}"
  kubeconfig::_with_privilege chmod 700 "${kube_dir}"

  if [ -n "${bashrc_path}" ]; then
    if ! grep -q 'KUBECONFIG=$HOME/.kube/config' "${bashrc_path}" 2>/dev/null; then
      printf '%s\n' 'export KUBECONFIG=$HOME/.kube/config' >>"${bashrc_path}"
    fi
  fi

  return 0
}
