#!/usr/bin/env bash
set -euo pipefail

state_file="${CRD_STATE_FILE:?Set CRD_STATE_FILE to a state fixture}"
log_file="${KUBECTL_CALL_LOG:-}"

log_call() {
    if [ -n "${log_file}" ]; then
        echo "$*" >>"${log_file}"
    fi
}

read_field() {
    local crd="$1"
    local field="$2"
    local line
    line=$(grep "^${crd}|" "${state_file}" || true)
    if [ -z "${line}" ]; then
        if [ "${field}" = "status" ]; then
            echo "missing"
        else
            echo ""
        fi
        return
    fi

    IFS='|' read -r _ status managed rel ns <<<"${line}"
    case "${field}" in
        status) echo "${status}" ;;
        managed) echo "${managed}" ;;
        rel) echo "${rel}" ;;
        ns) echo "${ns}" ;;
        *) echo "" ;;
    esac
}

update_after_delete() {
    local tmp="${state_file}.tmp"
    : >"${tmp}"
    while IFS='|' read -r name status managed rel ns; do
        if [ -z "${name}" ]; then
            continue
        fi
        for target in "$@"; do
            if [ "${name}" = "${target}" ]; then
                status="missing"
                managed=""
                rel=""
                ns=""
            fi
        done
        echo "${name}|${status}|${managed}|${rel}|${ns}" >>"${tmp}"
    done <"${state_file}"
    mv "${tmp}" "${state_file}"
}

if [ $# -lt 2 ]; then
    echo "kubectl stub: unexpected args: $*" >&2
    exit 1
fi

cmd="$1"
resource="$2"
shift 2

case "${cmd}" in
    get)
        crd_name="${resource}"
        if [[ "${resource}" == "crd" && $# -ge 1 ]]; then
            crd_name="$1"
            shift
        fi
        if [[ "${crd_name}" == crd/* ]]; then
            crd_name="${crd_name#crd/}"
        fi

        status=$(read_field "${crd_name}" status)
        if [ "${status}" != "present" ]; then
            exit 1
        fi

        if [ $# -ge 2 ] && [ "$1" = "-o" ]; then
            jsonpath="$2"
            case "${jsonpath}" in
                jsonpath=*) jsonpath="${jsonpath#jsonpath=}" ;;
            esac
            if [[ "${jsonpath}" == *managed-by* ]]; then
                read_field "${crd_name}" managed
            elif [[ "${jsonpath}" == *release-name* ]]; then
                read_field "${crd_name}" rel
            elif [[ "${jsonpath}" == *release-namespace* ]]; then
                read_field "${crd_name}" ns
            fi
        fi
        ;;
    delete)
        if [ "${resource}" != "crd" ]; then
            echo "kubectl stub: only crd deletes are supported" >&2
            exit 1
        fi
        if [ $# -lt 1 ]; then
            echo "kubectl stub: no CRDs provided to delete" >&2
            exit 1
        fi
        log_call "delete crd $*"
        update_after_delete "$@"
        ;;
    *)
        echo "kubectl stub: unsupported command ${cmd}" >&2
        exit 1
        ;;
 esac
