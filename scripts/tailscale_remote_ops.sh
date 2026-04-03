#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  scripts/tailscale_remote_ops.sh install
  scripts/tailscale_remote_ops.sh up [--auth-key-file FILE] [--auth-key-env VAR] [--reset]
                                 [--hostname NAME] [--accept-routes]
                                 [--advertise-tags TAGS] [--ssh]
                                 [--extra-arg ARG ...]
  scripts/tailscale_remote_ops.sh status [--json]

Notes:
  - Prefer --auth-key-file or --auth-key-env over passing keys in shell history.
  - Set SUGARKUBE_TAILSCALE_BIN/SUGARKUBE_TAILSCALED_BIN to override binary names.
USAGE
}

log() {
    printf '[tailscale-ops] %s\n' "$*"
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'ERROR: required command not found: %s\n' "$1" >&2
        return 1
    fi
}

tailscale_bin() {
    printf '%s' "${SUGARKUBE_TAILSCALE_BIN:-tailscale}"
}

tailscaled_bin() {
    printf '%s' "${SUGARKUBE_TAILSCALED_BIN:-tailscaled}"
}

run_install() {
    local installer_url="${SUGARKUBE_TAILSCALE_INSTALLER_URL:-https://tailscale.com/install.sh}"
    local installer

    require_cmd curl
    require_cmd sh

    installer="$(mktemp -t sugarkube-tailscale-install.XXXXXX)"
    trap 'rm -f "${installer}"' EXIT

    log "Downloading installer from ${installer_url}"
    curl -fsSL "${installer_url}" -o "${installer}"

    log "Running installer"
    sh "${installer}"

    trap - EXIT
    rm -f "${installer}"
}

run_up() {
    local auth_key_file=''
    local auth_key_env=''
    local reset='0'
    local hostname=''
    local accept_routes='0'
    local advertise_tags=''
    local ssh_mode='0'
    local arg

    local -a extra_args=()
    local -a cmd

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --auth-key-file)
                auth_key_file="$2"
                shift 2
                ;;
            --auth-key-env)
                auth_key_env="$2"
                shift 2
                ;;
            --reset)
                reset='1'
                shift
                ;;
            --hostname)
                hostname="$2"
                shift 2
                ;;
            --accept-routes)
                accept_routes='1'
                shift
                ;;
            --advertise-tags)
                advertise_tags="$2"
                shift 2
                ;;
            --ssh)
                ssh_mode='1'
                shift
                ;;
            --extra-arg)
                extra_args+=("$2")
                shift 2
                ;;
            --)
                shift
                while [ "$#" -gt 0 ]; do
                    extra_args+=("$1")
                    shift
                done
                ;;
            -h|--help)
                usage
                return 0
                ;;
            *)
                printf 'ERROR: unknown argument for up: %s\n' "$1" >&2
                return 1
                ;;
        esac
    done

    require_cmd "$(tailscale_bin)"
    require_cmd sudo

    cmd=(sudo "$(tailscale_bin)" up)

    if [ -n "${auth_key_file}" ] && [ -n "${auth_key_env}" ]; then
        printf 'ERROR: use either --auth-key-file or --auth-key-env, not both\n' >&2
        return 1
    fi

    if [ -n "${auth_key_file}" ]; then
        if [ ! -r "${auth_key_file}" ]; then
            printf 'ERROR: auth key file is not readable: %s\n' "${auth_key_file}" >&2
            return 1
        fi
        arg="$(tr -d '\r\n' < "${auth_key_file}")"
        if [ -z "${arg}" ]; then
            printf 'ERROR: auth key file is empty: %s\n' "${auth_key_file}" >&2
            return 1
        fi
        cmd+=(--auth-key "${arg}")
    elif [ -n "${auth_key_env}" ]; then
        if [ -z "${!auth_key_env-}" ]; then
            printf 'ERROR: environment variable %s is empty or unset\n' "${auth_key_env}" >&2
            return 1
        fi
        cmd+=(--auth-key "${!auth_key_env}")
    fi

    if [ "${reset}" = '1' ]; then
        cmd+=(--reset)
    fi
    if [ -n "${hostname}" ]; then
        cmd+=(--hostname "${hostname}")
    fi
    if [ "${accept_routes}" = '1' ]; then
        cmd+=(--accept-routes)
    fi
    if [ -n "${advertise_tags}" ]; then
        cmd+=(--advertise-tags "${advertise_tags}")
    fi
    if [ "${ssh_mode}" = '1' ]; then
        cmd+=(--ssh)
    fi

    for arg in "${extra_args[@]}"; do
        cmd+=("${arg}")
    done

    log "Running tailscale up"
    "${cmd[@]}"
}

run_status() {
    local json='0'

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --json)
                json='1'
                shift
                ;;
            -h|--help)
                usage
                return 0
                ;;
            *)
                printf 'ERROR: unknown argument for status: %s\n' "$1" >&2
                return 1
                ;;
        esac
    done

    require_cmd "$(tailscale_bin)"

    if [ "${json}" = '1' ]; then
        "$(tailscale_bin)" status --json
        return 0
    fi

    "$(tailscale_bin)" status
}

run_preflight() {
    require_cmd "$(tailscale_bin)"
    require_cmd "$(tailscaled_bin)"
}

main() {
    if [ "$#" -lt 1 ]; then
        usage
        return 1
    fi

    case "$1" in
        install)
            shift
            run_install "$@"
            ;;
        up)
            shift
            run_preflight
            run_up "$@"
            ;;
        status)
            shift
            run_preflight
            run_status "$@"
            ;;
        -h|--help)
            usage
            ;;
        *)
            printf 'ERROR: unknown command: %s\n' "$1" >&2
            usage
            return 1
            ;;
    esac
}

main "$@"
