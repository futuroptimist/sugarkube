#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  tailscale_remote_ops.sh install
  tailscale_remote_ops.sh up [tailscale-up-args...]
  tailscale_remote_ops.sh status [tailscale-status-args...]

Environment:
  TAILSCALE_AUTH_KEY       Optional auth key used by the up command.
  TAILSCALE_AUTH_KEY_FILE  Optional file path containing auth key (trimmed).
  TAILSCALE_INSTALL_URL    Override install script URL.
  TAILSCALE_DRY_RUN=1      Print commands instead of executing them.
USAGE
}

log() {
    printf '%s\n' "$*" >&2
}

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log "ERROR: required command '$cmd' was not found in PATH."
        return 1
    fi
}

run_cmd() {
    if [ "${TAILSCALE_DRY_RUN:-0}" = "1" ]; then
        printf 'DRY-RUN:' >&2
        printf ' %q' "$@" >&2
        printf '\n' >&2
        return 0
    fi
    "$@"
}

maybe_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        run_cmd "$@"
    else
        require_cmd sudo
        run_cmd sudo "$@"
    fi
}

read_auth_key() {
    if [ -n "${TAILSCALE_AUTH_KEY:-}" ]; then
        printf '%s' "${TAILSCALE_AUTH_KEY}"
        return 0
    fi

    if [ -n "${TAILSCALE_AUTH_KEY_FILE:-}" ]; then
        if [ ! -r "${TAILSCALE_AUTH_KEY_FILE}" ]; then
            log "ERROR: TAILSCALE_AUTH_KEY_FILE is set but not readable: ${TAILSCALE_AUTH_KEY_FILE}"
            return 1
        fi
        tr -d '\r\n' <"${TAILSCALE_AUTH_KEY_FILE}"
    fi
}

install_tailscale() {
    local install_url="${TAILSCALE_INSTALL_URL:-https://tailscale.com/install.sh}"

    if command -v tailscale >/dev/null 2>&1; then
        log 'tailscale is already installed; skipping installation.'
        return 0
    fi

    require_cmd curl
    require_cmd bash
    if [ "${TAILSCALE_DRY_RUN:-0}" = "1" ]; then
        log "DRY-RUN: would fetch installer from ${install_url} and execute it with sudo."
        return 0
    fi

    maybe_sudo bash -c "
        set -euo pipefail
        curl -fsSL '${install_url}' | bash
    "
}

up_tailscale() {
    require_cmd tailscale

    local auth_key
    auth_key="$(read_auth_key || true)"

    local args=(tailscale up)
    if [ -n "${auth_key}" ]; then
        args+=(--auth-key "${auth_key}")
    fi
    if [ "$#" -gt 0 ]; then
        args+=("$@")
    fi

    if [ "${TAILSCALE_DRY_RUN:-0}" = "1" ] && [ -n "${auth_key}" ]; then
        local redacted=(tailscale up --auth-key '***redacted***')
        if [ "$#" -gt 0 ]; then
            redacted+=("$@")
        fi
        printf 'DRY-RUN:' >&2
        printf ' %q' sudo "${redacted[@]}" >&2
        printf '\n' >&2
        return 0
    fi

    maybe_sudo "${args[@]}"
}

status_tailscale() {
    require_cmd tailscale
    run_cmd tailscale status "$@"
}

main() {
    local cmd="${1:-}"
    if [ -z "${cmd}" ]; then
        usage
        return 1
    fi
    shift

    case "${cmd}" in
        install) install_tailscale "$@" ;;
        up) up_tailscale "$@" ;;
        status) status_tailscale "$@" ;;
        -h|--help|help) usage ;;
        *)
            log "ERROR: unknown command '${cmd}'"
            usage
            return 1
            ;;
    esac
}

main "$@"
