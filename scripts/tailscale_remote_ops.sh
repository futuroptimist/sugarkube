#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/tailscale_remote_ops.sh install
  scripts/tailscale_remote_ops.sh up [-- <extra tailscale up args>]
  scripts/tailscale_remote_ops.sh status [-- <tailscale status args>]

Environment:
  TS_AUTHKEY           Optional auth key for non-interactive enrollment.
  TS_AUTHKEY_FILE      File containing auth key (preferred for local automation).

Notes:
  - Set only one of TS_AUTHKEY or TS_AUTHKEY_FILE.
  - If neither is set, `up` uses interactive local auth.
USAGE
}

require_cmd() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$bin" >&2
    exit 1
  fi
}

load_auth_key() {
  local key="${TS_AUTHKEY:-}"

  if [ -n "${TS_AUTHKEY_FILE:-}" ] && [ -n "$key" ]; then
    printf 'ERROR: set only one of TS_AUTHKEY or TS_AUTHKEY_FILE\n' >&2
    exit 1
  fi

  if [ -n "${TS_AUTHKEY_FILE:-}" ]; then
    if [ ! -r "$TS_AUTHKEY_FILE" ]; then
      printf 'ERROR: TS_AUTHKEY_FILE is not readable: %s\n' "$TS_AUTHKEY_FILE" >&2
      exit 1
    fi
    key="$(head -n 1 "$TS_AUTHKEY_FILE" | tr -d '\r\n')"
  fi

  printf '%s' "$key"
}

cmd_install() {
  require_cmd curl
  require_cmd sh
  curl -fsSL https://tailscale.com/install.sh | sh
}

cmd_up() {
  require_cmd sudo
  require_cmd tailscale

  local auth_key
  auth_key="$(load_auth_key)"

  local -a args=(up)
  if [ -n "$auth_key" ]; then
    args+=(--auth-key "$auth_key")
  fi

  if [ "$#" -gt 0 ]; then
    args+=("$@")
  fi

  sudo tailscale "${args[@]}"
}

cmd_status() {
  require_cmd tailscale
  if [ "$#" -gt 0 ]; then
    tailscale status "$@"
  else
    tailscale status
  fi
}

main() {
  if [ "$#" -lt 1 ]; then
    usage >&2
    exit 1
  fi

  local action="$1"
  shift

  case "$action" in
    install)
      cmd_install
      ;;
    up)
      if [ "${1:-}" = "--" ]; then
        shift
      fi
      cmd_up "$@"
      ;;
    status)
      if [ "${1:-}" = "--" ]; then
        shift
      fi
      cmd_status "$@"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      printf 'ERROR: unknown action: %s\n\n' "$action" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
