#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

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
NODE_TOKEN_PATH="${SUGARKUBE_NODE_TOKEN_PATH:-/var/lib/rancher/k3s/server/node-token}"
BOOT_TOKEN_PATH="${SUGARKUBE_BOOT_TOKEN_PATH:-/boot/sugarkube-node-token}"
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
MDNS_SELF_CHECK_FAILURE_CODE=94
ELECTION_HOLDOFF="${ELECTION_HOLDOFF:-10}"
FOLLOWER_UNTIL_SERVER=0
FOLLOWER_UNTIL_SERVER_SET_AT=0
FOLLOWER_REELECT_SECS="${FOLLOWER_REELECT_SECS:-60}"

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

NODE_TOKEN_PRESENT=0
BOOT_TOKEN_PRESENT=0

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

resolve_local_token() {
  if [ -n "${TOKEN:-}" ]; then
    return 0
  fi

  local candidate=""
  local line=""

  if [ -s "${NODE_TOKEN_PATH}" ]; then
    NODE_TOKEN_PRESENT=1
    candidate="$(tr -d '\n' <"${NODE_TOKEN_PATH}")"
    if [ -n "${candidate}" ]; then
      TOKEN="${candidate}"
      RESOLVED_TOKEN_SOURCE="${NODE_TOKEN_PATH}"
      return 0
    fi
  fi

  if [ -s "${BOOT_TOKEN_PATH}" ]; then
    line="$(grep -m1 '^NODE_TOKEN=' "${BOOT_TOKEN_PATH}" 2>/dev/null || true)"
    if [ -n "${line}" ]; then
      BOOT_TOKEN_PRESENT=1
      candidate="${line#NODE_TOKEN=}"
      candidate="${candidate%$'\r'}"
      candidate="${candidate%$'\n'}"
      if [ -n "${candidate}" ]; then
        TOKEN="${candidate}"
        RESOLVED_TOKEN_SOURCE="${BOOT_TOKEN_PATH}"
        return 0
      fi
    fi
  fi

  return 1
}

resolve_local_token || true

ALLOW_BOOTSTRAP_WITHOUT_TOKEN=0
if [ -z "${TOKEN:-}" ]; then
  if [ "${SERVERS_DESIRED}" = "1" ]; then
    ALLOW_BOOTSTRAP_WITHOUT_TOKEN=1
  elif [ "${NODE_TOKEN_PRESENT}" -eq 0 ] && [ "${BOOT_TOKEN_PRESENT}" -eq 0 ]; then
    # No join token was provided and nothing has been written locally yet.
    # Allow the first HA control-plane node to bootstrap without a token so
    # it can generate one for subsequent peers.
    ALLOW_BOOTSTRAP_WITHOUT_TOKEN=1
  fi
fi

if [ -z "${TOKEN:-}" ] && [ "${ALLOW_BOOTSTRAP_WITHOUT_TOKEN}" -ne 1 ]; then
  if [ "${CHECK_TOKEN_ONLY}" -eq 1 ]; then
    echo "SUGARKUBE_TOKEN (or per-env variant) required" >&2
    exit 1
  fi
  echo "SUGARKUBE_TOKEN (or per-env variant) required"
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
MDNS_SERVICE_DOMAIN="${SUGARKUBE_MDNS_DOMAIN:-local}"
MDNS_ABSENCE_REQUIRED_CONSEC="${SUGARKUBE_MDNS_ABSENCE_REQUIRED_CONSEC:-2}"
MDNS_ABSENCE_MAX_ATTEMPTS="${SUGARKUBE_MDNS_ABSENCE_ATTEMPTS:-10}"
MDNS_ABSENCE_TIMEOUT_MS="${SUGARKUBE_MDNS_ABSENCE_TIMEOUT_MS:-20000}"
MDNS_ABSENCE_BACKOFF_START_MS="${SUGARKUBE_MDNS_ABSENCE_BACKOFF_START_MS:-250}"
MDNS_ABSENCE_BACKOFF_CAP_MS="${SUGARKUBE_MDNS_ABSENCE_BACKOFF_CAP_MS:-2000}"
MDNS_ABSENCE_JITTER="${SUGARKUBE_MDNS_ABSENCE_JITTER:-0.25}"
case "${MDNS_ABSENCE_REQUIRED_CONSEC}" in
  ''|*[!0-9]*) MDNS_ABSENCE_REQUIRED_CONSEC=2 ;;
  0) MDNS_ABSENCE_REQUIRED_CONSEC=1 ;;
esac
case "${MDNS_ABSENCE_MAX_ATTEMPTS}" in
  ''|*[!0-9]*) MDNS_ABSENCE_MAX_ATTEMPTS=10 ;;
  0) MDNS_ABSENCE_MAX_ATTEMPTS=1 ;;
esac
case "${MDNS_ABSENCE_TIMEOUT_MS}" in
  ''|*[!0-9]*) MDNS_ABSENCE_TIMEOUT_MS=20000 ;;
esac
case "${MDNS_ABSENCE_BACKOFF_START_MS}" in
  ''|*[!0-9]*) MDNS_ABSENCE_BACKOFF_START_MS=250 ;;
esac
case "${MDNS_ABSENCE_BACKOFF_CAP_MS}" in
  ''|*[!0-9]*) MDNS_ABSENCE_BACKOFF_CAP_MS=2000 ;;
esac
AVAHI_SERVICE_DIR="${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}"
AVAHI_SERVICE_FILE="${SUGARKUBE_AVAHI_SERVICE_FILE:-${AVAHI_SERVICE_DIR}/k3s-${CLUSTER}-${ENVIRONMENT}.service}"
AVAHI_ROLE=""
BOOTSTRAP_PUBLISH_PID=""
BOOTSTRAP_PUBLISH_LOG=""
SERVER_PUBLISH_PID=""
SERVER_PUBLISH_LOG=""
ADDRESS_PUBLISH_PID=""
ADDRESS_PUBLISH_LOG=""
MDNS_RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
BOOTSTRAP_PID_FILE="${MDNS_RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-bootstrap.pid"
SERVER_PID_FILE="${MDNS_RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-server.pid"
SERVER_PUBLISH_PERSIST=0
MDNS_LAST_OBSERVED=""
CLAIMED_SERVER_HOST=""
IPTABLES_ENSURED=0

run_privileged() {
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" "$@"
  else
    "$@"
  fi
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

if ! run_privileged mkdir -p "${MDNS_RUNTIME_DIR}"; then
  echo "Failed to create ${MDNS_RUNTIME_DIR}" >&2
  exit 1
fi

for phase in bootstrap server; do
  pid_file="${MDNS_RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-${phase}.pid"
  if [ -f "${pid_file}" ]; then
    pid_contents="$(cat "${pid_file}" 2>/dev/null || true)"
    if [ -n "${pid_contents}" ] && kill -0 "${pid_contents}" >/dev/null 2>&1; then
      if [ "${phase}" = "bootstrap" ]; then
        BOOTSTRAP_PUBLISH_PID="${pid_contents}"
      else
        SERVER_PUBLISH_PID="${pid_contents}"
        SERVER_PUBLISH_PERSIST=1
      fi
    else
      remove_privileged_file "${pid_file}" || true
    fi
  fi
done

reload_avahi_daemon() {
  if [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" systemctl reload avahi-daemon || "${SUDO_CMD}" systemctl restart avahi-daemon
  else
    systemctl reload avahi-daemon || systemctl restart avahi-daemon
  fi
}

restart_avahi_daemon_service() {
  if [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if [ -n "${SUDO_CMD:-}" ]; then
    if ! "${SUDO_CMD}" systemctl restart avahi-daemon >/dev/null 2>&1; then
      return 1
    fi
  else
    if ! systemctl restart avahi-daemon >/dev/null 2>&1; then
      return 1
    fi
  fi
  return 0
}

stop_bootstrap_publisher() {
  if [ -n "${BOOTSTRAP_PUBLISH_PID:-}" ]; then
    if kill -0 "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1; then
      kill "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1 || true
    fi
    wait "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1 || true
    BOOTSTRAP_PUBLISH_PID=""
    BOOTSTRAP_PUBLISH_LOG=""
    remove_privileged_file "${BOOTSTRAP_PID_FILE}" || true
  fi
}

stop_server_publisher() {
  if [ -n "${SERVER_PUBLISH_PID:-}" ]; then
    if kill -0 "${SERVER_PUBLISH_PID}" >/dev/null 2>&1; then
      kill "${SERVER_PUBLISH_PID}" >/dev/null 2>&1 || true
    fi
    wait "${SERVER_PUBLISH_PID}" >/dev/null 2>&1 || true
    SERVER_PUBLISH_PID=""
    SERVER_PUBLISH_LOG=""
    remove_privileged_file "${SERVER_PID_FILE}" || true
  fi
}

stop_address_publisher() {
  if [ -n "${ADDRESS_PUBLISH_PID:-}" ]; then
    if kill -0 "${ADDRESS_PUBLISH_PID}" >/dev/null 2>&1; then
      kill "${ADDRESS_PUBLISH_PID}" >/dev/null 2>&1 || true
    fi
    wait "${ADDRESS_PUBLISH_PID}" >/dev/null 2>&1 || true
    ADDRESS_PUBLISH_PID=""
    ADDRESS_PUBLISH_LOG=""
  fi
}

cleanup_avahi_publishers() {
  if [ "${SERVER_PUBLISH_PERSIST}" != "1" ]; then
    stop_server_publisher
  fi
  stop_address_publisher
  stop_bootstrap_publisher
  if [ "${AVAHI_ROLE}" = "bootstrap" ]; then
    remove_privileged_file "${AVAHI_SERVICE_FILE}" || true
    reload_avahi_daemon || true
    AVAHI_ROLE=""
  fi
}

trap cleanup_avahi_publishers EXIT

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

mdns_absence_host_variants() {
  local -A _seen=()
  local candidate=""
  for candidate in "${MDNS_HOST_RAW}" "${MDNS_HOST}"; do
    if [ -n "${candidate}" ] && [ -z "${_seen[${candidate}]:-}" ]; then
      printf '%s\n' "${candidate}"
      _seen["${candidate}"]=1
    fi
  done

  local base
  base="$(strip_local_suffix "${MDNS_HOST_RAW}")"
  if [ -n "${base}" ] && [ -z "${_seen[${base}]:-}" ]; then
    printf '%s\n' "${base}"
    _seen["${base}"]=1
  fi

  if [ -n "${base}" ]; then
    local with_suffix="${base}.local"
    if [ -z "${_seen[${with_suffix}]:-}" ]; then
      printf '%s\n' "${with_suffix}"
      _seen["${with_suffix}"]=1
    fi
  fi
}

start_address_publisher() {
  if [ -z "${MDNS_ADDR_V4:-}" ]; then
    return 0
  fi
  if ! command -v avahi-publish-address >/dev/null 2>&1; then
    log_warn_msg mdns_publish "avahi-publish-address not available; skipping direct address publish" "publisher=address"
    return 1
  fi
  if [ -n "${ADDRESS_PUBLISH_PID:-}" ] && kill -0 "${ADDRESS_PUBLISH_PID}" >/dev/null 2>&1; then
    return 0
  fi

  ADDRESS_PUBLISH_LOG="/tmp/sugar-publish-address.log"
  : >"${ADDRESS_PUBLISH_LOG}" 2>/dev/null || true

  local -a publish_cmd=(
    avahi-publish-address
    "${MDNS_HOST_RAW}"
    "${MDNS_ADDR_V4}"
  )

  log_debug mdns_publish action=publish_address host="${MDNS_HOST_RAW}" ipv4="${MDNS_ADDR_V4}"
  "${publish_cmd[@]}" >"${ADDRESS_PUBLISH_LOG}" 2>&1 &
  ADDRESS_PUBLISH_PID=$!

  sleep 1
  if ! kill -0 "${ADDRESS_PUBLISH_PID}" >/dev/null 2>&1; then
    if [ -s "${ADDRESS_PUBLISH_LOG}" ]; then
      while IFS= read -r line; do
        log_error_msg mdns_publish "address publisher error: ${line}"
      done <"${ADDRESS_PUBLISH_LOG}"
    fi
    ADDRESS_PUBLISH_PID=""
    ADDRESS_PUBLISH_LOG=""
    return 1
  fi

  return 0
}

start_bootstrap_publisher() {
  start_address_publisher || true
  if ! command -v avahi-publish >/dev/null 2>&1; then
    log_warn_msg mdns_publish "avahi-publish not available; relying on Avahi service file" "publisher=bootstrap"
    return 1
  fi
  if [ -n "${BOOTSTRAP_PUBLISH_PID:-}" ] && kill -0 "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1; then
    return 0
  fi

  local publish_name
  publish_name="$(service_instance_name bootstrap "${MDNS_HOST_RAW}")"

  BOOTSTRAP_PUBLISH_LOG="/tmp/sugar-publish-bootstrap.log"
  : >"${BOOTSTRAP_PUBLISH_LOG}" 2>/dev/null || true

  local -a publish_txt_args=(
    "k3s=1"
    "cluster=${CLUSTER}"
    "env=${ENVIRONMENT}"
    "role=bootstrap"
    "phase=bootstrap"
    "state=pending"
  )
  if [ -n "${MDNS_HOST_RAW}" ]; then
    publish_txt_args+=("leader=${MDNS_HOST_RAW}")
  fi

  local host_arg="${MDNS_HOST_RAW:-}"
  local -a publish_cmd
  mapfile -t publish_cmd < <(
    python3 - "${publish_name}" "${MDNS_SERVICE_TYPE}" "6443" "${host_arg}" "${publish_txt_args[@]}" <<'PY'
import sys
from mdns_helpers import build_publish_cmd

instance = sys.argv[1]
service_type = sys.argv[2]
port = int(sys.argv[3])
host_value = sys.argv[4] or None
txt = {}
for item in sys.argv[5:]:
    if not item:
        continue
    if "=" in item:
        key, value = item.split("=", 1)
    else:
        key, value = item, ""
    txt[key] = value

cmd = build_publish_cmd(
    instance=instance,
    service_type=service_type,
    port=port,
    host=host_value or None,
    txt=txt,
)
for element in cmd:
    print(element)
PY
  )

  local publish_cmd_json
  publish_cmd_json="$(python3 - "${publish_cmd[@]}" <<'PY'
import json
import sys

print(json.dumps(sys.argv[1:]))
PY
  )"
  local publish_cmd_json_escaped
  publish_cmd_json_escaped="$(printf '%s' "${publish_cmd_json}" | sed 's/"/\\"/g')"
  log_trace mdns_publish role=bootstrap action=argv "cmd=\"${publish_cmd_json_escaped}\""

  log_debug mdns_publish action=start_publish role=bootstrap host="${MDNS_HOST_RAW}" ipv4="${MDNS_ADDR_V4:-auto}" type="${MDNS_SERVICE_TYPE}"
  "${publish_cmd[@]}" >"${BOOTSTRAP_PUBLISH_LOG}" 2>&1 &
  BOOTSTRAP_PUBLISH_PID=$!

  sleep 1
  if ! kill -0 "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1; then
    if [ -s "${BOOTSTRAP_PUBLISH_LOG}" ]; then
      while IFS= read -r line; do
        log_error_msg mdns_publish "bootstrap publisher error: ${line}"
      done <"${BOOTSTRAP_PUBLISH_LOG}"
    fi
    BOOTSTRAP_PUBLISH_PID=""
    BOOTSTRAP_PUBLISH_LOG=""
    return 1
  fi

  log_info mdns_publish outcome=started role=bootstrap host="${MDNS_HOST_RAW}" ipv4="${MDNS_ADDR_V4:-auto}" type="${MDNS_SERVICE_TYPE}" pid="${BOOTSTRAP_PUBLISH_PID}" >&2
  printf '%s\n' "${BOOTSTRAP_PUBLISH_PID}" | write_privileged_file "${BOOTSTRAP_PID_FILE}"
  return 0
}

start_server_publisher() {
  start_address_publisher || true
  if ! command -v avahi-publish >/dev/null 2>&1; then
    log_warn_msg mdns_publish "avahi-publish not available; relying on Avahi service file" "publisher=server"
    return 1
  fi
  if [ -n "${SERVER_PUBLISH_PID:-}" ] && kill -0 "${SERVER_PUBLISH_PID}" >/dev/null 2>&1; then
    return 0
  fi

  local publish_name
  publish_name="$(service_instance_name server "${MDNS_HOST_RAW}")"

  SERVER_PUBLISH_LOG="/tmp/sugar-publish-server.log"
  : >"${SERVER_PUBLISH_LOG}" 2>/dev/null || true

  local -a publish_txt_args=(
    "k3s=1"
    "cluster=${CLUSTER}"
    "env=${ENVIRONMENT}"
    "role=server"
    "phase=server"
  )
  if [ -n "${MDNS_HOST_RAW}" ]; then
    publish_txt_args+=("leader=${MDNS_HOST_RAW}")
  fi

  local host_arg="${MDNS_HOST_RAW:-}"
  local -a publish_cmd
  mapfile -t publish_cmd < <(
    python3 - "${publish_name}" "${MDNS_SERVICE_TYPE}" "6443" "${host_arg}" "${publish_txt_args[@]}" <<'PY'
import sys
from mdns_helpers import build_publish_cmd

instance = sys.argv[1]
service_type = sys.argv[2]
port = int(sys.argv[3])
host_value = sys.argv[4] or None
txt = {}
for item in sys.argv[5:]:
    if not item:
        continue
    if "=" in item:
        key, value = item.split("=", 1)
    else:
        key, value = item, ""
    txt[key] = value

cmd = build_publish_cmd(
    instance=instance,
    service_type=service_type,
    port=port,
    host=host_value or None,
    txt=txt,
)
for element in cmd:
    print(element)
PY
  )

  local publish_cmd_json
  publish_cmd_json="$(python3 - "${publish_cmd[@]}" <<'PY'
import json
import sys

print(json.dumps(sys.argv[1:]))
PY
  )"
  local publish_cmd_json_escaped
  publish_cmd_json_escaped="$(printf '%s' "${publish_cmd_json}" | sed 's/"/\\"/g')"
  log_trace mdns_publish role=server action=argv "cmd=\"${publish_cmd_json_escaped}\""

  log_debug mdns_publish action=start_publish role=server host="${MDNS_HOST_RAW}" ipv4="${MDNS_ADDR_V4:-auto}" type="${MDNS_SERVICE_TYPE}"
  "${publish_cmd[@]}" >"${SERVER_PUBLISH_LOG}" 2>&1 &
  SERVER_PUBLISH_PID=$!

  sleep 1
  if ! kill -0 "${SERVER_PUBLISH_PID}" >/dev/null 2>&1; then
    if [ -s "${SERVER_PUBLISH_LOG}" ]; then
      while IFS= read -r line; do
        log_error_msg mdns_publish "server publisher error: ${line}"
      done <"${SERVER_PUBLISH_LOG}"
    fi
    SERVER_PUBLISH_PID=""
    SERVER_PUBLISH_LOG=""
    return 1
  fi

  log_info mdns_publish outcome=started role=server host="${MDNS_HOST_RAW}" ipv4="${MDNS_ADDR_V4:-auto}" type="${MDNS_SERVICE_TYPE}" pid="${SERVER_PUBLISH_PID}" >&2
  printf '%s\n' "${SERVER_PUBLISH_PID}" | write_privileged_file "${SERVER_PID_FILE}"
  return 0
}

xml_escape() {
  python3 - "$1" <<'PY'
import html
import sys

print(html.escape(sys.argv[1], quote=True))
PY
}

service_instance_name() {
  local role="$1"
  local host="${2:-%h}"
  local suffix=""
  if [ -n "${role}" ]; then
    suffix=" (${role})"
  fi
  printf 'k3s-%s-%s@%s%s' "${CLUSTER}" "${ENVIRONMENT}" "${host}" "${suffix}"
}

render_avahi_service_xml() {
  local role="$1"; shift
  local port="${1:-6443}"; shift
  local service_name
  service_name="$(service_instance_name "${role}" "%h")"

  # Escape user-provided bits to keep valid XML
  local xml_service_name xml_port xml_cluster xml_env xml_role xml_type
  xml_service_name="$(xml_escape "${service_name}")"
  xml_port="$(xml_escape "${port}")"
  xml_cluster="$(xml_escape "${CLUSTER}")"
  xml_env="$(xml_escape "${ENVIRONMENT}")"
  xml_role="$(xml_escape "${role}")"
  xml_type="$(xml_escape "${MDNS_SERVICE_TYPE}")"

  # Optional TXT extras
  local extra=""
  local item
  for item in "$@"; do
    [ -n "${item}" ] || continue
    extra+=$'\n    <txt-record>'"$(xml_escape "${item}")"'</txt-record>'
  done

  cat <<EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">${xml_service_name}</name>
  <service>
    <type>${xml_type}</type>
    <port>${xml_port}</port>
    <txt-record>k3s=1</txt-record>
    <txt-record>cluster=${xml_cluster}</txt-record>
    <txt-record>env=${xml_env}</txt-record>
    <txt-record>role=${xml_role}</txt-record>${extra}
  </service>
</service-group>
EOF
}

monotonic_ms() {
  python3 - <<'PY'
import time

print(int(time.monotonic() * 1000))
PY
}

elapsed_ms_since() {
  python3 - "$1" <<'PY'
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
}

compute_absence_delay_ms() {
  local attempt="$1"
  python3 - "${attempt}" "${MDNS_ABSENCE_BACKOFF_START_MS}" "${MDNS_ABSENCE_BACKOFF_CAP_MS}" "${MDNS_ABSENCE_JITTER}" <<'PY'
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

if start:
    delay = start * (2 ** (attempt - 1))
else:
    delay = 0
if cap and delay > cap:
    delay = cap

if delay > 0 and jitter > 0:
    low = max(0.0, 1.0 - jitter)
    high = 1.0 + jitter
    delay = int(delay * random.uniform(low, high))

if delay < 0:
    delay = 0

print(delay)
PY
}

sleep_ms() {
  local ms="${1:-0}"
  local seconds
  seconds="$(python3 - "$ms" <<'PY'
import sys

try:
    value = float(sys.argv[1])
except (IndexError, ValueError):
    value = 0.0

if value <= 0:
    raise SystemExit(0)

print(f"{value / 1000.0:.3f}")
PY
)"
  if [ -n "${seconds}" ]; then
    sleep "${seconds}"
  fi
}

check_mdns_absence_dbus() {
  if ! command -v gdbus >/dev/null 2>&1; then
    return 2
  fi

  mapfile -t host_variants < <(mdns_absence_host_variants)
  if [ "${#host_variants[@]}" -eq 0 ]; then
    return 0
  fi

  local -A seen_instances=()
  local -a candidates=()
  local host role instance
  for host in "${host_variants[@]}"; do
    [ -n "${host}" ] || continue
    for role in "" "server" "bootstrap"; do
      instance="k3s-${CLUSTER}-${ENVIRONMENT}@${host}"
      if [ -n "${role}" ]; then
        instance="${instance} (${role})"
      fi
      if [ -n "${seen_instances[${instance}]:-}" ]; then
        continue
      fi
      seen_instances["${instance}"]=1
      candidates+=("${instance}")
    done
  done

  if [ "${#candidates[@]}" -eq 0 ]; then
    return 0
  fi

  local service_type="${MDNS_SERVICE_TYPE}"
  local domain="${MDNS_SERVICE_DOMAIN}"
  local candidate output status
  for candidate in "${candidates[@]}"; do
    if output=$(gdbus call --system --dest org.freedesktop.Avahi --object-path / \
      --method org.freedesktop.Avahi.Server.ResolveService \
      int32:-1 int32:-1 "${candidate}" "${service_type}" "${domain}" int32:-1 uint32:0 2>&1); then
      log_debug discover event=mdns_absence_dbus outcome=present candidate="${candidate}"
      return 1
    fi
    status=$?
    case "${status}" in
      126|127)
        log_debug discover event=mdns_absence_dbus outcome=unavailable candidate="${candidate}" status="${status}"
        return 2
        ;;
    esac
    if printf '%s' "${output}" | grep -q 'org.freedesktop.DBus.Error'; then
      if printf '%s' "${output}" | grep -Eq 'ServiceUnknown|NameHasNoOwner|NoReply'; then
        log_debug discover event=mdns_absence_dbus outcome=bus_unavailable candidate="${candidate}" detail="$(printf '%s' "${output}" | tr '\n' ' ')"
        return 2
      fi
    fi
  done

  return 0
}

check_mdns_absence_cli() {
  local service_type="${MDNS_SERVICE_TYPE}"
  local -a host_args=()
  mapfile -t host_args < <(mdns_absence_host_variants)
  if [ "${#host_args[@]}" -eq 0 ]; then
    return 0
  fi

  python3 - "${service_type}" "${CLUSTER}" "${ENVIRONMENT}" "${host_args[@]}" <<'PY'
import subprocess
import sys
from k3s_mdns_parser import parse_mdns_records
from mdns_helpers import _norm_host

service_type = sys.argv[1]
cluster = sys.argv[2]
environment = sys.argv[3]
targets = {_norm_host(value) for value in sys.argv[4:] if value}

if not targets:
    raise SystemExit(0)

command = ["avahi-browse", "-rptk", service_type]

try:
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
except FileNotFoundError:
    raise SystemExit(2) from None

lines = [line for line in (proc.stdout or "").splitlines() if line]
if not lines:
    raise SystemExit(0)

records = parse_mdns_records(lines, cluster, environment)

for record in records:
    host = _norm_host(record.host)
    leader = _norm_host(record.txt.get("leader", "")) if getattr(record, "txt", None) else ""
    if host in targets or (leader and leader in targets):
        raise SystemExit(1)

raise SystemExit(0)
PY
}

confirm_mdns_absence_gate() {
  if [ "${SUGARKUBE_SKIP_MDNS_ABSENCE_GATE:-0}" = "1" ]; then
    log_info discover event=mdns_absence mdns_absence_confirmed=1 reason=skipped attempts=0 ms_elapsed=0 >&2
    return 0
  fi

  if ! restart_avahi_daemon_service; then
    log_warn_msg discover "Failed to restart avahi-daemon before absence gate" "mdns_absence_restart_failed=1"
  else
    log_debug discover event=mdns_absence_restart outcome=ok
  fi

  local start_ms
  start_ms="$(monotonic_ms)"
  local attempt=0
  local consecutive=0
  local use_cli=0
  local fallback_used=0
  local last_strategy="dbus"
  local result=0
  local cli_unavailable_logged=0

  while :; do
    attempt=$((attempt + 1))
    local strategy="dbus"

    if [ "${use_cli}" -eq 1 ]; then
      strategy="cli"
      check_mdns_absence_cli
      result=$?
      if [ "${result}" -eq 2 ] && [ "${cli_unavailable_logged}" -eq 0 ]; then
        log_warn_msg discover "CLI mDNS absence probe unavailable" "mdns_absence_cli_unavailable=1"
        cli_unavailable_logged=1
      fi
    else
      check_mdns_absence_dbus
      result=$?
      if [ "${result}" -eq 2 ]; then
        use_cli=1
        fallback_used=1
        attempt=$((attempt - 1))
        log_debug discover event=mdns_absence_switch strategy="cli" reason=dbus_unavailable
        continue
      fi
    fi

    last_strategy="${strategy}"

    if [ "${result}" -eq 0 ]; then
      consecutive=$((consecutive + 1))
    else
      consecutive=0
    fi

    local attempt_result="unknown"
    case "${result}" in
      0) attempt_result="absent" ;;
      1) attempt_result="present" ;;
      2) attempt_result="error" ;;
    esac

    log_debug discover \
      event=mdns_absence_attempt \
      attempt="${attempt}" \
      strategy="${strategy}" \
      result="${attempt_result}" \
      consecutive="${consecutive}" \
      required="${MDNS_ABSENCE_REQUIRED_CONSEC}" \
      fallback_used="${fallback_used}"

    local elapsed
    elapsed="$(elapsed_ms_since "${start_ms}")"

    if [ "${consecutive}" -ge "${MDNS_ABSENCE_REQUIRED_CONSEC}" ]; then
      log_info discover \
        event=mdns_absence \
        mdns_absence_confirmed=1 \
        attempts="${attempt}" \
        ms_elapsed="${elapsed}" \
        strategy="${last_strategy}" \
        fallback_used="${fallback_used}" \
        consecutive_required="${MDNS_ABSENCE_REQUIRED_CONSEC}" >&2
      return 0
    fi

    if [ "${MDNS_ABSENCE_MAX_ATTEMPTS}" -gt 0 ] && [ "${attempt}" -ge "${MDNS_ABSENCE_MAX_ATTEMPTS}" ]; then
      break
    fi
    if [ "${MDNS_ABSENCE_TIMEOUT_MS}" -gt 0 ] && [ "${elapsed}" -ge "${MDNS_ABSENCE_TIMEOUT_MS}" ]; then
      break
    fi

    local delay_ms
    delay_ms="$(compute_absence_delay_ms "${attempt}")"
    sleep_ms "${delay_ms}"
  done

  local total_elapsed
  total_elapsed="$(elapsed_ms_since "${start_ms}")"
  log_warn_msg discover \
    "mDNS absence gate timed out" \
    "mdns_absence_confirmed=0" \
    "attempts=${attempt}" \
    "ms_elapsed=${total_elapsed}" \
    "fallback_used=${fallback_used}" \
    "consecutive_required=${MDNS_ABSENCE_REQUIRED_CONSEC}"

  return 0
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

ensure_self_mdns_advertisement() {
  local role="$1"
  if [ "${SKIP_MDNS_SELF_CHECK}" = "1" ]; then
    MDNS_LAST_OBSERVED="${MDNS_HOST_RAW}"
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
  if [ "$#" -gt 0 ]; then port="$1"; shift; fi

  run_privileged install -d -m 755 "${AVAHI_SERVICE_DIR}"
  if [ -f "${AVAHI_SERVICE_DIR}/k3s-https.service" ]; then
    remove_privileged_file "${AVAHI_SERVICE_DIR}/k3s-https.service" || true
  fi

  local xml
  xml="$(render_avahi_service_xml "${role}" "${port}" "$@")"
  printf '%s\n' "${xml}" | write_privileged_file "${AVAHI_SERVICE_FILE}"

  reload_avahi_daemon || true
  AVAHI_ROLE="${role}"
}

publish_api_service() {
  start_server_publisher || true
  publish_avahi_service server 6443 "leader=${MDNS_HOST_RAW}" "phase=server"

  if ensure_self_mdns_advertisement server; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=server host="${MDNS_HOST_RAW}" observed="${observed}" phase=server check=initial >&2
    SERVER_PUBLISH_PERSIST=1
    stop_bootstrap_publisher
    return 0
  fi

  log_warn_msg mdns_selfcheck "server advertisement not visible; restarting publishers" "host=${MDNS_HOST_RAW}" "role=server"
  stop_server_publisher
  stop_address_publisher
  sleep 1

  start_server_publisher || true
  publish_avahi_service server 6443 "leader=${MDNS_HOST_RAW}" "phase=server"

  if ensure_self_mdns_advertisement server; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=server host="${MDNS_HOST_RAW}" observed="${observed}" phase=server check=restarted >&2
    log_info_msg mdns_publish "Server advertisement observed after restart" "host=${MDNS_HOST_RAW}" "role=server"
    SERVER_PUBLISH_PERSIST=1
    stop_bootstrap_publisher
    return 0
  fi

  log_error_msg mdns_selfcheck "failed to confirm server advertisement; printing diagnostics" "host=${MDNS_HOST_RAW}" "role=server"
  pgrep -a avahi-publish || true
  sed -n '1,120p' "${BOOTSTRAP_PUBLISH_LOG:-/tmp/sugar-publish-bootstrap.log}" 2>/dev/null || true
  sed -n '1,120p' "${SERVER_PUBLISH_LOG:-/tmp/sugar-publish-server.log}" 2>/dev/null || true
  return "${MDNS_SELF_CHECK_FAILURE_CODE}"
}

publish_bootstrap_service() {
  log_info mdns_publish phase=bootstrap_attempt cluster="${CLUSTER}" environment="${ENVIRONMENT}" host="${MDNS_HOST_RAW}" >&2
  start_bootstrap_publisher || true
  publish_avahi_service bootstrap 6443 "leader=${MDNS_HOST_RAW}" "phase=bootstrap" "state=pending"
  sleep 1
  if ensure_self_mdns_advertisement bootstrap; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=bootstrap host="${MDNS_HOST_RAW}" observed="${observed}" phase=bootstrap check=initial >&2
    return 0
  fi

  log_warn_msg mdns_selfcheck "bootstrap advertisement not visible; restarting publishers" "host=${MDNS_HOST_RAW}" "role=bootstrap"
  stop_bootstrap_publisher
  stop_address_publisher
  sleep 1

  start_bootstrap_publisher || true
  publish_avahi_service bootstrap 6443 "leader=${MDNS_HOST_RAW}" "phase=bootstrap" "state=pending"
  sleep 1
  if ensure_self_mdns_advertisement bootstrap; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log_info mdns_selfcheck outcome=confirmed role=bootstrap host="${MDNS_HOST_RAW}" observed="${observed}" phase=bootstrap check=restarted >&2
    log_info_msg mdns_publish "Bootstrap advertisement observed after restart" "host=${MDNS_HOST_RAW}" "role=bootstrap"
    return 0
  fi

  log_error_msg mdns_selfcheck "failed to confirm bootstrap advertisement; printing diagnostics" "host=${MDNS_HOST_RAW}" "role=bootstrap"
  pgrep -a avahi-publish || true
  sed -n '1,120p' "${BOOTSTRAP_PUBLISH_LOG:-/tmp/sugar-publish-bootstrap.log}" 2>/dev/null || true
  sed -n '1,120p' "${SERVER_PUBLISH_LOG:-/tmp/sugar-publish-server.log}" 2>/dev/null || true
  log_error_msg mdns_selfcheck "unable to confirm bootstrap advertisement; aborting" "host=${MDNS_HOST_RAW}" "role=bootstrap"
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

build_install_env() {
  local -n _target=$1
  _target=("INSTALL_K3S_CHANNEL=${K3S_CHANNEL:-stable}")
  if [ -n "${TOKEN:-}" ]; then
    _target+=("K3S_TOKEN=${TOKEN}")
  fi
}

install_server_single() {
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
      exit 1
    fi
  else
    log_warn_msg discover "k3s API did not become ready within 60s; skipping Avahi publish" "phase=install_single" "host=${MDNS_HOST_RAW}"
  fi
}

install_server_cluster_init() {
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
      exit 1
    fi
  else
    log_warn_msg discover "k3s API did not become ready within 60s; skipping Avahi publish" "phase=install_cluster_init" "host=${MDNS_HOST_RAW}"
  fi
}

install_server_join() {
  local server="$1"
  if [ -z "${TOKEN:-}" ]; then
    log_error_msg discover "Join token missing; cannot join existing HA server" "phase=install_join" "host=${MDNS_HOST_RAW}"
    exit 1
  fi
  ensure_iptables_tools
  log_info discover phase=install_join host="${MDNS_HOST_RAW}" server="${server}" desired_servers="${SERVERS_DESIRED}" >&2
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
      exit 1
    fi
  else
    log_warn_msg discover "k3s API did not become ready within 60s; skipping Avahi publish" "phase=install_join" "host=${MDNS_HOST_RAW}"
  fi
}

install_agent() {
  local server="$1"
  if [ -z "${TOKEN:-}" ]; then
    log_error_msg discover "Join token missing; cannot join agent to existing server" "phase=install_agent" "host=${MDNS_HOST_RAW}"
    exit 1
  fi
  ensure_iptables_tools
  log_info discover phase=install_agent host="${MDNS_HOST_RAW}" server="${server}" >&2
  local env_assignments
  build_install_env env_assignments
  env_assignments+=("K3S_URL=https://${server}:6443")
  curl -sfL https://get.k3s.io \
    | env "${env_assignments[@]}" \
      sh -s - agent \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}"
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

confirm_mdns_absence_gate

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
