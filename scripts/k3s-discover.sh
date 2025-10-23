#!/usr/bin/env bash
set -euo pipefail

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
      echo "${SUDO_CMD%% *} command not found; run as root or set ALLOW_NON_ROOT=1" >&2
      exit 1
    fi
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
DISCOVERY_WAIT_SECS="${DISCOVERY_WAIT_SECS:-9}"
DISCOVERY_ATTEMPTS="${DISCOVERY_ATTEMPTS:-15}"
MDNS_SELF_CHECK_ATTEMPTS="${SUGARKUBE_MDNS_SELF_CHECK_ATTEMPTS:-5}"
MDNS_SELF_CHECK_DELAY="${SUGARKUBE_MDNS_SELF_CHECK_DELAY:-1}"
SKIP_MDNS_SELF_CHECK="${SUGARKUBE_SKIP_MDNS_SELF_CHECK:-0}"
SUGARKUBE_MDNS_BOOT_RETRIES="${SUGARKUBE_MDNS_BOOT_RETRIES:-${MDNS_SELF_CHECK_ATTEMPTS}}"
SUGARKUBE_MDNS_BOOT_DELAY="${SUGARKUBE_MDNS_BOOT_DELAY:-${MDNS_SELF_CHECK_DELAY}}"
SUGARKUBE_MDNS_SERVER_RETRIES="${SUGARKUBE_MDNS_SERVER_RETRIES:-60}"
SUGARKUBE_MDNS_SERVER_DELAY="${SUGARKUBE_MDNS_SERVER_DELAY:-1}"

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

HN="$(hostname -s)"
MDNS_HOST_RAW="${SUGARKUBE_MDNS_HOST:-${HN}.local}"
while [[ "${MDNS_HOST_RAW}" == *"." ]]; do
  MDNS_HOST_RAW="${MDNS_HOST_RAW%.}"
done
MDNS_HOST="${MDNS_HOST_RAW,,}"
MDNS_SERVICE_NAME="k3s-${CLUSTER}-${ENVIRONMENT}"
MDNS_SERVICE_TYPE="_${MDNS_SERVICE_NAME}._tcp"
AVAHI_SERVICE_DIR="${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}"
AVAHI_SERVICE_FILE="${SUGARKUBE_AVAHI_SERVICE_FILE:-${AVAHI_SERVICE_DIR}/k3s-${CLUSTER}-${ENVIRONMENT}.service}"
AVAHI_ROLE=""
BOOTSTRAP_PUBLISH_PID=""
BOOTSTRAP_PUBLISH_LOG=""
SERVER_PUBLISH_PID=""
SERVER_PUBLISH_LOG=""
MDNS_RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
BOOTSTRAP_PID_FILE="${MDNS_RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-bootstrap.pid"
SERVER_PID_FILE="${MDNS_RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-server.pid"
SERVER_PUBLISH_PERSIST=0
MDNS_LAST_OBSERVED=""
CLAIMED_SERVER_HOST=""

run_privileged() {
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" "$@"
  else
    "$@"
  fi
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
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if [ -n "${SUDO_CMD:-}" ]; then
    "${SUDO_CMD}" systemctl reload avahi-daemon || "${SUDO_CMD}" systemctl restart avahi-daemon
  else
    systemctl reload avahi-daemon || systemctl restart avahi-daemon
  fi
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

cleanup_avahi_publishers() {
  if [ "${SERVER_PUBLISH_PERSIST}" != "1" ]; then
    stop_server_publisher
  fi
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
  left_base="${left%'.local'}"
  right_base="${right%'.local'}"
  if [ "${left_base}" = "${left}" ] && [ "${right_base}" = "${right}" ]; then
    return 1
  fi
  [ -n "${left_base}" ] && [ "${left_base}" = "${right_base}" ]
}

log() {
  >&2 printf '[sugarkube %s/%s] %s\n' "${CLUSTER}" "${ENVIRONMENT}" "$*"
}

start_bootstrap_publisher() {
  if ! command -v avahi-publish-service >/dev/null 2>&1; then
    log "avahi-publish-service not available; relying on Avahi service file"
    return 1
  fi
  if [ -n "${BOOTSTRAP_PUBLISH_PID:-}" ] && kill -0 "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1; then
    return 0
  fi

  local publish_name
  publish_name="$(service_instance_name bootstrap "${MDNS_HOST_RAW}")"

  BOOTSTRAP_PUBLISH_LOG="/tmp/sugar-publish-bootstrap.log"
  : >"${BOOTSTRAP_PUBLISH_LOG}" 2>/dev/null || true

  avahi-publish-service \
    -H "${MDNS_HOST_RAW}" \
    "${publish_name}" \
    "${MDNS_SERVICE_TYPE}" \
    6443 \
    "k3s=1" \
    "cluster=${CLUSTER}" \
    "env=${ENVIRONMENT}" \
    "role=bootstrap" \
    "leader=${MDNS_HOST_RAW}" \
    "phase=bootstrap" \
    "state=pending" \
    >"${BOOTSTRAP_PUBLISH_LOG}" 2>&1 &
  BOOTSTRAP_PUBLISH_PID=$!

  sleep 1
  if ! kill -0 "${BOOTSTRAP_PUBLISH_PID}" >/dev/null 2>&1; then
    if [ -s "${BOOTSTRAP_PUBLISH_LOG}" ]; then
      while IFS= read -r line; do
        log "bootstrap publisher error: ${line}"
      done <"${BOOTSTRAP_PUBLISH_LOG}"
    fi
    BOOTSTRAP_PUBLISH_PID=""
    BOOTSTRAP_PUBLISH_LOG=""
    return 1
  fi

  log "avahi-publish-service advertising bootstrap as ${MDNS_HOST_RAW} on ${MDNS_SERVICE_TYPE} (pid ${BOOTSTRAP_PUBLISH_PID})"
  printf '%s\n' "${BOOTSTRAP_PUBLISH_PID}" | write_privileged_file "${BOOTSTRAP_PID_FILE}"
  return 0
}

start_server_publisher() {
  if ! command -v avahi-publish-service >/dev/null 2>&1; then
    log "avahi-publish-service not available; relying on Avahi service file"
    return 1
  fi
  if [ -n "${SERVER_PUBLISH_PID:-}" ] && kill -0 "${SERVER_PUBLISH_PID}" >/dev/null 2>&1; then
    return 0
  fi

  local publish_name
  publish_name="$(service_instance_name server "${MDNS_HOST_RAW}")"

  SERVER_PUBLISH_LOG="/tmp/sugar-publish-server.log"
  : >"${SERVER_PUBLISH_LOG}" 2>/dev/null || true

  avahi-publish-service \
    -H "${MDNS_HOST_RAW}" \
    "${publish_name}" \
    "${MDNS_SERVICE_TYPE}" \
    6443 \
    "k3s=1" \
    "cluster=${CLUSTER}" \
    "env=${ENVIRONMENT}" \
    "role=server" \
    "leader=${MDNS_HOST_RAW}" \
    "phase=server" \
    >"${SERVER_PUBLISH_LOG}" 2>&1 &
  SERVER_PUBLISH_PID=$!

  sleep 1
  if ! kill -0 "${SERVER_PUBLISH_PID}" >/dev/null 2>&1; then
    if [ -s "${SERVER_PUBLISH_LOG}" ]; then
      while IFS= read -r line; do
        log "server publisher error: ${line}"
      done <"${SERVER_PUBLISH_LOG}"
    fi
    SERVER_PUBLISH_PID=""
    SERVER_PUBLISH_LOG=""
    return 1
  fi

  log "avahi-publish-service advertising server as ${MDNS_HOST_RAW} on ${MDNS_SERVICE_TYPE} (pid ${SERVER_PUBLISH_PID})"
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

  local require_phase retries delay
  case "${role}" in
    bootstrap)
      require_phase="bootstrap"
      retries="${SUGARKUBE_MDNS_BOOT_RETRIES}"
      delay="${SUGARKUBE_MDNS_BOOT_DELAY}"
      ;;
    server)
      require_phase="server"
      retries="${SUGARKUBE_MDNS_SERVER_RETRIES}"
      delay="${SUGARKUBE_MDNS_SERVER_DELAY}"
      ;;
    *)
      return 0
      ;;
  esac

  MDNS_LAST_OBSERVED=""
  local observed=""
  if observed="$(
    python3 "${SCRIPT_DIR}/mdns_helpers.py" \
      --expect-host "${MDNS_HOST_RAW}" \
      --cluster "${CLUSTER}" \
      --env "${ENVIRONMENT}" \
      --require-phase "${require_phase}" \
      --retries "${retries}" \
      --delay "${delay}"
  )"; then
    MDNS_LAST_OBSERVED="${observed}"
    return 0
  fi

  return 1
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
  for attempt in $(seq 1 "${attempts}"); do
    local server
    server="$(discover_server_host || true)"
    if [ -n "${server}" ]; then
      log "Discovered API server advertisement from ${server} (attempt ${attempt}/${effective_attempts})"
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
      log "Bootstrap advertisement(s) detected from ${bootstrap_hosts} (attempt ${attempt}/${effective_attempts}); waiting for server advertisement..."
    else
      if [ "${require_activity}" -eq 1 ]; then
        no_activity_streak=$((no_activity_streak + 1))
        if [ "${activity_grace_attempts}" -gt 0 ] && [ "${no_activity_streak}" -ge "${activity_grace_attempts}" ]; then
          log "No bootstrap advertisements detected (attempt ${attempt}/${effective_attempts}); exiting discovery wait."
          return 1
        fi
        log "No bootstrap activity detected yet (attempt ${attempt}/${effective_attempts}); will retry before giving up."
      elif [ "${observed_activity}" -eq 0 ]; then
        log "No bootstrap activity detected yet (attempt ${attempt}/${effective_attempts})."
      else
        log "Bootstrap activity previously detected; continuing to wait (attempt ${attempt}/${effective_attempts})."
      fi
    fi

    if [ "${attempt}" -lt "${attempts}" ]; then
      local next_attempt
      next_attempt=$((attempt + 1))
      log "Sleeping ${wait_secs}s before retry ${next_attempt}/${effective_attempts}."
      sleep "${wait_secs}"
    fi
  done

  if [ "${observed_activity}" -eq 1 ]; then
    log "Bootstrap advertisements did not yield a server after ${attempts} attempts."
  else
    log "No bootstrap activity observed after ${attempts} attempts."
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
    log "phase=self-check host=${MDNS_HOST_RAW} observed=${observed}; server advertisement confirmed."
    SERVER_PUBLISH_PERSIST=1
    stop_bootstrap_publisher
    return 0
  fi

  log "Failed to confirm Avahi server advertisement for ${MDNS_HOST_RAW}; printing diagnostics:"
  pgrep -a avahi-publish || true
  sed -n '1,120p' "${BOOTSTRAP_PUBLISH_LOG:-/tmp/sugar-publish-bootstrap.log}" 2>/dev/null || true
  sed -n '1,120p' "${SERVER_PUBLISH_LOG:-/tmp/sugar-publish-server.log}" 2>/dev/null || true
  return 1
}

publish_bootstrap_service() {
  log "Advertising bootstrap attempt for ${CLUSTER}/${ENVIRONMENT} via Avahi"
  start_bootstrap_publisher || true
  publish_avahi_service bootstrap 6443 "leader=${MDNS_HOST_RAW}" "phase=bootstrap" "state=pending"
  sleep 1
  if ensure_self_mdns_advertisement bootstrap; then
    local observed
    observed="${MDNS_LAST_OBSERVED:-${MDNS_HOST_RAW}}"
    log "phase=self-check host=${MDNS_HOST_RAW} observed=${observed}; bootstrap advertisement confirmed."
    return 0
  fi

  log "Unable to confirm bootstrap advertisement for ${MDNS_HOST_RAW}; aborting to avoid split brain"
  return 1
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
      log "Server advertisement from ${server} observed during bootstrap election; deferring bootstrap."
      CLAIMED_SERVER_HOST="${server}"
      cleanup_avahi_publishers
      return 2
    fi

    mapfile -t candidates < <(discover_bootstrap_leaders || true)
    if [ "${#candidates[@]}" -eq 0 ]; then
      consecutive=0
      log "Bootstrap leadership attempt ${attempt}/${DISCOVERY_ATTEMPTS}: no candidates discovered"
    else
      leader="$(printf '%s\n' "${candidates[@]}" | sort | head -n1)"
      if same_host "${leader}" "${MDNS_HOST_RAW}"; then
        consecutive=$((consecutive + 1))
        if [ "${consecutive}" -ge 3 ]; then
          log "Confirmed bootstrap leadership as ${MDNS_HOST_RAW}"
          return 0
        fi
      else
        log "Bootstrap leader ${leader} detected; deferring cluster initialization"
        cleanup_avahi_publishers
        return 1
      fi
    fi
    sleep "${DISCOVERY_WAIT_SECS}"
  done
  log "No stable bootstrap leader observed; proceeding as ${MDNS_HOST_RAW}"
  return 0
}

build_install_env() {
  local -n _target=$1
  _target=("INSTALL_K3S_CHANNEL=${K3S_CHANNEL:-stable}")
  if [ -n "${TOKEN:-}" ]; then
    _target+=("K3S_TOKEN=${TOKEN}")
  fi
}

install_server_single() {
  log "Bootstrapping single-server (SQLite) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST_RAW}"
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
      log "Failed to confirm Avahi server advertisement for ${MDNS_HOST_RAW}; aborting"
      exit 1
    fi
  else
    log "k3s API did not become ready within 60s; skipping Avahi publish"
  fi
}

install_server_cluster_init() {
  log "Bootstrapping first HA server (embedded etcd) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST_RAW}"
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
      log "Failed to confirm Avahi server advertisement for ${MDNS_HOST_RAW}; aborting"
      exit 1
    fi
  else
    log "k3s API did not become ready within 60s; skipping Avahi publish"
  fi
}

install_server_join() {
  local server="$1"
  if [ -z "${TOKEN:-}" ]; then
    log "Join token missing; cannot join existing HA server"
    exit 1
  fi
  log "Joining as additional HA server via https://${server}:6443 (desired servers=${SERVERS_DESIRED})"
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
      log "Failed to confirm Avahi server advertisement for ${MDNS_HOST_RAW}; aborting"
      exit 1
    fi
  else
    log "k3s API did not become ready within 60s; skipping Avahi publish"
  fi
}

install_agent() {
  local server="$1"
  if [ -z "${TOKEN:-}" ]; then
    log "Join token missing; cannot join agent to existing server"
    exit 1
  fi
  log "Joining as agent via https://${server}:6443"
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

log "Discovering existing k3s API for ${CLUSTER}/${ENVIRONMENT} via mDNS..."
server_host="$(discover_server_host || true)"

if [ -z "${server_host:-}" ]; then
  wait_result="$(wait_for_bootstrap_activity --require-activity || true)"
  if [ -n "${wait_result:-}" ]; then
    server_host="${wait_result}"
  fi
fi

if [ -z "${server_host:-}" ]; then
  jitter=$((RANDOM % 11 + 5))
  log "No servers discovered yet; waiting ${jitter}s before attempting bootstrap..."
  sleep "${jitter}"
  server_host="$(discover_server_host || true)"
  if [ -z "${server_host:-}" ]; then
    wait_result="$(wait_for_bootstrap_activity --require-activity || true)"
    if [ -n "${wait_result:-}" ]; then
      server_host="${wait_result}"
    fi
  fi
fi

bootstrap_selected="false"
if [ -z "${server_host:-}" ]; then
  CLAIMED_SERVER_HOST=""
  if claim_bootstrap_leadership; then
    bootstrap_selected="true"
  else
    claim_status=$?
    if [ "${claim_status}" -eq 2 ]; then
      if [ -n "${CLAIMED_SERVER_HOST:-}" ]; then
        server_host="${CLAIMED_SERVER_HOST}"
      else
        server_host="$(discover_server_host || true)"
      fi
    else
      server_host="$(wait_for_bootstrap_activity || true)"
    fi
  fi
fi

if [ "${bootstrap_selected}" = "true" ]; then
  if [ "${SERVERS_DESIRED}" = "1" ]; then
    install_server_single
  else
    install_server_cluster_init
  fi
else
  servers_now="$(count_servers)"
  if [ "${servers_now}" -lt "${SERVERS_DESIRED}" ]; then
    if [ -z "${server_host:-}" ]; then
      server_host="$(discover_server_host || true)"
    fi
    if [ -z "${server_host:-}" ]; then
      log "No servers discovered after waiting; proceeding with bootstrap fallback"
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
      log "Unable to discover an API server to join as agent; exiting"
      exit 1
    fi
    install_agent "${server_host}"
  fi
fi

if [ -f /etc/rancher/k3s/k3s.yaml ]; then
  run_privileged mkdir -p /root/.kube
  run_privileged cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
fi
