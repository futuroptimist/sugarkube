#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${SUGARKUBE_TOKEN:-}" ]]; then
  printf '%s\n' "${SUGARKUBE_TOKEN}"
  exit 0
fi

SERVER_TOKEN_PATH="${SUGARKUBE_SERVER_TOKEN_PATH:-/var/lib/rancher/k3s/server/token}"
ALLOW_TOKEN_CREATE="${SUGARKUBE_ALLOW_TOKEN_CREATE:-0}"

if [[ "${ALLOW_TOKEN_CREATE}" == "1" ]]; then
  if ! command -v k3s >/dev/null 2>&1; then
    printf 'k3s binary not available for secure token creation\n' >&2
    exit 1
  fi

  if [[ ! -f "${SERVER_TOKEN_PATH}" ]]; then
    printf 'secure server token not found at %s\n' "${SERVER_TOKEN_PATH}" >&2
    exit 1
  fi

  SUDO_BIN=""
  if [[ "${EUID}" -eq 0 ]]; then
    SUDO_BIN="${SUGARKUBE_SUDO_BIN:-}"
  else
    SUDO_BIN="${SUGARKUBE_SUDO_BIN:-sudo}"
  fi

  if [[ -n "${SUDO_BIN}" ]]; then
    if ! command -v "${SUDO_BIN%% *}" >/dev/null 2>&1; then
      printf 'sudo command "%s" not available\n' "${SUDO_BIN%% *}" >&2
      exit 1
    fi
    TOKEN_OUTPUT="$(${SUDO_BIN} k3s token create --description 'sugarkube-join-token')"
  else
    TOKEN_OUTPUT="$(k3s token create --description 'sugarkube-join-token')"
  fi

  TOKEN_OUTPUT="${TOKEN_OUTPUT%$'\n'}"
  if [[ -n "${TOKEN_OUTPUT}" ]]; then
    printf '%s\n' "${TOKEN_OUTPUT}"
    exit 0
  fi

  printf 'k3s token create returned an empty token\n' >&2
  exit 1
fi

exit 1
