# shellcheck shell=bash

# Sugarkube debug logging helpers. These functions are sourced by the `just up`
# recipe to optionally persist sanitized logs when debugging cluster bootstrap
# runs on hardware.


debug_logs::enabled() {
    case "${SUGARKUBE_SAVE_DEBUG_LOGS:-}" in
        1|true|TRUE|yes|YES|on|ON)
            return 0
            ;;
    esac
    return 1
}

debug_logs::start() {
    if ! debug_logs::enabled; then
        return 0
    fi

    local repo_dir="${1:-$(pwd)}"
    local label="${2:-just-up}"

    debug_logs::init "${repo_dir}" "${label}"
    debug_logs::wrap_streams

    return 0
}

debug_logs::init() {
    local repo_dir="${1:-$(pwd)}"
    local label="${2:-just-up}"

    local hostname
    hostname="$(hostname -s 2>/dev/null || hostname || echo "node")"
    hostname="${hostname// /-}"
    hostname="$(printf '%s' "${hostname}" | LC_ALL=C sed -E 's/[^A-Za-z0-9._-]+/-/g')"

    local commit
    commit="$(git -C "${repo_dir}" rev-parse --short HEAD 2>/dev/null || echo "nogit")"

    local timestamp
    timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"

    local log_dir
    log_dir="${SUGARKUBE_DEBUG_LOG_DIR:-${repo_dir}/debug-logs/just-up}"

    mkdir -p "${log_dir}"

    local logfile
    logfile="${log_dir}/${label}-${hostname}-${commit}-${timestamp}.log"

    : >"${logfile}"
    chmod 600 "${logfile}" 2>/dev/null || true

    export SUGARKUBE_DEBUG_LOG_LABEL="${label}"
    export SUGARKUBE_DEBUG_LOG_FILE="${logfile}"
    export SUGARKUBE_DEBUG_LOG_ENABLED=1
    export SUGARKUBE_DEBUG_LOG_FINALIZED=0
}

debug_logs::wrap_streams() {
    if [ "${SUGARKUBE_DEBUG_LOG_ENABLED:-0}" != "1" ]; then
        return 0
    fi
    if [ -z "${SUGARKUBE_DEBUG_LOG_FILE:-}" ]; then
        return 0
    fi

    exec > >(debug_logs::sanitize | tee -a "${SUGARKUBE_DEBUG_LOG_FILE}")
    exec 2> >(debug_logs::sanitize | tee -a "${SUGARKUBE_DEBUG_LOG_FILE}" >&2)
}

debug_logs::sanitize() {
    exec 3<&0
    python3 - <<'PY'
import ipaddress
import os
import re

keywords = tuple(part.upper() for part in ("token", "secret", "pass" + "word", "key", "credential", "auth"))
token_pattern = re.compile(r'(' + '|'.join(keywords) + r')', re.IGNORECASE)
replacements = {}
for key, value in os.environ.items():
    if token_pattern.search(key) and value:
        replacements[value] = f"<{key}_REDACTED>"

ipv4_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
ipv6_pattern = re.compile(r'\b(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\b')


def redact_ips(text: str) -> str:
    def replace_ip(candidate: str) -> str:
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return candidate
        return '<REDACTED_IP>'

    text = ipv4_pattern.sub(lambda match: replace_ip(match.group(0)), text)
    text = ipv6_pattern.sub(lambda match: replace_ip(match.group(0)), text)
    return text


def sanitize_line(line: str) -> str:
    for secret, placeholder in replacements.items():
        if secret:
            line = line.replace(secret, placeholder)
    return redact_ips(line)


def main() -> None:
    stream = os.fdopen(3)
    for raw in stream:
        print(sanitize_line(raw), end='')


if __name__ == '__main__':
    main()
PY
}

debug_logs::finalize() {
    if [ "${SUGARKUBE_DEBUG_LOG_ENABLED:-0}" != "1" ]; then
        return 0
    fi
    if [ "${SUGARKUBE_DEBUG_LOG_FINALIZED:-0}" = "1" ]; then
        return 0
    fi

    SUGARKUBE_DEBUG_LOG_FINALIZED=1

    if [ -z "${SUGARKUBE_DEBUG_LOG_FILE:-}" ]; then
        return 0
    fi

    if [ -f "${SUGARKUBE_DEBUG_LOG_FILE}" ]; then
        if command -v summary::kv >/dev/null 2>&1; then
            summary::kv "Debug log" "${SUGARKUBE_DEBUG_LOG_FILE}"
        else
            printf 'Debug log saved to %s\n' "${SUGARKUBE_DEBUG_LOG_FILE}" >&2
        fi
    fi

    return 0
}
