#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"
SUMMARY_LIB="${SUGARKUBE_SUMMARY_LIB:-${SCRIPT_DIR}/lib/summary.sh}"
if [ -f "${SUMMARY_LIB}" ]; then
  # shellcheck source=scripts/lib/summary.sh
  . "${SUMMARY_LIB}"
fi
SUMMARY_DBUS_RECORDED="${SUMMARY_DBUS_RECORDED:-0}"

log_message() {
  local level="$1"
  shift
  local event="$1"
  shift
  local message="$1"
  shift || true
  local safe_message
  safe_message="$(printf '%s' "${message}" | sed 's/"/\\"/g')"
  log_kv "${level}" "${event}" "msg=\"${safe_message}\"" "$@" >&2
}

log_info_msg() {
  local event="$1"
  shift
  local message="$1"
  shift || true
  log_message info "${event}" "${message}" "$@"
}

log_warn_msg() {
  local event="$1"
  shift
  local message="$1"
  shift || true
  log_message info "${event}" "${message}" "severity=warn" "$@"
}

log_error_msg() {
  local event="$1"
  shift
  local message="$1"
  shift || true
  log_message info "${event}" "${message}" "severity=error" "$@"
}

escape_log_value() {
  printf '%s' "$1" | sed 's/"/\\"/g'
}

ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"

if [ "${EUID}" -eq 0 ]; then
  SUDO_CMD="${SUGARKUBE_SUDO_BIN:-}"
else
  if [ "${ALLOW_NON_ROOT}" = "1" ]; then
    SUDO_CMD="${SUGARKUBE_SUDO_BIN:-}"
  else
    SUDO_CMD="${SUGARKUBE_SUDO_BIN:-sudo}"
  fi
fi

if [ -n "${SUDO_CMD:-}" ]; then
  if ! command -v "${SUDO_CMD%% *}" >/dev/null 2>&1; then
    if [ "${ALLOW_NON_ROOT}" = "1" ]; then
      SUDO_CMD=""
    else
      log_error_msg discover "${SUDO_CMD%% *} command not found; run as root or set ALLOW_NON_ROOT=1"
      exit 1
    fi
  fi
fi

if [ -n "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"
else
  export PYTHONPATH="${SCRIPT_DIR}"
fi

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVERS_DESIRED="${SUGARKUBE_SERVERS:-1}"
SERVER_TOKEN_PATH="${SUGARKUBE_K3S_SERVER_TOKEN_PATH:-/var/lib/rancher/k3s/server/token}"
DISCOVERY_WAIT_SECS="${DISCOVERY_WAIT_SECS:-4}"
DISCOVERY_ATTEMPTS="${DISCOVERY_ATTEMPTS:-8}"
MDNS_SELF_CHECK_ATTEMPTS="${SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS:-20}"
MDNS_SELF_CHECK_DELAY="${SUGARKUBE_MDNS_SELF_CHECK_DELAY:-0.5}"
SKIP_MDNS_SELF_CHECK="${SUGARKUBE_SKIP_MDNS_SELF_CHECK:-0}"
SUGARKUBE_MDNS_BOOT_RETRIES="${SUGARKUBE_MDNS_BOOT_RETRIES:-${MDNS_SELF_CHECK_ATTEMPTS}}"
SUGARKUBE_MDNS_BOOT_DELAY="${SUGARKUBE_MDNS_BOOT_DELAY:-${MDNS_SELF_CHECK_DELAY}}"
SUGARKUBE_MDNS_SERVER_RETRIES="${SUGARKUBE_MDNS_SERVER_RETRIES:-20}"
SUGARKUBE_MDNS_SERVER_DELAY="${SUGARKUBE_MDNS_SERVER_DELAY:-0.5}"
SUGARKUBE_MDNS_ALLOW_ADDR_MISMATCH="${SUGARKUBE_MDNS_ALLOW_ADDR_MISMATCH:-1}"
MDNS_ABSENCE_GATE="${SUGARKUBE_MDNS_ABSENCE_GATE:-1}"
MDNS_ABSENCE_TIMEOUT_MS="${SUGARKUBE_MDNS_ABSENCE_TIMEOUT_MS:-15000}"
MDNS_ABSENCE_BACKOFF_START_MS="${SUGARKUBE_MDNS_ABSENCE_BACKOFF_START_MS:-500}"
MDNS_ABSENCE_BACKOFF_CAP_MS="${SUGARKUBE_MDNS_ABSENCE_BACKOFF_CAP_MS:-4000}"
MDNS_ABSENCE_JITTER="${SUGARKUBE_MDNS_ABSENCE_JITTER:-0.25}"
MDNS_ABSENCE_USE_DBUS="${SUGARKUBE_MDNS_ABSENCE_DBUS:-${SUGARKUBE_MDNS_DBUS:-1}}"
MDNS_ABSENCE_LAST_METHOD=""
MDNS_ABSENCE_LAST_STATUS=""
if [ "${MDNS_ABSENCE_USE_DBUS}" = "1" ] && command -v gdbus >/dev/null 2>&1; then
  MDNS_ABSENCE_DBUS_CAPABLE=1
else
  MDNS_ABSENCE_DBUS_CAPABLE=0
fi
if command -v tcpdump >/dev/null 2>&1; then
  TCPDUMP_AVAILABLE=1
else
  TCPDUMP_AVAILABLE=0
fi
if [ -z "${SUGARKUBE_MDNS_WIRE_PROOF:-}" ]; then
  if [ "${TCPDUMP_AVAILABLE}" -eq 1 ]; then
    SUGARKUBE_MDNS_WIRE_PROOF=1
  else
    SUGARKUBE_MDNS_WIRE_PROOF=0
  fi
fi
MDNS_WIRE_PROOF_ENABLED="${SUGARKUBE_MDNS_WIRE_PROOF}"
MDNS_WIRE_PROOF_LAST_STATUS=""
MDNS_WIRE_PROOF_LAST_RESULT=""
MDNS_WIRE_PROOF_DISABLED_LOGGED=0
MDNS_WIRE_PROOF_SKIP_LOGGED=0
MDNS_SELF_CHECK_FAILURE_CODE=94
ELECTION_HOLDOFF="${ELECTION_HOLDOFF:-10}"
FOLLOWER_UNTIL_SERVER=0
FOLLOWER_UNTIL_SERVER_SET_AT=0
FOLLOWER_REELECT_SECS="${FOLLOWER_REELECT_SECS:-60}"
SUGARKUBE_STRICT_IPTABLES="${SUGARKUBE_STRICT_IPTABLES:-0}"
SUGARKUBE_STRICT_TIME="${SUGARKUBE_STRICT_TIME:-0}"
if [ -n "${SUGARKUBE_API_REGADDR:-}" ]; then
  API_REGADDR="${SUGARKUBE_API_REGADDR}"
  while [[ "${API_REGADDR}" == *. ]]; do
    API_REGADDR="${API_REGADDR%.}"
  done
else
  API_REGADDR=""
fi
JOIN_GATE_BIN="${SUGARKUBE_JOIN_GATE_BIN:-${SCRIPT_DIR}/join_gate.sh}"
JOIN_GATE_HELD=0
L4_PROBE_BIN="${SUGARKUBE_L4_PROBE_BIN:-${SCRIPT_DIR}/l4_probe.sh}"
TIME_SYNC_CHECK_BIN="${SUGARKUBE_TIME_SYNC_BIN:-${SCRIPT_DIR}/check_time_sync.sh}"

API_READY_CHECK_BIN="${SUGARKUBE_API_READY_CHECK_BIN:-${SCRIPT_DIR}/check_apiready.sh}"
API_READY_TIMEOUT="${SUGARKUBE_API_READY_TIMEOUT:-120}"
API_READY_POLL_INTERVAL="${SUGARKUBE_API_READY_INTERVAL:-2}"
if [ -n "${SUGARKUBE_SERVER_FLAG_PARITY_BIN:-}" ]; then
  SERVER_FLAG_PARITY_BIN="${SUGARKUBE_SERVER_FLAG_PARITY_BIN}"
else
  SERVER_FLAG_PARITY_BIN="${SCRIPT_DIR}/check_server_flag_parity.sh"
fi

run_net_diag() {
  local reason="$1"
  shift

  local diag_script="${SUGARKUBE_NET_DIAG_BIN:-${SCRIPT_DIR}/net_diag.sh}"
  if [ ! -x "${diag_script}" ]; then
    return 0
  fi

  "${diag_script}" --reason "${reason}" "$@" || true
}

PRINT_TOKEN_ONLY=0
CHECK_TOKEN_ONLY=0

TEST_RUN_AVAHI=""
TEST_RENDER_SERVICE=0
TEST_WAIT_LOOP=0
TEST_PUBLISH_BOOTSTRAP=0
TEST_BOOTSTRAP_SERVER_FLOW=0
TEST_CLAIM_BOOTSTRAP=0
declare -a TEST_RENDER_ARGS=()
PRINT_SERVER_HOSTS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --print-resolved-token)
      PRINT_TOKEN_ONLY=1
      ;;
    --check-token-only)
      CHECK_TOKEN_ONLY=1
      ;;
    --run-avahi-query)
      if [ "$#" -lt 2 ]; then
        echo "--run-avahi-query requires a mode" >&2
        exit 2
      fi
      TEST_RUN_AVAHI="$2"
      shift
      ;;
    --render-avahi-service)
      TEST_RENDER_SERVICE=1
      shift
      TEST_RENDER_ARGS=("$@")
      break
      ;;
    --test-wait-loop-only)
      TEST_WAIT_LOOP=1
      ;;
    --test-bootstrap-publish)
      TEST_PUBLISH_BOOTSTRAP=1
      ;;
    --test-bootstrap-server-flow)
      TEST_BOOTSTRAP_SERVER_FLOW=1
      ;;
    --test-claim-bootstrap)
      TEST_CLAIM_BOOTSTRAP=1
      ;;
    --print-server-hosts)
      PRINT_SERVER_HOSTS=1
      ;;
    --help)
      cat <<'EOF_HELP'
Usage: k3s-discover.sh [--print-resolved-token] [--check-token-only]

  --print-resolved-token  Resolve the effective join token using the
                          standard environment and file fallbacks, print it,
                          then exit.
  --check-token-only      Resolve the token and validate whether discovery
                          can proceed. No network or installer actions are
                          executed.
EOF_HELP
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -* )
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    * )
      break
      ;;
  esac
  shift
done

case "${ENVIRONMENT}" in
  dev) TOKEN="${SUGARKUBE_TOKEN_DEV:-${SUGARKUBE_TOKEN:-}}" ;;
  int) TOKEN="${SUGARKUBE_TOKEN_INT:-${SUGARKUBE_TOKEN:-}}" ;;
  prod) TOKEN="${SUGARKUBE_TOKEN_PROD:-${SUGARKUBE_TOKEN:-}}" ;;
  *) TOKEN="${SUGARKUBE_TOKEN:-}" ;;
esac

RESOLVED_TOKEN_SOURCE=""
INITIAL_TOKEN="${TOKEN:-}"
TOKEN=""

resolve_server_join_token() {
  local resolver="${SCRIPT_DIR}/resolve_server_token.sh"
  local -a resolver_env=()
  local resolved_output=""

  if [ -n "${INITIAL_TOKEN:-}" ]; then
    resolver_env+=("SUGARKUBE_TOKEN=${INITIAL_TOKEN}")
  fi
  if [ -n "${SUGARKUBE_ALLOW_TOKEN_CREATE:-}" ]; then
    resolver_env+=("SUGARKUBE_ALLOW_TOKEN_CREATE=${SUGARKUBE_ALLOW_TOKEN_CREATE}")
  fi
  if [ "${SUGARKUBE_SUDO_BIN+x}" = "x" ]; then
    resolver_env+=("SUGARKUBE_SUDO_BIN=${SUGARKUBE_SUDO_BIN}")
  fi
  if [ "${SUGARKUBE_K3S_BIN+x}" = "x" ]; then
    resolver_env+=("SUGARKUBE_K3S_BIN=${SUGARKUBE_K3S_BIN}")
  fi
  if [ -n "${SERVER_TOKEN_PATH:-}" ]; then
    resolver_env+=("SUGARKUBE_K3S_SERVER_TOKEN_PATH=${SERVER_TOKEN_PATH}")
  fi

  if [ "${#resolver_env[@]}" -gt 0 ]; then
    if ! resolved_output="$(env "${resolver_env[@]}" "${resolver}")"; then
      return 1
    fi
  else
    if ! resolved_output="$("${resolver}")"; then
      return 1
    fi
  fi

  TOKEN="${resolved_output}"
  if [ -n "${TOKEN}" ]; then
    RESOLVED_TOKEN_SOURCE="${resolver}"
  fi

  return 0
}

resolve_server_join_token || true

ALLOW_BOOTSTRAP_WITHOUT_TOKEN=0
SERVER_TOKEN_PRESENT=0
if [ -f "${SERVER_TOKEN_PATH}" ]; then
  SERVER_TOKEN_PRESENT=1
fi

if [ -z "${TOKEN:-}" ]; then
  if [ "${SERVERS_DESIRED}" = "1" ]; then
    ALLOW_BOOTSTRAP_WITHOUT_TOKEN=1
  elif [ "${SERVER_TOKEN_PRESENT}" -eq 0 ]; then
    # No secure join token is yet available locally. Allow the first HA
    # control-plane node to bootstrap so it can mint one for peers.
    ALLOW_BOOTSTRAP_WITHOUT_TOKEN=1
  fi
fi

if [ -z "${TOKEN:-}" ] && [ "${ALLOW_BOOTSTRAP_WITHOUT_TOKEN}" -ne 1 ]; then
  if [ "${CHECK_TOKEN_ONLY}" -eq 1 ]; then
    echo "failed to resolve secure k3s server join token; provide SUGARKUBE_TOKEN or enable SUGARKUBE_ALLOW_TOKEN_CREATE=1" >&2
    exit 1
  fi
  echo "failed to resolve secure k3s server join token; provide SUGARKUBE_TOKEN or enable SUGARKUBE_ALLOW_TOKEN_CREATE=1"
  exit 1
fi

if [ "${PRINT_TOKEN_ONLY}" -eq 1 ]; then
  printf '%s\n' "${TOKEN:-}"
  if [ -n "${RESOLVED_TOKEN_SOURCE:-}" ]; then
    >&2 printf 'token-source=%s\n' "${RESOLVED_TOKEN_SOURCE}"
  fi
  exit 0
fi

if [ "${CHECK_TOKEN_ONLY}" -eq 1 ]; then
  exit 0
fi

MDNS_IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"

HN="$(hostname -s 2>/dev/null || hostname)"

if [ -n "${SUGARKUBE_MDNS_HOST:-}" ]; then
  MDNS_HOST_RAW="${SUGARKUBE_MDNS_HOST}"
else
  _short_host="${HN}"
  case "${_short_host}" in
    *.local)
      MDNS_HOST_RAW="${_short_host}"
      ;;
    *)
      MDNS_HOST_RAW="${_short_host}.local"
      ;;
  esac
fi

while [[ "${MDNS_HOST_RAW}" == *"." ]]; do
  MDNS_HOST_RAW="${MDNS_HOST_RAW%.}"
done
MDNS_HOST="${MDNS_HOST_RAW,,}"

if [ -n "${SUGARKUBE_MDNS_PUBLISH_ADDR:-}" ]; then
  MDNS_ADDR_V4="${SUGARKUBE_MDNS_PUBLISH_ADDR}"
else
  ip_output="$(ip -4 -o addr show "${MDNS_IFACE}" 2>/dev/null || true)"
  MDNS_ADDR_V4="$(printf '%s\n' "${ip_output}" | awk '{print $4}' | cut -d/ -f1 | head -n1)"
fi

if [ -z "${MDNS_ADDR_V4}" ]; then
  log_warn_msg mdns_publish "no IPv4 found" "iface=${MDNS_IFACE}" "action=publish_without_addr"
fi
MDNS_SERVICE_NAME="k3s-${CLUSTER}-${ENVIRONMENT}"
MDNS_SERVICE_TYPE="_${MDNS_SERVICE_NAME}._tcp"
AVAHI_SERVICE_DIR="${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}"
AVAHI_SERVICE_FILE="${SUGARKUBE_AVAHI_SERVICE_FILE:-${AVAHI_SERVICE_DIR}/k3s-${CLUSTER}-${ENVIRONMENT}.service}"
MDNS_LAST_OBSERVED=""
CLAIMED_SERVER_HOST=""
AVAHI_LIVENESS_READY=0
IPTABLES_ENSURED=0
IPTABLES_PREFLIGHT_DONE=0
IPTABLES_PREFLIGHT_OUTCOME=""
IPTABLES_PREFLIGHT_DETAILS=""

run_privileged() {
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" "$@"
  else
    "$@"
  fi
}

iptables_preflight() {
  if [ "${IPTABLES_PREFLIGHT_DONE}" -eq 1 ]; then
    return 0
  fi

  local strict="${SUGARKUBE_STRICT_IPTABLES:-0}"
  local iptables_cmd=""
  local iptables_variant="missing"
  local iptables_version="unavailable"
  local nft_available="no"
  local kube_proxy_mode=""
  local outcome="ok"
  local message="iptables configuration appears compatible"
  local remediation=""
  local version_line=""

  if command -v nft >/dev/null 2>&1; then
    nft_available="yes"
  fi

  if command -v iptables >/dev/null 2>&1; then
    iptables_cmd="$(command -v iptables)"
    version_line="$(iptables --version 2>/dev/null | head -n1 || true)"
    if [ -n "${version_line}" ]; then
      iptables_version="$(printf '%s' "${version_line}" | awk '{print $2}')"
      if printf '%s' "${version_line}" | grep -qi 'nf_tables'; then
        iptables_variant="nf_tables"
      elif printf '%s' "${version_line}" | grep -qi 'legacy'; then
        iptables_variant="legacy"
      else
        iptables_variant="unknown"
      fi
    else
      iptables_variant="unknown"
      iptables_version="unknown"
    fi
  else
    outcome="warn"
    message="iptables binary is missing"
    remediation="install_iptables_package"
  fi

  if [ -n "${SUGARKUBE_KUBE_PROXY_MODE:-}" ]; then
    kube_proxy_mode="${SUGARKUBE_KUBE_PROXY_MODE}"
  elif [ -n "${K3S_KUBE_PROXY_MODE:-}" ]; then
    kube_proxy_mode="${K3S_KUBE_PROXY_MODE}"
  elif [ -n "${KUBE_PROXY_MODE:-}" ]; then
    kube_proxy_mode="${KUBE_PROXY_MODE}"
  else
    kube_proxy_mode="iptables (default)"
  fi

  if [ -n "${INSTALL_K3S_EXEC:-}" ] && printf '%s' "${INSTALL_K3S_EXEC}" | grep -q -- '--disable-kube-proxy'; then
    kube_proxy_mode="disabled"
  fi

  if [ "${outcome}" = "ok" ] && [ "${iptables_variant}" = "nf_tables" ]; then
    outcome="warn"
    message="iptables is using the nf_tables backend which is known to break k3s kube-proxy"
    remediation="use_update-alternatives_to_select_iptables-legacy"
  fi

  if [ "${outcome}" = "warn" ] && [ "${nft_available}" = "no" ] && [ "${iptables_variant}" = "nf_tables" ]; then
    remediation="install_nftables_or_switch_to_iptables-legacy"
  fi

  local safe_kube_proxy_mode
  safe_kube_proxy_mode="$(printf '%s' "${kube_proxy_mode}" | tr ' ' '_' | tr -d '"')"

  local details
  details="variant=${iptables_variant},version=${iptables_version},nft=${nft_available},kube-proxy=${safe_kube_proxy_mode}"
  if [ -n "${iptables_cmd}" ]; then
    details="${details},path=${iptables_cmd}"
  fi

  IPTABLES_PREFLIGHT_DONE=1
  IPTABLES_PREFLIGHT_OUTCOME="${outcome}"
  IPTABLES_PREFLIGHT_DETAILS="${details}"

  local -a log_pairs=(
    "outcome=${outcome}"
    "details=\"$(escape_log_value "${details}")\""
    "variant=${iptables_variant}"
    "version=${iptables_version}"
    "nft_available=${nft_available}"
    "kube_proxy_mode=\"$(escape_log_value "${kube_proxy_mode}")\""
  )

  if [ -n "${remediation}" ]; then
    log_pairs+=("remediation=\"$(escape_log_value "${remediation}")\"")
  fi

  if [ "${outcome}" = "warn" ]; then
    log_warn_msg iptables_preflight "${message}" "${log_pairs[@]}"
    if [ "${strict}" = "1" ]; then
      log_error_msg iptables_preflight "Failing due to SUGARKUBE_STRICT_IPTABLES=1" \
        "outcome=${outcome}" \
        "details=\"$(escape_log_value "${details}")\""
      exit 1
    fi
  else
    log_info_msg iptables_preflight "${message}" "${log_pairs[@]}"
  fi

  return 0
}

run_configure_avahi() {
  local configure_script
  configure_script="${SUGARKUBE_CONFIGURE_AVAHI_BIN:-${SCRIPT_DIR}/configure_avahi.sh}"
  if [ ! -x "${configure_script}" ]; then
    return 0
  fi

  local -a command=("${configure_script}")
  if [ -n "${SUDO_CMD:-}" ]; then
    command=("${SUDO_CMD}" "${configure_script}")
  fi

  if "${command[@]}" >/dev/null 2>&1; then
    log_info discover event=configure_avahi outcome=ok script="${configure_script}" >&2
    return 0
  fi

  local status=$?
  log_error_msg discover "configure_avahi.sh failed" "status=${status}" "script=${configure_script}"
  exit "${status}"
}

write_privileged_file() {
  local path="$1"
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" tee "${path}" >/dev/null
  else
    cat >"${path}"
  fi
}

remove_privileged_file() {
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" rm -f "$1"
  else
    rm -f "$1"
  fi
}

run_configure_avahi

iptables_preflight

reload_avahi_daemon() {
  if [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  AVAHI_LIVENESS_READY=0
  local reload_status=0
  if [ -n "${SUDO_CMD:-}" ]; then
    if ! "${SUDO_CMD}" systemctl reload avahi-daemon; then
      reload_status=$?
      if ! "${SUDO_CMD}" systemctl restart avahi-daemon; then
        return "${reload_status}"
      fi
    fi
  else
    if ! systemctl reload avahi-daemon; then
      reload_status=$?
      if ! systemctl restart avahi-daemon; then
        return "${reload_status}"
      fi
    fi
  fi

  if ! ensure_avahi_liveness_signal; then
    return 1
  fi

  return 0
}

restart_avahi_daemon_service() {
  if [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" systemctl restart avahi-daemon
  else
    systemctl restart avahi-daemon
  fi
}

cleanup_avahi_publishers() {
  if [ -f "${AVAHI_SERVICE_FILE}" ]; then
    remove_privileged_file "${AVAHI_SERVICE_FILE}" || true
    reload_avahi_daemon || true
  fi
}

ensure_avahi_liveness_signal() {
  local summary_active=0
  local summary_start=0
  local summary_recorded=0
  local summary_note=""

  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled && [ "${SUMMARY_DBUS_RECORDED}" -eq 0 ]; then
    summary_active=1
    summary_start="$(summary_now_ms)"
  fi

  if [ "${AVAHI_LIVENESS_READY}" -eq 1 ]; then
    if [ "${summary_active}" -eq 1 ]; then
      summary_step "D-Bus readiness" "OK" "$(summary_elapsed_ms "${summary_start}")" "cached=1"
      SUMMARY_DBUS_RECORDED=1
      summary_recorded=1
    fi
    return 0
  fi

  local wait_status=0
  local dbus_note=""
  if command -v gdbus >/dev/null 2>&1; then
    if "${SCRIPT_DIR}/wait_for_avahi_dbus.sh"; then
      log_info discover event=avahi_liveness_dbus outcome=ok >&2
    else
      wait_status=$?
      if [ "${wait_status}" -eq 2 ]; then
        dbus_note="dbus=disabled"
        log_info discover event=avahi_liveness_dbus outcome=disabled severity=info >&2
      else
        log_warn_msg discover "Avahi D-Bus wait failed" "event=avahi_liveness" "status=${wait_status}" >&2
      fi
    fi
  else
    dbus_note="dbus=missing"
    log_info discover event=avahi_liveness_dbus outcome=skip reason=gdbus_missing severity=info >&2
  fi

  local attempt
  local status
  local browse_output
  local lines
  for attempt in 1 2; do
    status=0
    browse_output=""
    if ! browse_output="$(avahi-browse --all --terminate --timeout=2 2>/dev/null)"; then
      status=$?
      browse_output=""
    fi
    lines="$(printf '%s\n' "${browse_output}" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [ "${status}" -eq 0 ] && [ -n "${lines}" ] && [ "${lines}" -gt 0 ]; then
      log_info discover event=avahi_liveness outcome=ok attempt="${attempt}" lines="${lines}" >&2
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_note="attempt=${attempt} lines=${lines}"
        if [ -n "${dbus_note}" ]; then
          summary_note+=" ${dbus_note}"
        fi
        summary_step "D-Bus readiness" "OK" \
          "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note}"
        SUMMARY_DBUS_RECORDED=1
        summary_recorded=1
      fi
      AVAHI_LIVENESS_READY=1
      return 0
    fi
    log_warn_msg discover "Avahi liveness probe retry" "attempt=${attempt}" "status=${status}" "lines=${lines:-0}" >&2
    if [ "${attempt}" -eq 1 ]; then
      sleep 1
    fi
  done

  if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
    summary_note="attempts=2 status=${status}"
    if [ -n "${dbus_note}" ]; then
      summary_note+=" ${dbus_note}"
    fi
    if [ "${wait_status}" -ne 0 ] && [ -z "${dbus_note}" ]; then
      summary_note+=" wait_status=${wait_status}"
    fi
    summary_step "D-Bus readiness" "FAIL" \
      "$(summary_elapsed_ms "${summary_start}")" \
      "${summary_note}"
    SUMMARY_DBUS_RECORDED=1
    summary_recorded=1
  fi

  log_error_msg discover "Avahi liveness probe failed" "event=avahi_liveness" >&2
  return 1
}

render_avahi_service_xml() {
  local role="$1"; shift
  local port="${1:-6443}"; shift || true
  local phase=""
  local leader=""
  local arg
  for arg in "$@"; do
    case "${arg}" in
      phase=*)
        phase="${arg#phase=}"
        ;;
      leader=*)
        leader="${arg#leader=}"
        ;;
    esac
  done

  python3 - <<'PY' \
    "${CLUSTER}" \
    "${ENVIRONMENT}" \
    "${role}" \
    "${port}" \
    "${phase}" \
    "${leader}"
import html
import sys

cluster, environment, role, port, phase, leader = sys.argv[1:7]
host = "%h"

service_name = f"k3s-{cluster}-{environment}@{host} ({role})"
service_type = f"_k3s-{cluster}-{environment}._tcp"

records = [
    ("k3s", "1"),
    ("cluster", cluster),
    ("env", environment),
    ("role", role),
    ("phase", phase),
    ("leader", leader),
]

def esc(value: str) -> str:
    return html.escape(value, quote=True)

print("<?xml version=\"1.0\" standalone='no'?>")
print("<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">")
print("<service-group>")
print(f"  <name replace-wildcards=\"yes\">{esc(service_name)}</name>")
print("  <service>")
print(f"    <type>{esc(service_type)}</type>")
print(f"    <port>{esc(str(port))}</port>")
for key, value in records:
    print(f"    <txt-record>{esc(f'{key}={value}')}</txt-record>")
print("  </service>")
print("</service-group>")
PY
}

current_time_ms() {
  python3 - <<'PY'
import time

print(int(time.time() * 1000))
PY
}

elapsed_since_ms() {
  python3 - "$1" <<'PY'
import sys
import time

try:
    start = int(sys.argv[1])
except (IndexError, ValueError):
    start = 0
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
}

compute_absence_delay_ms() {
  python3 - "$@" <<'PY'
import random
import sys

try:
    attempt = int(sys.argv[1])
except (IndexError, ValueError):
    attempt = 1
try:
    start = int(sys.argv[2])
except (IndexError, ValueError):
    start = 0
try:
    cap = int(sys.argv[3])
except (IndexError, ValueError):
    cap = 0
try:
    jitter = float(sys.argv[4])
except (IndexError, ValueError):
    jitter = 0.0

if attempt < 1:
    attempt = 1
if start < 0:
    start = 0
if cap < 0:
    cap = 0

if cap and start > cap:
    base = cap
else:
    base = start * (2 ** (attempt - 1)) if attempt > 0 else start

if cap and base > cap:
    base = cap

if jitter > 0:
    low = max(0.0, 1.0 - jitter)
    high = 1.0 + jitter
    delay = int(base * random.uniform(low, high))
else:
    delay = base

if delay < 0:
    delay = 0

print(delay)
PY
}

mdns_absence_check_dbus() {
  if [ "${MDNS_ABSENCE_USE_DBUS}" != "1" ]; then
    return 2
  fi
  if [ "${MDNS_ABSENCE_DBUS_CAPABLE}" -ne 1 ]; then
    return 2
  fi
  if ! command -v gdbus >/dev/null 2>&1; then
    MDNS_ABSENCE_DBUS_CAPABLE=0
    return 2
  fi

  if ! "${SCRIPT_DIR}/wait_for_avahi_dbus.sh"; then
    local wait_status=$?
    if [ "${wait_status}" -eq 2 ]; then
      MDNS_ABSENCE_DBUS_CAPABLE=0
      log_info discover \
        event=mdns_absence_dbus \
        outcome=skip \
        reason=avahi_dbus_disabled \
        severity=info >&2
    fi
    return 2
  fi

  local service_domain
  service_domain="${SUGARKUBE_MDNS_DOMAIN:-local}"

  if ! gdbus call \
    --system \
    --dest org.freedesktop.Avahi \
    --object-path / \
    --method org.freedesktop.Avahi.Server.ServiceBrowserNew \
    int32:-1 \
    int32:-1 \
    "${MDNS_SERVICE_TYPE}" \
    "${service_domain}" \
    uint32:0 >/dev/null 2>&1; then
    local status=$?
    if [ "${status}" -eq 126 ] || [ "${status}" -eq 127 ]; then
      return 2
    fi
    return 2
  fi

  local base_instance
  base_instance="k3s-${CLUSTER}-${ENVIRONMENT}@${MDNS_HOST_RAW}"
  local -a candidates=(
    "${base_instance}"
    "${base_instance} (server)"
    "${base_instance} (bootstrap)"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    [ -n "${candidate}" ] || continue
    if gdbus call \
      --system \
      --dest org.freedesktop.Avahi \
      --object-path / \
      --method org.freedesktop.Avahi.Server.ResolveService \
      int32:-1 \
      int32:-1 \
      "${candidate}" \
      "${MDNS_SERVICE_TYPE}" \
      "${service_domain}" \
      int32:-1 \
      uint32:0 >/dev/null 2>&1; then
      return 1
    fi
  done

  return 0
}

mdns_absence_check_cli() {
  python3 - "${MDNS_SERVICE_TYPE}" "${CLUSTER}" "${ENVIRONMENT}" "${MDNS_HOST_RAW}" <<'PY'
import subprocess
import sys

from k3s_mdns_parser import parse_mdns_records
from mdns_helpers import _norm_host

service_type, cluster, environment, target = sys.argv[1:5]
command = [
    "avahi-browse",
    "-rptk",
    service_type,
]

try:
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
except FileNotFoundError:
    sys.exit(2)

lines = [line for line in proc.stdout.splitlines() if line]
records = parse_mdns_records(lines, cluster, environment)
target_norm = _norm_host(target)

for record in records:
    if _norm_host(record.host) == target_norm:
        sys.exit(1)

sys.exit(0)
PY
}

mdns_wire_proof_check() {
  MDNS_WIRE_PROOF_LAST_RESULT=""

  if [ "${MDNS_WIRE_PROOF_ENABLED}" != "1" ]; then
    if [ "${MDNS_WIRE_PROOF_DISABLED_LOGGED}" -ne 1 ]; then
      log_info discover event=mdns_wire_proof outcome=skip wire_proof_enabled=0 \
        tcpdump_available="${TCPDUMP_AVAILABLE}" >&2
      MDNS_WIRE_PROOF_DISABLED_LOGGED=1
    fi
    MDNS_WIRE_PROOF_LAST_STATUS="disabled"
    MDNS_WIRE_PROOF_LAST_RESULT="wire_proof=disabled"
    return 0
  fi

  if [ "${TCPDUMP_AVAILABLE}" -ne 1 ]; then
    if [ "${MDNS_WIRE_PROOF_SKIP_LOGGED}" -ne 1 ]; then
      log_info discover event=mdns_wire_proof outcome=skip wire_proof_enabled=1 \
        tcpdump_available=0 >&2
      MDNS_WIRE_PROOF_SKIP_LOGGED=1
    fi
    MDNS_WIRE_PROOF_LAST_STATUS="tcpdump_unavailable"
    MDNS_WIRE_PROOF_LAST_RESULT="tcpdump_available=0"
    return 0
  fi

  local duration
  duration="${SUGARKUBE_MDNS_WIRE_PROOF_DURATION:-2.5}"

  local output
  output="$(python3 - "${MDNS_IFACE}" "${CLUSTER}" "${ENVIRONMENT}" "${MDNS_HOST_RAW}" "${duration}" <<'PY'
import select
import signal
import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv) < 6:
        print("matched=0 frames=0 https_lines=0 port_lines=0 return_code=1 error=1")
        return 2

    iface, cluster, env, host, raw_duration = sys.argv[1:6]

    try:
        duration = float(raw_duration)
    except ValueError:
        duration = 2.5
    if duration <= 0:
        duration = 2.5

    short_host = host
    if host.lower().endswith(".local"):
        short_host = host[: -len(".local")]

    prefix = f"k3s-{cluster}-{env}@"
    candidates = {host.lower(), short_host.lower()}
    patterns = {prefix.lower()}
    for candidate in candidates:
        if candidate:
            patterns.add(f"{prefix}{candidate}".lower())
            patterns.add(candidate)
            patterns.add(f"{candidate}._https._tcp")
            patterns.add(f"{candidate}._https._tcp.local")

    patterns = {pattern for pattern in patterns if pattern}

    command = [
        "tcpdump",
        "-l",
        "-n",
        "-vvv",
        "-s",
        "0",
        "udp",
        "port",
        "5353",
    ]
    if iface:
        command.extend(["-i", iface])

    proc = None
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        print("matched=0 frames=0 https_lines=0 port_lines=0 return_code=127 error=1")
        return 2

    start = time.monotonic()
    frames = 0
    https_lines = 0
    port_lines = 0
    matched_line = ""

    try:
        while True:
            now = time.monotonic()
            if duration > 0:
                remaining = (start + duration) - now
                if remaining <= 0:
                    break
                timeout = max(0.0, min(0.25, remaining))
            else:
                timeout = 0.25

            if proc.poll() is not None:
                line = proc.stdout.readline()
                if not line:
                    break
            else:
                ready = []
                try:
                    ready = select.select([proc.stdout], [], [], timeout)[0]
                except (OSError, ValueError):
                    ready = [proc.stdout]

                if not ready:
                    continue

                line = proc.stdout.readline()
                if not line:
                    continue

            frames += 1
            candidate = line.strip()
            lower = candidate.lower()

            if "_https._tcp" in lower:
                https_lines += 1
                if not matched_line:
                    for pattern in patterns:
                        if pattern in lower:
                            matched_line = candidate
                            break

            if "port 6443" in lower or " 6443" in lower:
                port_lines += 1
    finally:
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    return_code = 0
    if proc is not None and proc.returncode is not None:
        return_code = proc.returncode

    match_detected = bool(matched_line) and port_lines > 0
    error_flag = 0 if return_code in (0, 130) else 1

    print(
        "matched={matched} frames={frames} https_lines={https_lines} "
        "port_lines={port_lines} return_code={return_code} error={error}".format(
            matched="1" if match_detected else "0",
            frames=frames,
            https_lines=https_lines,
            port_lines=port_lines,
            return_code=return_code,
            error=error_flag,
        )
    )

    if match_detected:
        return 1
    if error_flag:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY
)"
  local status=$?

  MDNS_WIRE_PROOF_LAST_RESULT="${output}"

  case "${status}" in
    0)
      MDNS_WIRE_PROOF_LAST_STATUS="absent"
      # shellcheck disable=SC2086
      log_info discover event=mdns_wire_proof outcome=absent ${MDNS_WIRE_PROOF_LAST_RESULT} >&2
      ;;
    1)
      MDNS_WIRE_PROOF_LAST_STATUS="present"
      # shellcheck disable=SC2086
      log_warn_msg discover "wire proof detected DNS-SD answers" \
        "mdns_wire_proof_status=present" ${MDNS_WIRE_PROOF_LAST_RESULT} >&2
      ;;
    2)
      MDNS_WIRE_PROOF_LAST_STATUS="error"
      # shellcheck disable=SC2086
      log_warn_msg discover "wire proof failed" "mdns_wire_proof_status=error" \
        ${MDNS_WIRE_PROOF_LAST_RESULT} >&2
      ;;
    *)
      MDNS_WIRE_PROOF_LAST_STATUS="error"
      # shellcheck disable=SC2086
      log_warn_msg discover "wire proof failed" "mdns_wire_proof_status=error" \
        ${MDNS_WIRE_PROOF_LAST_RESULT} >&2
      ;;
  esac

  return "${status}"
}

check_mdns_absence_once() {
  MDNS_ABSENCE_LAST_METHOD=""
  MDNS_ABSENCE_LAST_STATUS="unknown"

  local status
  if mdns_absence_check_dbus; then
    status=0
  else
    status=$?
  fi
  if [ "${status}" -ne 2 ]; then
    MDNS_ABSENCE_LAST_METHOD="dbus"
    case "${status}" in
      0) MDNS_ABSENCE_LAST_STATUS="absent" ;;
      1) MDNS_ABSENCE_LAST_STATUS="present" ;;
      *) MDNS_ABSENCE_LAST_STATUS="unknown" ;;
    esac
    return "${status}"
  fi

  if mdns_absence_check_cli; then
    status=0
  else
    status=$?
  fi
  if [ "${status}" -ne 2 ]; then
    MDNS_ABSENCE_LAST_METHOD="cli"
    case "${status}" in
      0) MDNS_ABSENCE_LAST_STATUS="absent" ;;
      1) MDNS_ABSENCE_LAST_STATUS="present" ;;
      *) MDNS_ABSENCE_LAST_STATUS="unknown" ;;
    esac
    return "${status}"
  fi

  MDNS_ABSENCE_LAST_METHOD="none"
  MDNS_ABSENCE_LAST_STATUS="unknown"
  return 2
}

ensure_mdns_absence_gate() {
  if [ "${MDNS_ABSENCE_GATE}" != "1" ]; then
    return 0
  fi

  local timeout_ms="${MDNS_ABSENCE_TIMEOUT_MS}"
  case "${timeout_ms}" in
    ''|*[!0-9]*) timeout_ms=15000 ;;
  esac

  local backoff_start="${MDNS_ABSENCE_BACKOFF_START_MS}"
  case "${backoff_start}" in
    ''|*[!0-9]*) backoff_start=500 ;;
  esac

  local backoff_cap="${MDNS_ABSENCE_BACKOFF_CAP_MS}"
  case "${backoff_cap}" in
    ''|*[!0-9]*) backoff_cap=4000 ;;
  esac

  local jitter="${MDNS_ABSENCE_JITTER}"

  local start_ms
  start_ms="$(current_time_ms)"

  log_info discover event=mdns_absence_gate phase=start host="${MDNS_HOST_RAW}" service="${MDNS_SERVICE_TYPE}" timeout_ms="${timeout_ms}" >&2

  if restart_avahi_daemon_service; then
    log_info discover event=mdns_absence_gate action=restart_avahi outcome=ok >&2
  else
    log_warn_msg discover "failed to restart avahi-daemon" "action=restart_avahi" >&2
  fi

  local attempts=0
  local consecutive_absent=0
  local consecutive_dbus_absent=0
  local presence_seen=0
  local wire_presence_seen=0
  local elapsed_ms=0
  local last_status="unknown"
  local last_method="none"
  local status=2
  local dbus_requirement_met=0
  local require_wire_proof=1
  local wire_absent_window=0

  if [ "${MDNS_ABSENCE_DBUS_CAPABLE}" -ne 1 ]; then
    dbus_requirement_met=1
    log_info discover event=mdns_absence_gate action=dbus_requirement_skip dbus_available=0 >&2
  fi

  if [ "${MDNS_WIRE_PROOF_ENABLED}" != "1" ] || [ "${TCPDUMP_AVAILABLE}" -ne 1 ]; then
    require_wire_proof=0
    mdns_wire_proof_check >/dev/null 2>&1 || true
    wire_absent_window=1
  fi

  while :; do
    attempts=$((attempts + 1))
    if check_mdns_absence_once; then
      status=0
    else
      status=$?
    fi
    last_method="${MDNS_ABSENCE_LAST_METHOD:-none}"
    last_status="${MDNS_ABSENCE_LAST_STATUS:-unknown}"

    case "${status}" in
      0)
        consecutive_absent=$((consecutive_absent + 1))
        if [ "${last_method}" = "dbus" ]; then
          consecutive_dbus_absent=$((consecutive_dbus_absent + 1))
        else
          consecutive_dbus_absent=0
        fi
        ;;
      1)
        presence_seen=1
        consecutive_absent=0
        consecutive_dbus_absent=0
        if [ "${MDNS_ABSENCE_DBUS_CAPABLE}" -eq 1 ]; then
          dbus_requirement_met=0
        else
          dbus_requirement_met=1
        fi
        if [ "${require_wire_proof}" -eq 1 ]; then
          wire_absent_window=0
        fi
        ;;
      *)
        consecutive_absent=0
        consecutive_dbus_absent=0
        if [ "${require_wire_proof}" -eq 1 ]; then
          wire_absent_window=0
        fi
        ;;
    esac

    if [ "${last_method}" = "dbus" ] && [ "${status}" -eq 0 ] && [ "${consecutive_dbus_absent}" -ge 2 ]; then
      dbus_requirement_met=1
    fi

    if [ "${require_wire_proof}" -eq 1 ] && [ "${dbus_requirement_met}" -eq 1 ] && [ "${wire_absent_window}" -ne 1 ]; then
      if mdns_wire_proof_check; then
        wire_absent_window=1
      else
        local wire_status=$?
        if [ "${wire_status}" -eq 1 ]; then
          wire_presence_seen=1
          presence_seen=1
          consecutive_absent=0
          consecutive_dbus_absent=0
          dbus_requirement_met=0
          wire_absent_window=0
        elif [ "${wire_status}" -eq 2 ]; then
          wire_absent_window=0
        fi
      fi
    fi

    local -a absence_gate_log_fields=(
      "event=mdns_absence_gate"
      "attempt=\"${attempts}\""
      "method=\"${last_method}\""
      "status=\"${last_status}\""
      "consecutive_absent=\"${consecutive_absent}\""
      "consecutive_dbus_absent=\"${consecutive_dbus_absent}\""
      "dbus_requirement_met=\"${dbus_requirement_met}\""
      "wire_absent_window=\"${wire_absent_window}\""
      "wire_proof_status=\"${MDNS_WIRE_PROOF_LAST_STATUS:-skipped}\""
    )

    if [ "${IPTABLES_PREFLIGHT_DONE:-0}" -eq 1 ]; then
      local iptables_outcome="${IPTABLES_PREFLIGHT_OUTCOME:-unknown}"
      absence_gate_log_fields+=("iptables_preflight_outcome=\"${iptables_outcome}\"")

      if [ -n "${IPTABLES_PREFLIGHT_DETAILS:-}" ]; then
        local iptables_details="${IPTABLES_PREFLIGHT_DETAILS//\"/\\\"}"
        absence_gate_log_fields+=("iptables_preflight_details=\"${iptables_details}\"")
      fi
    fi

    log_debug discover "${absence_gate_log_fields[@]}" >&2

    elapsed_ms="$(elapsed_since_ms "${start_ms}")"

    if [ "${consecutive_absent}" -ge 2 ] && [ "${dbus_requirement_met}" -eq 1 ] && [ "${wire_absent_window}" -eq 1 ]; then
      break
    fi

    if [ "${timeout_ms}" -gt 0 ] && [ "${elapsed_ms}" -ge "${timeout_ms}" ]; then
      break
    fi

    local delay_ms
    delay_ms="$(compute_absence_delay_ms "${attempts}" "${backoff_start}" "${backoff_cap}" "${jitter}")"
    case "${delay_ms}" in
      ''|*[!0-9]*) delay_ms=0 ;;
    esac
    if [ "${delay_ms}" -gt 0 ]; then
      local delay_s
      delay_s="$(python3 - "${delay_ms}" <<'PY'
import sys

try:
    value = int(sys.argv[1])
except (IndexError, ValueError):
    value = 0
if value < 0:
    value = 0
print(value / 1000.0)
PY
)"
      sleep "${delay_s}"
    fi
  done

  local confirmed=0
  if [ "${consecutive_absent}" -ge 2 ] && [ "${dbus_requirement_met}" -eq 1 ] && [ "${wire_absent_window}" -eq 1 ]; then
    confirmed=1
  fi

  local reason=""
  if [ "${confirmed}" -ne 1 ]; then
    if [ "${timeout_ms}" -gt 0 ] && [ "${elapsed_ms}" -ge "${timeout_ms}" ]; then
      reason="timeout"
    elif [ "${wire_presence_seen}" -eq 1 ]; then
      reason="wire_presence_detected"
    elif [ "${presence_seen}" -eq 1 ]; then
      reason="presence_detected"
    elif [ "${dbus_requirement_met}" -ne 1 ]; then
      reason="dbus_requirement_unmet"
    elif [ "${wire_absent_window}" -ne 1 ]; then
      reason="wire_absence_unconfirmed"
    else
      reason="unconfirmed"
    fi
  fi

  if [ "${confirmed}" -eq 1 ]; then
    log_info discover event=mdns_absence_gate mdns_absence_confirmed=1 attempts="${attempts}" \
      ms_elapsed="${elapsed_ms}" last_method="${last_method}" consecutive_absent="${consecutive_absent}" \
      consecutive_dbus_absent="${consecutive_dbus_absent}" wire_proof_status="${MDNS_WIRE_PROOF_LAST_STATUS:-skipped}" >&2
  else
    log_warn_msg discover "mDNS absence gate timed out" "mdns_absence_confirmed=0" \
      "attempts=${attempts}" "ms_elapsed=${elapsed_ms}" "reason=${reason}" "last_method=${last_method}" \
      "consecutive_dbus_absent=${consecutive_dbus_absent}" "wire_proof_status=${MDNS_WIRE_PROOF_LAST_STATUS:-skipped}" >&2
  fi

  return 0
}

norm_host() {
  local host="${1:-}"
  while [[ "${host}" == *"." ]]; do
    host="${host%.}"
  done
  printf '%s\n' "${host,,}"
}

strip_local_suffix() {
  local host="${1:-}"
  while [[ "${host}" == *.local ]]; do
    host="${host%.local}"
  done
  printf '%s\n' "${host}"
}

canonical_host() {
  local host
  host="$(norm_host "${1:-}")"
  while [[ "${host}" == *.local.local ]]; do
    host="${host%.local}"
  done
  printf '%s\n' "${host}"
}

same_host() {
  local left right left_base right_base
  left="$(norm_host "${1:-}")"
  right="$(norm_host "${2:-}")"
  if [ -z "${left}" ] || [ -z "${right}" ]; then
    return 1
  fi
  if [ "${left}" = "${right}" ]; then
    return 0
  fi
  left_base="$(strip_local_suffix "${left}")"
  right_base="$(strip_local_suffix "${right}")"
  if [ "${left_base}" = "${left}" ] && [ "${right_base}" = "${right}" ]; then
    return 1
  fi
  [ -n "${left_base}" ] && [ "${left_base}" = "${right_base}" ]
}

run_avahi_query() {
  local mode="$1"
  python3 - "${mode}" "${CLUSTER}" "${ENVIRONMENT}" <<'PY'
import os
import sys

from k3s_mdns_query import query_mdns


mode, cluster, environment = sys.argv[1:4]

fixture_path = os.environ.get("SUGARKUBE_MDNS_FIXTURE_FILE")
debug_enabled = bool(os.environ.get("SUGARKUBE_DEBUG"))


def debug(message: str) -> None:
    if debug_enabled:
        print(f"[k3s-discover mdns] {message}", file=sys.stderr)


results = query_mdns(
    mode,
    cluster,
    environment,
    fixture_path=fixture_path,
    debug=debug if debug_enabled else None,
)

for line in results:
    print(line)
PY
}

discover_server_host() {
  run_avahi_query server-first | head -n1
}

discover_server_hosts() {
  run_avahi_query server-hosts | sort -u
}

discover_bootstrap_hosts() {
  run_avahi_query bootstrap-hosts | sort -u
}

discover_bootstrap_leaders() {
  run_avahi_query bootstrap-leaders | sort -u
}

join_target_host() {
  local discovered="$1"
  if [ -n "${API_REGADDR:-}" ]; then
    printf '%s\n' "${API_REGADDR}"
    return 0
  fi
  printf '%s\n' "${discovered}"
}

ensure_self_mdns_advertisement() {
  local role="$1"
  local summary_active=0
  local summary_start=0
  local summary_recorded=0
  local summary_note="role=${role}"

  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled; then
    summary_active=1
    summary_start="$(summary_now_ms)"
  fi

  if [ "${SKIP_MDNS_SELF_CHECK}" = "1" ]; then
    MDNS_LAST_OBSERVED="${MDNS_HOST_RAW}"
    if [ "${summary_active}" -eq 1 ]; then
      summary_step "Self-check (mDNS)" "SKIP" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=skip"
      summary_recorded=1
    fi
    return 0
  fi

  local retries delay
  case "${role}" in
    bootstrap)
      retries="${SUGARKUBE_MDNS_BOOT_RETRIES}"
      delay="${SUGARKUBE_MDNS_BOOT_DELAY}"
      ;;
    server)
      retries="${SUGARKUBE_MDNS_SERVER_RETRIES}"
      delay="${SUGARKUBE_MDNS_SERVER_DELAY}"
      ;;
    *)
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_step "Self-check (mDNS)" "SKIP" "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note} reason=unknown-role"
        summary_recorded=1
      fi
      return 0
      ;;
  esac

  log_info mdns_selfcheck phase=start role="${role}" host="${MDNS_HOST_RAW}" attempts="${retries}" >&2

  MDNS_LAST_OBSERVED=""
  local delay_ms=""
  if [ -n "${delay}" ]; then
    delay_ms="$(SELFCHK_DELAY="${delay}" python3 - <<'PY'
import os

raw = os.environ.get("SELFCHK_DELAY", "0")
try:
    value = float(raw)
except ValueError:
    value = 0.0
if value < 0:
    value = 0.0
print(int(value * 1000))
PY
)"
  fi

  local -a selfcheck_env=(
    "SUGARKUBE_CLUSTER=${CLUSTER}"
    "SUGARKUBE_ENV=${ENVIRONMENT}"
    "SUGARKUBE_EXPECTED_HOST=${MDNS_HOST_RAW}"
    "SUGARKUBE_SELFCHK_ATTEMPTS=${retries}"
    "SUGARKUBE_EXPECTED_ROLE=${role}"
    "SUGARKUBE_EXPECTED_PHASE=${role}"
  )
  if [ -n "${delay_ms}" ]; then
    case "${delay_ms}" in
      ''|*[!0-9]*) delay_ms="" ;;
      0) delay_ms="" ;;
    esac
  fi
  if [ -n "${delay_ms}" ]; then
    selfcheck_env+=("SUGARKUBE_SELFCHK_BACKOFF_START_MS=${delay_ms}" "SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=${delay_ms}")
  fi
  if [ -n "${MDNS_ADDR_V4}" ]; then
    selfcheck_env+=("SUGARKUBE_EXPECTED_IPV4=${MDNS_ADDR_V4}")
  fi

  local selfcheck_output=""
  local observed_host="${MDNS_HOST_RAW}"
  local -a diag_args=("--iface" "${MDNS_IFACE}")
  if [ -n "${retries}" ]; then
    diag_args+=("--attempt" "${retries}")
  fi
  diag_args+=(
    "--tag" "role=${role}"
    "--tag" "host=${MDNS_HOST_RAW}"
    "--tag" "cluster=${CLUSTER}"
    "--tag" "environment=${ENVIRONMENT}"
  )
  if [ -n "${MDNS_ADDR_V4}" ]; then
    diag_args+=("--tag" "expected_ipv4=${MDNS_ADDR_V4}")
  else
    diag_args+=("--tag" "expected_ipv4=none")
  fi

  local relaxed_attempted=0
  local relaxed_status="not_attempted"

  local selfcheck_start_ms
  selfcheck_start_ms="$(python3 - <<'PY'
import time
print(int(time.monotonic() * 1000))
PY
)"

  local status=0
  if selfcheck_output="$(env "${selfcheck_env[@]}" "${MDNS_SELF_CHECK_BIN}")"; then
    local token summary_attempts summary_elapsed
    summary_attempts="${retries}"
    summary_elapsed=""
    for token in ${selfcheck_output}; do
      case "${token}" in
        host=*)
          observed_host="${token#host=}"
          ;;
        attempts=*)
          summary_attempts="${token#attempts=}"
          ;;
        ms_elapsed=*)
          summary_elapsed="${token#ms_elapsed=}"
          ;;
      esac
    done
    if [ -z "${observed_host}" ]; then
      observed_host="${MDNS_HOST_RAW}"
    fi
    MDNS_LAST_OBSERVED="$(canonical_host "${observed_host}")"
    case "${summary_elapsed}" in
      ''|*[!0-9]*) summary_elapsed="" ;;
    esac
    if [ -z "${summary_elapsed}" ]; then
      local measured_elapsed
      measured_elapsed="$(python3 - "${selfcheck_start_ms}" <<'PY'
import sys
import time

try:
    start = int(sys.argv[1])
except (IndexError, ValueError):
    start = 0
now = int(time.monotonic() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
)"
      case "${measured_elapsed}" in
        ''|*[!0-9]*) measured_elapsed="" ;;
      esac
      if [ -n "${measured_elapsed}" ]; then
        summary_elapsed="${measured_elapsed}"
      fi
    fi
    if [ -z "${summary_elapsed}" ]; then
      summary_elapsed="0"
    fi
    log_info mdns_selfcheck outcome=ok role="${role}" host="${MDNS_HOST_RAW}" observed="${MDNS_LAST_OBSERVED}" attempts="${summary_attempts}" ms_elapsed="${summary_elapsed}" >&2
    if [ "${SUGARKUBE_DEBUG_MDNS:-0}" = "1" ]; then
      run_net_diag \
        "mdns_selfcheck_debug" \
        "${diag_args[@]}" \
        "--tag" "mode=strict" \
        "--tag" "status=0"
    fi
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      local summary_extra="attempts=${summary_attempts}"
      if [ -n "${summary_elapsed}" ]; then
        summary_extra+=" ms=${summary_elapsed}"
      fi
      summary_step "Self-check (mDNS)" "OK" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} ${summary_extra}"
      summary_recorded=1
    fi
    return 0
  else
    status=$?
  fi
  # Only perform a relaxed retry when the self-check explicitly signalled IPv4 mismatch (exit 5)
  if [ -n "${MDNS_ADDR_V4}" ] && [ "${SUGARKUBE_MDNS_ALLOW_ADDR_MISMATCH}" != "0" ] && [ "${status}" -eq 5 ]; then
    log_warn_msg mdns_selfcheck "IPv4 expectation not met; retrying without requirement" "role=${role}" "host=${MDNS_HOST_RAW}" "expected_ipv4=${MDNS_ADDR_V4}"
    local -a relaxed_env=(
      "SUGARKUBE_CLUSTER=${CLUSTER}"
      "SUGARKUBE_ENV=${ENVIRONMENT}"
      "SUGARKUBE_EXPECTED_HOST=${MDNS_HOST_RAW}"
      "SUGARKUBE_SELFCHK_ATTEMPTS=${retries}"
      "SUGARKUBE_EXPECTED_ROLE=${role}"
      "SUGARKUBE_EXPECTED_PHASE=${role}"
    )
    relaxed_attempted=1
    if [ -n "${delay_ms}" ]; then
      relaxed_env+=("SUGARKUBE_SELFCHK_BACKOFF_START_MS=${delay_ms}" "SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=${delay_ms}")
    fi
    if selfcheck_output="$(env "${relaxed_env[@]}" "${MDNS_SELF_CHECK_BIN}")"; then
      local token
      observed_host="${MDNS_HOST_RAW}"
      for token in ${selfcheck_output}; do
        case "${token}" in
          host=*)
            observed_host="${token#host=}"
            ;;
        esac
      done
      if [ -z "${observed_host}" ]; then
        observed_host="${MDNS_HOST_RAW}"
      fi
      MDNS_LAST_OBSERVED="$(canonical_host "${observed_host}")"
      log_warn_msg mdns_selfcheck "advertisement observed without expected IPv4; continuing" "role=${role}" "observed=${observed_host}" "expected_ipv4=${MDNS_ADDR_V4}" "strict_status=${status}"
      if [ "${SUGARKUBE_DEBUG_MDNS:-0}" = "1" ]; then
        run_net_diag \
          "mdns_selfcheck_debug" \
          "${diag_args[@]}" \
          "--tag" "mode=relaxed" \
          "--tag" "status=0" \
          "--tag" "strict_status=${status}"
      fi
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_step "Self-check (mDNS)" "WARN" "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note} attempts=${retries} relaxed=1"
        summary_recorded=1
      fi
      return 0
    else
      relaxed_status="$?"
    fi
  fi

  log_error_msg mdns_selfcheck "advertisement not observed for ${MDNS_HOST_RAW}; status=${status}" "role=${role}"
  if [ "${relaxed_attempted}" -eq 1 ]; then
    run_net_diag \
      "mdns_selfcheck_failure" \
      "${diag_args[@]}" \
      "--tag" "mode=strict" \
      "--tag" "strict_status=${status}" \
      "--tag" "relaxed_attempted=1" \
      "--tag" "relaxed_status=${relaxed_status}"
  else
    run_net_diag \
      "mdns_selfcheck_failure" \
      "${diag_args[@]}" \
      "--tag" "mode=strict" \
      "--tag" "strict_status=${status}" \
      "--tag" "relaxed_attempted=0"
  fi
  if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
    local failure_note="status=${status}"
    if [ "${relaxed_attempted}" -eq 1 ]; then
      failure_note+=" relaxed_status=${relaxed_status}"
    fi
    summary_step "Self-check (mDNS)" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
      "${summary_note} ${failure_note}"
    summary_recorded=1
  fi
  return "${MDNS_SELF_CHECK_FAILURE_CODE}"
}

count_servers() {
  local count
  count="$(run_avahi_query server-count | head -n1)"
  if [ -z "${count}" ]; then
    count=0
  fi
  echo "${count}"
}

wait_for_bootstrap_activity() {
  local require_activity=0
  local attempts="${DISCOVERY_ATTEMPTS}"
  local wait_secs="${DISCOVERY_WAIT_SECS}"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --require-activity)
        require_activity=1
        shift
        ;;
      --)
        shift
        break
        ;;
      *)
        break
        ;;
    esac
  done

  local attempt observed_activity=0
  local no_activity_streak=0
  local activity_grace_attempts=0
  if [ "${require_activity}" -eq 1 ]; then
    activity_grace_attempts=2
    if [ "${attempts}" -lt "${activity_grace_attempts}" ]; then
      activity_grace_attempts="${attempts}"
    fi
  fi
  local effective_attempts="${attempts}"
  if [ "${require_activity}" -eq 1 ]; then
    effective_attempts="${activity_grace_attempts}"
  fi
  log_info discover phase=wait_bootstrap attempts="${attempts}" wait_secs="${wait_secs}" require_activity="${require_activity}" >&2
  for attempt in $(seq 1 "${attempts}"); do
    local server
    server="$(discover_server_host || true)"
    if [ -n "${server}" ]; then
      log_info discover outcome=server_found host="${server}" attempt="${attempt}" total_attempts="${effective_attempts}" require_activity="${require_activity}" >&2
      printf '%s\n' "${server}"
      return 0
    fi

    local bootstrap
    bootstrap="$(discover_bootstrap_hosts || true)"
    if [ -n "${bootstrap}" ]; then
      observed_activity=1
      no_activity_streak=0
      local bootstrap_hosts
      bootstrap_hosts="${bootstrap//$'\n'/, }"
      local bootstrap_hosts_sanitized
      bootstrap_hosts_sanitized="$(printf '%s' "${bootstrap_hosts}" | sed 's/"/\\"/g')"
      log_debug discover event=bootstrap_activity attempt="${attempt}" total_attempts="${effective_attempts}" "hosts=\"${bootstrap_hosts_sanitized}\""
    else
      if [ "${require_activity}" -eq 1 ]; then
        no_activity_streak=$((no_activity_streak + 1))
        if [ "${activity_grace_attempts}" -gt 0 ] && [ "${no_activity_streak}" -ge "${activity_grace_attempts}" ]; then
          log_info discover outcome=no_bootstrap activity_required=1 attempt="${attempt}" total_attempts="${effective_attempts}" >&2
          return 1
        fi
        log_debug discover event=no_activity attempt="${attempt}" total_attempts="${effective_attempts}" streak="${no_activity_streak}" activity_required="${require_activity}"
      elif [ "${observed_activity}" -eq 0 ]; then
        log_debug discover event=no_activity attempt="${attempt}" total_attempts="${effective_attempts}" activity_required="${require_activity}"
      else
        log_debug discover event=activity_seen attempt="${attempt}" total_attempts="${effective_attempts}" activity_required="${require_activity}"
      fi
    fi

    if [ "${attempt}" -lt "${attempts}" ]; then
      local next_attempt
      next_attempt=$((attempt + 1))
      log_debug discover event=sleep attempt="${attempt}" next_attempt="${next_attempt}" wait_secs="${wait_secs}" total_attempts="${effective_attempts}"
      sleep "${wait_secs}"
    fi
  done

  if [ "${observed_activity}" -eq 1 ]; then
    log_info discover outcome=server_not_found attempts="${attempts}" observed_activity=1 >&2
  else
    log_info discover outcome=no_bootstrap attempts="${attempts}" observed_activity=0 >&2
  fi
  return 1
}

check_api_listen() {
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn '( sport = :6443 )' 2>/dev/null | grep -q LISTEN; then
      return 0
    fi
  fi

  if command -v timeout >/dev/null 2>&1; then
    if timeout 1 bash -c '</dev/tcp/127.0.0.1/6443' >/dev/null 2>&1; then
      return 0
    fi
  elif bash -c '</dev/tcp/127.0.0.1/6443' >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

wait_for_api() {
  local attempt
  for attempt in $(seq 1 60); do
    if check_api_listen; then
      return 0
    fi
    sleep 1
  done
  return 1
}

publish_avahi_service() {
  local role="$1"; shift
  local port="6443"
  if [ "$#" -gt 0 ]; then
    port="$1"
    shift
  fi

  local phase=""
  local leader=""
  local arg
  for arg in "$@"; do
    case "${arg}" in
      phase=*)
        phase="${arg#phase=}"
        ;;
      leader=*)
        leader="${arg#leader=}"
        ;;
    esac
  done

  local hostname="${MDNS_HOST_RAW:-}" 
  if [ -z "${hostname}" ]; then
    hostname="$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf '%s' "${HOSTNAME:-}")"
  fi

  local -a publish_env=(
    "SUGARKUBE_CLUSTER=${CLUSTER}"
    "SUGARKUBE_ENV=${ENVIRONMENT}"
    "ROLE=${role}"
    "PORT=${port}"
    "HOSTNAME=${hostname}"
    "PHASE=${phase}"
    "LEADER=${leader}"
  )
  if [ -n "${SUGARKUBE_AVAHI_SERVICE_DIR:-}" ]; then
    publish_env+=("SUGARKUBE_AVAHI_SERVICE_DIR=${SUGARKUBE_AVAHI_SERVICE_DIR}")
  fi
  if [ -n "${SUGARKUBE_AVAHI_SERVICE_FILE:-}" ]; then
    publish_env+=("SUGARKUBE_AVAHI_SERVICE_FILE=${SUGARKUBE_AVAHI_SERVICE_FILE}")
  fi
  if [ -n "${SUGARKUBE_SKIP_SYSTEMCTL:-}" ]; then
    publish_env+=("SUGARKUBE_SKIP_SYSTEMCTL=${SUGARKUBE_SKIP_SYSTEMCTL}")
  fi

  AVAHI_LIVENESS_READY=0
  local publish_status=0
  local publish_summary_active=0
  local publish_summary_start=0
  local publish_note="role=${role}"
  if [ -n "${phase}" ]; then
    publish_note+=" phase=${phase}"
  fi
  if [ -n "${leader}" ]; then
    publish_note+=" leader=${leader}"
  fi
  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled; then
    publish_summary_active=1
    publish_summary_start="$(summary_now_ms)"
  fi

  if ! run_privileged env "${publish_env[@]}" "${SCRIPT_DIR}/mdns_publish_static.sh"; then
    publish_status=$?
  fi

  if [ "${publish_summary_active}" -eq 1 ]; then
    local publish_status_label="OK"
    if [ "${publish_status}" -ne 0 ]; then
      publish_status_label="FAIL"
    fi
    summary_step "Publish ${MDNS_SERVICE_TYPE}" "${publish_status_label}" \
      "$(summary_elapsed_ms "${publish_summary_start}")" "${publish_note}"
  fi

  if [ "${publish_status}" -ne 0 ]; then
    return "${publish_status}"
  fi

  ensure_avahi_liveness_signal || return 1
}

publish_api_service() {
  publish_avahi_service server 6443 "leader=${MDNS_HOST_RAW}" "phase=server"

  if ensure_self_mdns_advertisement server; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=server host="${MDNS_HOST_RAW}" observed="${observed}" phase=server check=initial >&2
    return 0
  fi

  log_warn_msg mdns_selfcheck "server advertisement not visible; refreshing Avahi service" "host=${MDNS_HOST_RAW}" "role=server"
  sleep 1

  publish_avahi_service server 6443 "leader=${MDNS_HOST_RAW}" "phase=server"

  if ensure_self_mdns_advertisement server; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=server host="${MDNS_HOST_RAW}" observed="${observed}" phase=server check=reloaded >&2
    log_info_msg mdns_publish "Server advertisement observed after Avahi reload" "host=${MDNS_HOST_RAW}" "role=server"
    return 0
  fi

  log_error_msg mdns_selfcheck "failed to confirm server advertisement after Avahi reload" "host=${MDNS_HOST_RAW}" "role=server"
  if [ -f "${AVAHI_SERVICE_FILE}" ]; then
    sed -n '1,120p' "${AVAHI_SERVICE_FILE}" 2>/dev/null || true
  fi
  return "${MDNS_SELF_CHECK_FAILURE_CODE}"
}
publish_bootstrap_service() {
  log_info mdns_publish phase=bootstrap_attempt cluster="${CLUSTER}" environment="${ENVIRONMENT}" host="${MDNS_HOST_RAW}" >&2
  publish_avahi_service bootstrap 6443 "leader=${MDNS_HOST_RAW}" "phase=bootstrap"
  sleep 1
  if ensure_self_mdns_advertisement bootstrap; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=bootstrap host="${MDNS_HOST_RAW}" observed="${observed}" phase=bootstrap check=initial >&2
    return 0
  fi

  log_warn_msg mdns_selfcheck "bootstrap advertisement not visible; refreshing Avahi service" "host=${MDNS_HOST_RAW}" "role=bootstrap"
  sleep 1

  publish_avahi_service bootstrap 6443 "leader=${MDNS_HOST_RAW}" "phase=bootstrap"
  sleep 1
  if ensure_self_mdns_advertisement bootstrap; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=bootstrap host="${MDNS_HOST_RAW}" observed="${observed}" phase=bootstrap check=reloaded >&2
    log_info_msg mdns_publish "Bootstrap advertisement observed after Avahi reload" "host=${MDNS_HOST_RAW}" "role=bootstrap"
    return 0
  fi

  log_error_msg mdns_selfcheck "failed to confirm bootstrap advertisement after Avahi reload" "host=${MDNS_HOST_RAW}" "role=bootstrap"
  if [ -f "${AVAHI_SERVICE_FILE}" ]; then
    sed -n '1,120p' "${AVAHI_SERVICE_FILE}" 2>/dev/null || true
  fi
  return "${MDNS_SELF_CHECK_FAILURE_CODE}"
}
claim_bootstrap_leadership() {
  if ! publish_bootstrap_service; then
    exit 1
  fi
  sleep "${DISCOVERY_WAIT_SECS}"
  local consecutive leader candidates server
  consecutive=0
  for attempt in $(seq 1 "${DISCOVERY_ATTEMPTS}"); do
    server="$(discover_server_host || true)"
    if [ -n "${server}" ]; then
      log_info discover outcome=server_during_election host="${server}" attempt="${attempt}" total_attempts="${DISCOVERY_ATTEMPTS}" >&2
      CLAIMED_SERVER_HOST="${server}"
      cleanup_avahi_publishers
      return 2
    fi

    mapfile -t candidates < <(discover_bootstrap_leaders || true)
    if [ "${#candidates[@]}" -eq 0 ]; then
      consecutive=0
      log_debug discover event=leadership_no_candidates attempt="${attempt}" total_attempts="${DISCOVERY_ATTEMPTS}"
    else
      leader="$(printf '%s\n' "${candidates[@]}" | sort | head -n1)"
      if same_host "${leader}" "${MDNS_HOST_RAW}"; then
        consecutive=$((consecutive + 1))
        if [ "${consecutive}" -ge 3 ]; then
          log_info discover outcome=leadership_confirmed host="${MDNS_HOST_RAW}" attempts="${attempt}" consecutive="${consecutive}" >&2
          return 0
        fi
      else
        log_info discover outcome=leader_other host="${leader}" attempt="${attempt}" total_attempts="${DISCOVERY_ATTEMPTS}" >&2
        cleanup_avahi_publishers
        return 1
      fi
    fi
    sleep "${DISCOVERY_WAIT_SECS}"
  done
  log_info discover outcome=leadership_self host="${MDNS_HOST_RAW}" attempts="${DISCOVERY_ATTEMPTS}" >&2
  return 0
}

ELECTION_KEY="undefined"
ELECT_LEADER_BIN="${SUGARKUBE_ELECT_LEADER_BIN:-${SCRIPT_DIR}/elect_leader.sh}"
MDNS_SELF_CHECK_BIN="${SUGARKUBE_MDNS_SELF_CHECK_BIN:-${SCRIPT_DIR}/mdns_selfcheck.sh}"

run_leader_election() {
  local election_output
  local election_status
  local election_winner="no"
  local election_key=""

  election_output="$(SUGARKUBE_SERVERS="${SERVERS_DESIRED}" "${ELECT_LEADER_BIN}" 2>/dev/null || true)"
  election_status=$?

  if [ "${election_status}" -eq 0 ]; then
    while IFS='=' read -r field value; do
      case "${field}" in
        winner)
          election_winner="${value}"
          ;;
        key)
          election_key="${value}"
          ;;
      esac
    done <<<"${election_output}"
  else
    log_warn_msg discover "elect_leader exited non-zero" "status=${election_status}" "script=${ELECT_LEADER_BIN}"
  fi

  if [ -z "${election_key}" ]; then
    election_key="undefined"
  fi

  ELECTION_KEY="${election_key}"

  if [ "${election_winner}" = "yes" ]; then
    log_info discover event=election outcome=winner key="${ELECTION_KEY}" >&2
    return 0
  fi

  log_info discover event=election outcome=follower key="${ELECTION_KEY}" >&2
  return 1
}

ensure_iptables_tools() {
  if [ "${IPTABLES_ENSURED}" -eq 1 ]; then
    return 0
  fi
  if ! run_privileged "${SCRIPT_DIR}/k3s-install-iptables.sh"; then
    log_error_msg discover "Failed to ensure iptables tooling" "script=${SCRIPT_DIR}/k3s-install-iptables.sh"
    exit 1
  fi
  IPTABLES_ENSURED=1
}

ensure_time_sync() {
  local phase="$1"

  if [ -z "${TIME_SYNC_CHECK_BIN}" ] || [ ! -x "${TIME_SYNC_CHECK_BIN}" ]; then
    if [ "${SUGARKUBE_STRICT_TIME}" = "1" ]; then
      log_error_msg discover "Time sync check helper missing" "phase=${phase}" "script=${TIME_SYNC_CHECK_BIN}"
      return 1
    fi
    log_warn_msg discover "Time sync check skipped; helper missing" "phase=${phase}" "script=${TIME_SYNC_CHECK_BIN}"
    return 0
  fi

  local output status
  set +e
  output="$(${TIME_SYNC_CHECK_BIN} 2>&1)"
  status=$?
  set -e

  if [ -n "${output}" ]; then
    while IFS= read -r line; do
      [ -n "${line}" ] || continue
      if [ "${status}" -eq 0 ]; then
        log_info_msg discover "time sync: ${line}" "phase=${phase}"
      else
        if [ "${SUGARKUBE_STRICT_TIME}" = "1" ]; then
          log_error_msg discover "time sync: ${line}" "phase=${phase}"
        else
          log_warn_msg discover "time sync: ${line}" "phase=${phase}"
        fi
      fi
    done <<<"${output}"
  fi

  if [ "${status}" -ne 0 ]; then
    if [ "${SUGARKUBE_STRICT_TIME}" = "1" ]; then
      log_error_msg discover "Clock synchronization requirement failed" "phase=${phase}"
      return 1
    fi
    log_warn_msg discover "Clock synchronization check failed; continuing" "phase=${phase}"
  fi

  return 0
}

build_install_env() {
  local -n _target=$1
  _target=("INSTALL_K3S_CHANNEL=${K3S_CHANNEL:-stable}")
  if [ -n "${TOKEN:-}" ]; then
    _target+=("K3S_TOKEN=${TOKEN}")
  fi
}

acquire_join_gate() {
  if [ ! -x "${JOIN_GATE_BIN}" ]; then
    log_error_msg discover "join gate helper missing" "script=${JOIN_GATE_BIN}"
    return 1
  fi
  if ! "${JOIN_GATE_BIN}" wait; then
    log_error_msg discover "join gate wait failed" "script=${JOIN_GATE_BIN}"
    return 1
  fi
  if "${JOIN_GATE_BIN}" acquire; then
    JOIN_GATE_HELD=1
    return 0
  fi
  log_error_msg discover "join gate acquire failed" "script=${JOIN_GATE_BIN}"
  return 1
}

release_join_gate_if_needed() {
  if [ "${JOIN_GATE_HELD:-0}" -ne 1 ]; then
    return 0
  fi
  if [ ! -x "${JOIN_GATE_BIN}" ]; then
    log_warn_msg discover "join gate release skipped; helper missing" "script=${JOIN_GATE_BIN}"
    JOIN_GATE_HELD=0
    return 0
  fi
  if "${JOIN_GATE_BIN}" release; then
    JOIN_GATE_HELD=0
    return 0
  fi
  log_warn_msg discover "join gate release failed" "script=${JOIN_GATE_BIN}"
  return 1
}

trap 'release_join_gate_if_needed || true' EXIT

resolve_server_ip_hint() {
  local host="$1"
  local hint="${2:-}"
  if [ -n "${hint}" ]; then
    printf '%s' "${hint}"
    return 0
  fi
  case "${host}" in
    '' )
      return 0
      ;;
    *:*)
      printf '%s' "${host}"
      return 0
      ;;
    *[!0-9.]* )
      if command -v getent >/dev/null 2>&1; then
        local resolved
        resolved="$(getent hosts "${host}" | awk 'NR==1 {print $1}' | head -n1)"
        if [ -n "${resolved}" ]; then
          printf '%s' "${resolved}"
          return 0
        fi
      fi
      ;;
    * )
      printf '%s' "${host}"
      return 0
      ;;
  esac
  return 1
}

wait_for_remote_api_ready() {
  local host="$1"
  local ip_hint="${2:-}"
  local port="${3:-6443}"
  if [ -z "${host}" ]; then
    log_error_msg discover "API readiness check requires a host" "phase=api_ready"
    return 1
  fi
  if [ -z "${API_READY_CHECK_BIN}" ] || [ ! -x "${API_READY_CHECK_BIN}" ]; then
    log_error_msg discover "API readiness helper missing" "script=${API_READY_CHECK_BIN}" "phase=api_ready" "host=${host}" "port=${port}"
    return 1
  fi
  local ip=""
  if ip="$(resolve_server_ip_hint "${host}" "${ip_hint}")"; then
    if [ -z "${ip}" ]; then
      ip=""
    fi
  else
    ip=""
  fi
  local -a check_env=(
    "SERVER_HOST=${host}"
    "SERVER_PORT=${port}"
    "TIMEOUT=${API_READY_TIMEOUT}"
  )
  if [ -n "${API_READY_POLL_INTERVAL}" ]; then
    check_env+=("POLL_INTERVAL=${API_READY_POLL_INTERVAL}")
  fi
  if [ -n "${ip}" ]; then
    check_env+=("SERVER_IP=${ip}")
  fi
  if ! env "${check_env[@]}" "${API_READY_CHECK_BIN}"; then
    if [ -n "${ip}" ]; then
      log_error_msg discover "API readiness gate failed" "script=${API_READY_CHECK_BIN}" "host=${host}" "ip=${ip}" "port=${port}" "phase=api_ready"
    else
      log_error_msg discover "API readiness gate failed" "script=${API_READY_CHECK_BIN}" "host=${host}" "port=${port}" "phase=api_ready"
    fi
    return 1
  fi
  return 0
}

check_remote_server_tls_sans() {
  local server_host="$1"
  if [ -z "${server_host}" ]; then
    return 0
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    log_warn_msg discover "openssl missing; skipping SAN validation" \
      "server=${server_host}" "phase=tls_san_check"
    return 0
  fi

  local tmpdir
  tmpdir="$(mktemp -d 2>/dev/null || mktemp -d -t tls-sans)"
  local cacert_path="${tmpdir}/cacerts.pem"

  local -a curl_args=(
    --fail
    --silent
    --show-error
    --connect-timeout "${SUGARKUBE_TLS_SAN_CURL_TIMEOUT:-5}"
    --max-time "${SUGARKUBE_TLS_SAN_CURL_MAX_TIME:-15}"
    --insecure
    "https://${server_host}:6443/cacerts"
  )
  if ! curl "${curl_args[@]}" >"${cacert_path}"; then
    log_warn_msg discover "Failed to download server CA bundle" \
      "server=${server_host}" "phase=tls_san_check"
    rm -rf "${tmpdir}"
    return 0
  fi

  local san_output
  if ! san_output="$(
    openssl s_client -servername "${server_host}" -connect "${server_host}:6443" \
      -CAfile "${cacert_path}" </dev/null 2>/dev/null \
      | openssl x509 -noout -ext subjectAltName 2>/dev/null
  )"; then
    log_warn_msg discover "Failed to inspect server certificate SANs" \
      "server=${server_host}" "phase=tls_san_check"
    rm -rf "${tmpdir}"
    return 0
  fi

  rm -rf "${tmpdir}"

  if [ -z "${san_output}" ]; then
    log_warn_msg discover "Server certificate missing subjectAltName" \
      "server=${server_host}" "phase=tls_san_check"
    return 0
  fi

  local match_fragment
  if [[ "${server_host}" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
    match_fragment="IP Address:${server_host}"
  else
    match_fragment="DNS:${server_host}"
  fi

  if ! grep -q -- "${match_fragment}" <<<"${san_output}"; then
    local compact_sans
    compact_sans="$(printf '%s' "${san_output}" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')"
    log_warn_msg discover "Server certificate SANs miss join host" \
      "server=${server_host}" "hostname=${server_host}" \
      "sans=$(escape_log_value "${compact_sans}")" "phase=tls_san_check"
  fi

  return 0
}

ensure_server_flag_parity() {
  local server_host="$1"
  local phase="$2"
  if [ -z "${SERVER_FLAG_PARITY_BIN:-}" ]; then
    return 0
  fi
  if [ ! -x "${SERVER_FLAG_PARITY_BIN}" ]; then
    log_error_msg discover "Server flag parity helper missing" \
      "script=${SERVER_FLAG_PARITY_BIN}" "phase=${phase}" "server=${server_host}"
    return 1
  fi
  if ! server_flag_parity_sources_available; then
    log_warn_msg discover "Server flag parity inputs unavailable; skipping validation" \
      "phase=${phase}" "server=${server_host}"
    return 0
  fi
  local -a parity_args=()
  if [ -n "${server_host}" ]; then
    parity_args+=("--server" "${server_host}")
  fi
  if ! SUGARKUBE_SERVER_FLAG_PARITY_PHASE="${phase}" \
    "${SERVER_FLAG_PARITY_BIN}" "${parity_args[@]}"; then
    return 1
  fi
  return 0
}

server_flag_parity_sources_available() {
  if [ -n "${SUGARKUBE_SERVER_ENV_PREFIX:-}" ]; then
    return 0
  fi
  if [ -n "${SUGARKUBE_SERVER_CONFIG_CMD:-}" ]; then
    return 0
  fi
  if [ -n "${SUGARKUBE_SERVER_SERVICE_CMD:-}" ]; then
    return 0
  fi
  if [ -n "${SUGARKUBE_SERVER_CONFIG_PATH:-}" ] && [ -r "${SUGARKUBE_SERVER_CONFIG_PATH}" ]; then
    return 0
  fi
  if [ -n "${SUGARKUBE_SERVER_SERVICE_PATH:-}" ] && [ -r "${SUGARKUBE_SERVER_SERVICE_PATH}" ]; then
    return 0
  fi
  if [ -n "${SUGARKUBE_SERVER_CONFIG_DIR:-}" ] && [ -d "${SUGARKUBE_SERVER_CONFIG_DIR}" ]; then
    return 0
  fi
  if [ -r "/etc/rancher/k3s/config.yaml" ]; then
    return 0
  fi
  local service_candidate
  for service_candidate in \
    /etc/systemd/system/k3s.service \
    /usr/lib/systemd/system/k3s.service \
    /lib/systemd/system/k3s.service \
    /etc/systemd/system/multi-user.target.wants/k3s.service
  do
    if [ -r "${service_candidate}" ]; then
      return 0
    fi
  done
  return 1
}

install_server_single() {
  local summary_active=0
  local summary_start=0
  local summary_recorded=0
  local summary_status="OK"
  local summary_note="mode=single"
  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled; then
    summary_active=1
    summary_start="$(summary_now_ms)"
  fi
  ensure_iptables_tools
  log_info discover phase=install_single cluster="${CLUSTER}" environment="${ENVIRONMENT}" host="${MDNS_HOST_RAW}" datastore=sqlite >&2
  local env_assignments
  build_install_env env_assignments
  curl -sfL https://get.k3s.io \
    | env "${env_assignments[@]}" \
      sh -s - server \
      --tls-san "${MDNS_HOST}" \
      --tls-san "${HN}" \
      --kubelet-arg "node-labels=sugarkube.cluster=${CLUSTER},sugarkube.env=${ENVIRONMENT}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  if wait_for_api; then
    if ! publish_api_service; then
      log_error_msg discover "Failed to confirm Avahi server advertisement" "host=${MDNS_HOST_RAW}" "phase=install_single"
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note} reason=mdns"
        summary_recorded=1
      fi
      exit 1
    fi
  else
    log_warn_msg discover "k3s API did not become ready within 60s; skipping Avahi publish" "phase=install_single" "host=${MDNS_HOST_RAW}"
    summary_status="WARN"
    summary_note+=" reason=api-timeout"
  fi
  if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
    summary_step "k3s install" "${summary_status}" \
      "$(summary_elapsed_ms "${summary_start}")" \
      "${summary_note}"
    summary_recorded=1
  fi
}

install_server_cluster_init() {
  local summary_active=0
  local summary_start=0
  local summary_recorded=0
  local summary_status="OK"
  local summary_note="mode=cluster-init"
  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled; then
    summary_active=1
    summary_start="$(summary_now_ms)"
  fi
  ensure_iptables_tools
  log_info discover phase=install_cluster_init cluster="${CLUSTER}" environment="${ENVIRONMENT}" host="${MDNS_HOST_RAW}" datastore=etcd >&2
  local env_assignments
  build_install_env env_assignments
  curl -sfL https://get.k3s.io \
    | env "${env_assignments[@]}" \
      sh -s - server \
      --cluster-init \
      --tls-san "${MDNS_HOST}" \
      --tls-san "${HN}" \
      --kubelet-arg "node-labels=sugarkube.cluster=${CLUSTER},sugarkube.env=${ENVIRONMENT}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  if wait_for_api; then
    if ! publish_api_service; then
      log_error_msg discover "Failed to confirm Avahi server advertisement" "host=${MDNS_HOST_RAW}" "phase=install_cluster_init"
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note} reason=mdns"
        summary_recorded=1
      fi
      exit 1
    fi
  else
    log_warn_msg discover "k3s API did not become ready within 60s; skipping Avahi publish" "phase=install_cluster_init" "host=${MDNS_HOST_RAW}"
    summary_status="WARN"
    summary_note+=" reason=api-timeout"
  fi
  if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
    summary_step "k3s install" "${summary_status}" \
      "$(summary_elapsed_ms "${summary_start}")" \
      "${summary_note}"
    summary_recorded=1
  fi
}

install_server_join() {
  local discovered_server="$1"
  local server
  server="$(join_target_host "${discovered_server}")"
  local probe_host="${server}"
  local summary_active=0
  local summary_start=0
  local summary_recorded=0
  local summary_status="OK"
  local summary_note="mode=join"
  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled; then
    summary_active=1
    summary_start="$(summary_now_ms)"
  fi
  if [ -n "${API_REGADDR:-}" ] && [ -n "${discovered_server:-}" ]; then
    probe_host="${discovered_server}"
  fi
  if [ -z "${TOKEN:-}" ]; then
    log_error_msg discover "Join token missing; cannot join existing HA server" "phase=install_join" "host=${MDNS_HOST_RAW}"
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=token"
      summary_recorded=1
    fi
    exit 1
  fi
  local required_ports="6443,2379,2380"
  if [ ! -x "${L4_PROBE_BIN}" ]; then
    log_error_msg discover "Port connectivity helper missing" "phase=install_join" "server=${server}" "script=${L4_PROBE_BIN}"
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=l4-probe"
      summary_recorded=1
    fi
    exit 1
  fi
  local probe_output=""
  local probe_status=0
  set +e
  probe_output="$(${L4_PROBE_BIN} "${probe_host}" "${required_ports}")"
  probe_status=$?
  set -e
  if [ -n "${probe_output}" ]; then
    while IFS= read -r line; do
      [ -n "${line}" ] || continue
      local escaped_line
      escaped_line="$(escape_log_value "${line}")"
      if [ "${probe_host}" != "${server}" ]; then
        log_info discover event=l4_probe phase=install_join \
          "server=\"${server}\"" "probe_host=\"${probe_host}\"" \
          "result=\"${escaped_line}\"" >&2
      else
        log_info discover event=l4_probe phase=install_join \
          "server=\"${server}\"" "result=\"${escaped_line}\"" >&2
      fi
    done <<<"${probe_output}"
  fi
  if [ "${probe_status}" -ne 0 ]; then
    if [ -n "${probe_output}" ]; then
      printf '%s\n' "${probe_output}" >&2
    fi
    log_error_msg discover "Required TCP ports are not reachable" \
      "phase=install_join" "server=${server}" "probe_host=${probe_host}" \
      "ports=${required_ports}"
    log_error_msg discover "Ensure TCP 6443, 2379, and 2380 are open between control-plane nodes before retrying" \
      "phase=install_join" "server=${server}"
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=ports"
      summary_recorded=1
    fi
    exit 1
  fi
  if ! wait_for_remote_api_ready "${server}"; then
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=remote-api"
      summary_recorded=1
    fi
    exit 1
  fi
  if ! ensure_server_flag_parity "${server}" "install_join"; then
    log_error_msg discover "Server flag parity validation failed" \
      "phase=install_join" "host=${MDNS_HOST_RAW}" "server=${server}"
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=flag-parity"
      summary_recorded=1
    fi
    exit 1
  fi
  if ! ensure_time_sync "install_join"; then
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=time-sync"
      summary_recorded=1
    fi
    exit 1
  fi
  check_remote_server_tls_sans "${server}"
  if ! acquire_join_gate; then
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=join-gate"
      summary_recorded=1
    fi
    exit 1
  fi
  ensure_iptables_tools
  local -a log_args=(
    "phase=install_join"
    "host=${MDNS_HOST_RAW}"
    "server=${server}"
    "desired_servers=${SERVERS_DESIRED}"
  )
  if [ -n "${API_REGADDR:-}" ] && [ -n "${discovered_server:-}" ] && [ "${server}" != "${discovered_server}" ]; then
    log_args+=("discovered_server=${discovered_server}")
  fi
  log_info discover "${log_args[@]}" >&2
  local env_assignments
  build_install_env env_assignments
  curl -sfL https://get.k3s.io \
    | env "${env_assignments[@]}" \
      sh -s - server \
      --server "https://${server}:6443" \
      --tls-san "${server}" \
      --tls-san "${MDNS_HOST}" \
      --tls-san "${HN}" \
      --kubelet-arg "node-labels=sugarkube.cluster=${CLUSTER},sugarkube.env=${ENVIRONMENT}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  if wait_for_api; then
    if ! publish_api_service; then
      log_error_msg discover "Failed to confirm Avahi server advertisement" "host=${MDNS_HOST_RAW}" "phase=install_join"
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note} reason=mdns"
        summary_recorded=1
      fi
      exit 1
    fi
    if ! release_join_gate_if_needed; then
      log_error_msg discover "Failed to release join gate" "phase=install_join"
      if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
        summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
          "${summary_note} reason=join-gate-release"
        summary_recorded=1
      fi
      exit 1
    fi
  else
    log_warn_msg discover "k3s API did not become ready within 60s; skipping Avahi publish" "phase=install_join" "host=${MDNS_HOST_RAW}"
    summary_status="WARN"
    summary_note+=" reason=api-timeout"
  fi
  if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
    summary_step "k3s install" "${summary_status}" \
      "$(summary_elapsed_ms "${summary_start}")" \
      "${summary_note}"
    summary_recorded=1
  fi
}

install_agent() {
  local discovered_server="$1"
  local server
  server="$(join_target_host "${discovered_server}")"
  local summary_active=0
  local summary_start=0
  local summary_recorded=0
  local summary_note="mode=agent"
  if command -v summary_enabled >/dev/null 2>&1 && summary_enabled; then
    summary_active=1
    summary_start="$(summary_now_ms)"
  fi
  if [ -z "${TOKEN:-}" ]; then
    log_error_msg discover "Join token missing; cannot join agent to existing server" "phase=install_agent" "host=${MDNS_HOST_RAW}"
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=token"
      summary_recorded=1
    fi
    exit 1
  fi
  if ! wait_for_remote_api_ready "${server}"; then
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=remote-api"
      summary_recorded=1
    fi
    exit 1
  fi
  if ! ensure_server_flag_parity "${server}" "install_agent"; then
    log_error_msg discover "Server flag parity validation failed" \
      "phase=install_agent" "host=${MDNS_HOST_RAW}" "server=${server}"
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=flag-parity"
      summary_recorded=1
    fi
    exit 1
  fi
  if ! ensure_time_sync "install_agent"; then
    if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
      summary_step "k3s install" "FAIL" "$(summary_elapsed_ms "${summary_start}")" \
        "${summary_note} reason=time-sync"
      summary_recorded=1
    fi
    exit 1
  fi
  ensure_iptables_tools
  local -a agent_log_args=(
    "phase=install_agent"
    "host=${MDNS_HOST_RAW}"
    "server=${server}"
  )
  if [ -n "${API_REGADDR:-}" ] && [ -n "${discovered_server:-}" ] && [ "${server}" != "${discovered_server}" ]; then
    agent_log_args+=("discovered_server=${discovered_server}")
  fi
  log_info discover "${agent_log_args[@]}" >&2
  local env_assignments
  build_install_env env_assignments
  env_assignments+=("K3S_URL=https://${server}:6443")
  curl -sfL https://get.k3s.io \
    | env "${env_assignments[@]}" \
      sh -s - agent \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}"
  if [ "${summary_active}" -eq 1 ] && [ "${summary_recorded}" -eq 0 ]; then
    summary_step "k3s install" "OK" \
      "$(summary_elapsed_ms "${summary_start}")" \
      "${summary_note}"
    summary_recorded=1
  fi
}

if [ -n "${TEST_RUN_AVAHI:-}" ]; then
  run_avahi_query "${TEST_RUN_AVAHI}"
  exit 0
fi

if [ "${PRINT_SERVER_HOSTS}" -eq 1 ]; then
  discover_server_hosts
  exit 0
fi

if [ "${TEST_RENDER_SERVICE}" -eq 1 ]; then
  if [ "${#TEST_RENDER_ARGS[@]}" -eq 0 ]; then
    echo "--render-avahi-service requires a role argument" >&2
    exit 2
  fi
  if [ "${TEST_RENDER_ARGS[0]}" = "api" ]; then
    render_avahi_service_xml server 6443 "leader=%h.local" "phase=server"
  else
    render_avahi_service_xml "${TEST_RENDER_ARGS[@]}"
  fi
  exit 0
fi

if [ "${TEST_WAIT_LOOP:-0}" -eq 1 ]; then
  # fast path for tests
  wait_for_bootstrap_activity --require-activity
  exit 0
fi

if [ "${TEST_PUBLISH_BOOTSTRAP:-0}" -eq 1 ]; then
  if publish_bootstrap_service; then
    exit 0
  fi
  exit 1
fi

if [ "${TEST_BOOTSTRAP_SERVER_FLOW:-0}" -eq 1 ]; then
  if publish_bootstrap_service && publish_api_service; then
    exit 0
  fi
  exit 1
fi

if [ "${TEST_CLAIM_BOOTSTRAP:-0}" -eq 1 ]; then
  CLAIMED_SERVER_HOST=""
  if claim_bootstrap_leadership; then
    printf 'bootstrap\n'
    exit 0
  fi
  status=$?
  if [ "${status}" -eq 2 ] && [ -n "${CLAIMED_SERVER_HOST:-}" ]; then
    printf '%s\n' "${CLAIMED_SERVER_HOST}"
  fi
  exit "${status}"
fi

ensure_mdns_absence_gate

log_info discover phase=discover_existing cluster="${CLUSTER}" environment="${ENVIRONMENT}" >&2
server_host=""
bootstrap_selected="false"

while :; do
  if [ -z "${server_host}" ] && [ "${bootstrap_selected}" != "true" ]; then
    while [ -z "${server_host}" ] && [ "${bootstrap_selected}" != "true" ]; do
      server_host="$(discover_server_host || true)"
      if [ -n "${server_host}" ]; then
        FOLLOWER_UNTIL_SERVER=0
        FOLLOWER_UNTIL_SERVER_SET_AT=0
        break
      fi

      if [ "${FOLLOWER_UNTIL_SERVER}" -eq 1 ]; then
        if [ "${FOLLOWER_UNTIL_SERVER_SET_AT}" -eq 0 ]; then
          FOLLOWER_UNTIL_SERVER_SET_AT="$(date +%s)"
        fi
        now="$(date +%s)"
        if [ $((now - FOLLOWER_UNTIL_SERVER_SET_AT)) -ge "${FOLLOWER_REELECT_SECS}" ]; then
          log_info discover event=follower_election_retry wait_secs="${FOLLOWER_REELECT_SECS}" >&2
          FOLLOWER_UNTIL_SERVER=0
          FOLLOWER_UNTIL_SERVER_SET_AT=0
        else
          sleep "${DISCOVERY_WAIT_SECS}"
          continue
        fi
      fi

      if run_leader_election; then
        sleep "${ELECTION_HOLDOFF}"
        server_host="$(discover_server_host || true)"
        if [ -n "${server_host}" ]; then
          log_info discover outcome=post_election_server host="${server_host}" holdoff="${ELECTION_HOLDOFF}" >&2
          FOLLOWER_UNTIL_SERVER=0
          FOLLOWER_UNTIL_SERVER_SET_AT=0
          break
        fi
        bootstrap_selected="true"
        FOLLOWER_UNTIL_SERVER=0
        FOLLOWER_UNTIL_SERVER_SET_AT=0
        break
      fi

      FOLLOWER_UNTIL_SERVER=1
      FOLLOWER_UNTIL_SERVER_SET_AT="$(date +%s)"
      sleep "${DISCOVERY_WAIT_SECS}"
    done
  fi

  if [ "${bootstrap_selected}" = "true" ]; then
    if publish_bootstrap_service; then
      if [ "${SERVERS_DESIRED}" = "1" ]; then
        install_server_single
      else
        install_server_cluster_init
      fi
      break
    fi

    log_warn_msg discover "mDNS self-check failed after bootstrap advertisement" "host=${MDNS_HOST_RAW}" "role=bootstrap"
    cleanup_avahi_publishers || true
    run_net_diag "bootstrap_selfcheck_failure" \
      --iface "${MDNS_IFACE}" \
      --tag "cluster=${CLUSTER}" \
      --tag "environment=${ENVIRONMENT}" \
      --tag "host=${MDNS_HOST_RAW}" \
      --tag "role=bootstrap" \
      --tag "status=failure"

    if run_leader_election; then
      log_info discover event=bootstrap_selfcheck_election outcome=winner key="${ELECTION_KEY}" >&2
      FOLLOWER_UNTIL_SERVER=0
      FOLLOWER_UNTIL_SERVER_SET_AT=0
      sleep "${ELECTION_HOLDOFF}"
      if [ "${SERVERS_DESIRED}" = "1" ]; then
        install_server_single
      else
        install_server_cluster_init
      fi
      break
    fi

    log_info discover event=bootstrap_selfcheck_election outcome=follower key="${ELECTION_KEY}" >&2
    FOLLOWER_UNTIL_SERVER=1
    FOLLOWER_UNTIL_SERVER_SET_AT="$(date +%s)"
    bootstrap_selected="false"
    server_host=""
    sleep "${DISCOVERY_WAIT_SECS}"
    continue
  fi

  servers_now="$(count_servers)"
  if [ "${servers_now}" -lt "${SERVERS_DESIRED}" ]; then
    if [ -z "${server_host:-}" ]; then
      server_host="$(discover_server_host || true)"
    fi
    if [ -z "${server_host:-}" ]; then
      log_info discover outcome=fallback_bootstrap reason=no_servers attempts="${DISCOVERY_ATTEMPTS}" >&2
      if [ "${SERVERS_DESIRED}" = "1" ]; then
        install_server_single
      else
        install_server_cluster_init
      fi
    else
      install_server_join "${server_host}"
    fi
  else
    if [ -z "${server_host:-}" ]; then
      server_host="$(discover_server_host || true)"
    fi
    if [ -z "${server_host:-}" ]; then
      log_error_msg discover "Unable to discover an API server to join as agent" "cluster=${CLUSTER}" "environment=${ENVIRONMENT}"
      exit 1
    fi
    install_agent "${server_host}"
  fi
  break
done

if [ -f /etc/rancher/k3s/k3s.yaml ]; then
  run_privileged mkdir -p /root/.kube
  run_privileged cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
fi
