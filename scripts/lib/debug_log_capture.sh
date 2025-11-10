#!/usr/bin/env bash

# shellcheck shell=bash

debug_logs::enabled() {
    [[ "${SAVE_DEBUG_LOGS:-0}" == "1" ]]
}

debug_logs::start() {
    if ! debug_logs::enabled; then
        return 1
    fi
    local repo_dir="${1:-$(pwd)}"
    local label="${2:-session}"
    if [ ! -d "${repo_dir}" ]; then
        return 1
    fi
    export SUGARKUBE_DEBUG_LOG_LABEL="${label}"
    export SUGARKUBE_DEBUG_LOG_REPO_DIR="${repo_dir}"
    if [ -n "${SUGARKUBE_DEBUG_LOG_TMP:-}" ] && [ -f "${SUGARKUBE_DEBUG_LOG_TMP}" ]; then
        rm -f "${SUGARKUBE_DEBUG_LOG_TMP}" || true
    fi
    local tmp
    tmp="$(mktemp -t sugarkube-debug-log.XXXXXX)"
    export SUGARKUBE_DEBUG_LOG_TMP="${tmp}"
    exec > >(tee -a "${tmp}") 2> >(tee -a "${tmp}" >&2)
}

debug_logs::finalize() {
    local status="${1:-0}"
    if ! debug_logs::enabled; then
        return "${status}"
    fi
    local tmp="${SUGARKUBE_DEBUG_LOG_TMP:-}"
    if [ -z "${tmp}" ] || [ ! -f "${tmp}" ]; then
        return "${status}"
    fi
    local repo_dir="${SUGARKUBE_DEBUG_LOG_REPO_DIR:-$(pwd)}"
    local label="${SUGARKUBE_DEBUG_LOG_LABEL:-session}"
    local log_dir="${SUGARKUBE_DEBUG_LOG_DIR:-${repo_dir}/debug-logs}"
    local sanitizer="${SUGARKUBE_DEBUG_LOG_SANITIZER:-${repo_dir}/scripts/sanitize_debug_log.py}"

    if [ ! -f "${sanitizer}" ]; then
        printf 'Debug log sanitizer not found at %s; skipping log export.\n' "${sanitizer}" >&2
        rm -f "${tmp}" || true
        return "${status}"
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        printf 'python3 is required to sanitize debug logs; skipping log export.\n' >&2
        rm -f "${tmp}" || true
        return "${status}"
    fi

    mkdir -p "${log_dir}"

    local hostname
    hostname="$(hostname 2>/dev/null || echo unknown-host)"
    local commit
    if commit="$(git -C "${repo_dir}" rev-parse --short HEAD 2>/dev/null)"; then
        :
    elif commit="$(git rev-parse --short HEAD 2>/dev/null)"; then
        :
    else
        commit="unknown"
    fi
    local timestamp
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    local logfile
    logfile="${log_dir}/${hostname}_${commit}_${timestamp}_${label}.log"

    local sanitized_tmp
    sanitized_tmp="$(mktemp -t sugarkube-debug-log-sanitized.XXXXXX)"
    if python3 "${sanitizer}" <"${tmp}" >"${sanitized_tmp}"; then
        mv "${sanitized_tmp}" "${logfile}"
        printf 'Debug log saved to %s\n' "${logfile}" >&2
    else
        printf 'Failed to sanitize debug log; nothing saved.\n' >&2
        rm -f "${sanitized_tmp}" || true
    fi
    rm -f "${tmp}" || true
    return "${status}"
}
