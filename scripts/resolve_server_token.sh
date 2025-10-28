#!/usr/bin/env bash
set -euo pipefail

SERVER_TOKEN_PATH="${SUGARKUBE_K3S_SERVER_TOKEN_PATH:-/var/lib/rancher/k3s/server/token}"
K3S_BIN="${SUGARKUBE_K3S_BIN:-k3s}"
if [ "${SUGARKUBE_SUDO_BIN+x}" = "x" ]; then
  SUDO_BIN="${SUGARKUBE_SUDO_BIN}"
else
  SUDO_BIN="sudo"
fi
ALLOW_CREATE="${SUGARKUBE_ALLOW_TOKEN_CREATE:-0}"

trim_token() {
  printf '%s' "$1" | tr -d '\r\n'
}

if [ -n "${SUGARKUBE_TOKEN:-}" ]; then
  trim_token "${SUGARKUBE_TOKEN}"
  printf '\n'
  exit 0
fi

if [ "${ALLOW_CREATE}" = "1" ] \
  && [ -f "${SERVER_TOKEN_PATH}" ] \
  && command -v "${K3S_BIN}" >/dev/null 2>&1; then
  create_cmd=()
  if [ -n "${SUDO_BIN}" ]; then
    create_cmd+=("${SUDO_BIN}")
  fi
  create_cmd+=("${K3S_BIN}" "token" "create" "--description" "sugarkube-join-token")

  if token_output="$("${create_cmd[@]}")"; then
    token_output="$(trim_token "${token_output}")"
    if [ -n "${token_output}" ]; then
      printf '%s\n' "${token_output}"
      exit 0
    fi
  fi
fi

exit 1
