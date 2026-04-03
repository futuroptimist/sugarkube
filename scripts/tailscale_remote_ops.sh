#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/tailscale_remote_ops.sh <command> [options]

Commands:
  install             Install Tailscale using the upstream install script.
  up                  Bring this node online in the tailnet.
  status              Show and validate Tailscale status.
  ssh-check <target>  Probe SSH connectivity to a tailnet host.

Environment:
  SUGARKUBE_TAILSCALE_AUTH_KEY   Optional auth key used by `up`.
  SUGARKUBE_TAILSCALE_INSTALL_URL Override install script URL.
USAGE
}

log() {
  printf '[tailscale-ops] %s\n' "$*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf 'missing required command: %s\n' "$cmd" >&2
    exit 1
  fi
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi

  require_cmd sudo
  sudo "$@"
}

validate_install_url() {
  local install_url="$1"

  case "$install_url" in
    https://*)
      ;;
    *)
      printf 'invalid tailscale install URL (must use https): %s\n' "$install_url" >&2
      exit 1
      ;;
  esac

  case "$install_url" in
    *[[:space:]\'\"\\\`\$\;\&\|\<\>\(\)\{\}\[\]\!\#\*\?~]*)
      printf 'invalid tailscale install URL (contains unsafe characters): %s\n' "$install_url" >&2
      exit 1
      ;;
  esac
}

install_tailscale() {
  require_cmd curl
  require_cmd sh
  require_cmd mktemp

  local install_url="${SUGARKUBE_TAILSCALE_INSTALL_URL:-https://tailscale.com/install.sh}"
  local tmp_script
  validate_install_url "$install_url"
  tmp_script="$(mktemp)"
  trap "rm -f '$tmp_script'" RETURN

  log "installing tailscale from ${install_url}"
  curl -fsSL --output "$tmp_script" "$install_url"
  run_as_root sh "$tmp_script"
  log 'install complete'
}

up_tailscale() {
  require_cmd tailscale

  local -a cmd=(tailscale up)
  if [ -n "${SUGARKUBE_TAILSCALE_AUTH_KEY:-}" ]; then
    cmd+=(--auth-key "${SUGARKUBE_TAILSCALE_AUTH_KEY}")
  fi

  if [ "$#" -gt 0 ]; then
    cmd+=("$@")
  fi

  log 'bringing tailscale up'
  run_as_root "${cmd[@]}"
}

status_tailscale() {
  require_cmd tailscale
  require_cmd python3

  tailscale status --json | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
backend_state = payload.get("BackendState", "")
self_info = payload.get("Self") or {}
hostname = self_info.get("HostName", "unknown")
tail_addr = ", ".join(self_info.get("TailscaleIPs", [])) or "none"

print(f"BackendState={backend_state}")
print(f"HostName={hostname}")
print(f"TailscaleIPs={tail_addr}")

if backend_state.lower() != "running":
    raise SystemExit("tailscale backend is not running")
'
}

ssh_check() {
  require_cmd ssh
  local target="${1:-}"
  if [ -z "${target}" ]; then
    printf 'ssh-check requires a target like pi@sugarkube0\n' >&2
    exit 1
  fi

  log "probing ssh to ${target}"
  ssh \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=8 \
    "$target" true
}

main() {
  local command="${1:-}"
  case "$command" in
    install)
      shift
      install_tailscale "$@"
      ;;
    up)
      shift
      up_tailscale "$@"
      ;;
    status)
      shift
      status_tailscale "$@"
      ;;
    ssh-check)
      shift
      ssh_check "$@"
      ;;
    -h|--help|help)
      usage
      ;;
    "")
      usage >&2
      exit 1
      ;;
    *)
      printf 'unknown command: %s\n' "$command" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
