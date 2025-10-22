#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVERS_DESIRED="${SUGARKUBE_SERVERS:-1}"
NODE_TOKEN_PATH="${SUGARKUBE_NODE_TOKEN_PATH:-/var/lib/rancher/k3s/server/node-token}"
BOOT_TOKEN_PATH="${SUGARKUBE_BOOT_TOKEN_PATH:-/boot/sugarkube-node-token}"

DISCOVERY_WAIT_SECS="${DISCOVERY_WAIT_SECS:-9}"
DISCOVERY_ATTEMPTS="${DISCOVERY_ATTEMPTS:-15}"

case "${DISCOVERY_WAIT_SECS}" in
  ''|*[!0-9]*) DISCOVERY_WAIT_SECS=9 ;;
esac
case "${DISCOVERY_ATTEMPTS}" in
  ''|*[!0-9]*) DISCOVERY_ATTEMPTS=15 ;;
esac

PRINT_TOKEN_ONLY=0
CHECK_TOKEN_ONLY=0

NODE_TOKEN_PRESENT=0
BOOT_TOKEN_PRESENT=0

TEST_RUN_AVAHI=""
TEST_RENDER_SERVICE=0
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
MDNS_HOST="${HN}.local"
AVAHI_SERVICE_DIR="${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}"
AVAHI_SERVICE_FILE="${SUGARKUBE_AVAHI_SERVICE_FILE:-${AVAHI_SERVICE_DIR}/k3s-${CLUSTER}-${ENVIRONMENT}.service}"
AVAHI_ROLE=""

cleanup_avahi_bootstrap() {
  if [ "${AVAHI_ROLE}" = "bootstrap" ]; then
    sudo rm -f "${AVAHI_SERVICE_FILE}" || true
    sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
    AVAHI_ROLE=""
  fi
}

trap cleanup_avahi_bootstrap EXIT

log() {
  echo "[sugarkube ${CLUSTER}/${ENVIRONMENT}] $*"
}

wait_for_api() {
  local attempt=0
  local max_attempts=60
  while [ "${attempt}" -lt "${max_attempts}" ]; do
    if command -v ss >/dev/null 2>&1; then
      if ss -ltn '( sport = :6443 )' 2>/dev/null | grep -q LISTEN; then
        return 0
      fi
    fi
    if command -v timeout >/dev/null 2>&1; then
      if timeout 1 bash -c '>/dev/tcp/127.0.0.1/6443' >/dev/null 2>&1; then
        return 0
      fi
    else
      if bash -c '>/dev/tcp/127.0.0.1/6443' >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  return 1
}

sleep_for_discovery() {
  if [ "${DISCOVERY_WAIT_SECS}" -gt 0 ]; then
    sleep "${DISCOVERY_WAIT_SECS}"
  fi
}

xml_escape() {
  python3 - "$1" <<'PY'
import html
import sys

print(html.escape(sys.argv[1], quote=True))
PY
}

publish_api_service() {
  local port="6443"
  if [ "$#" -gt 0 ] && [ -n "${1:-}" ]; then
    port="$1"
    shift
  fi

  if [ "${AVAHI_ROLE}" = "bootstrap" ]; then
    cleanup_avahi_bootstrap
  fi

  sudo install -d -m 755 "${AVAHI_SERVICE_DIR}"

  local xml_service_name xml_port xml_cluster xml_env
  xml_service_name="$(xml_escape "k3s API ${CLUSTER}/${ENVIRONMENT} on %h")"
  xml_port="$(xml_escape "${port}")"
  xml_cluster="$(xml_escape "${CLUSTER}")"
  xml_env="$(xml_escape "${ENVIRONMENT}")"

  sudo tee "${AVAHI_SERVICE_FILE}" >/dev/null <<EOF_AVAHI_API
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">${xml_service_name}</name>
  <service>
    <type>_https._tcp</type>
    <port>${xml_port}</port>
    <txt-record>k3s=1</txt-record>
    <txt-record>cluster=${xml_cluster}</txt-record>
    <txt-record>env=${xml_env}</txt-record>
    <txt-record>role=server</txt-record>
EOF_AVAHI_API

  local record
  for record in "$@"; do
    if [ -n "${record}" ]; then
      local escaped_record
      escaped_record="$(xml_escape "${record}")"
      printf '    <txt-record>%s</txt-record>\n' "${escaped_record}" | sudo tee -a "${AVAHI_SERVICE_FILE}" >/dev/null
    fi
  done

  sudo tee -a "${AVAHI_SERVICE_FILE}" >/dev/null <<'EOF_AVAHI_API'
  </service>
</service-group>
EOF_AVAHI_API

  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
  fi

  AVAHI_ROLE="server"
}

advertise_server_api() {
  if wait_for_api; then
    publish_api_service 6443 "leader=${MDNS_HOST}"
  else
    log "Timed out waiting for k3s API on ${MDNS_HOST}; Avahi service not published"
  fi
}

run_avahi_query() {
  local mode="$1"
  python3 - "${mode}" "${CLUSTER}" "${ENVIRONMENT}" <<'PY'
import os
import subprocess
import sys

from scripts.mdns_parser import parse_avahi_output

mode, cluster, environment = sys.argv[1:4]

debug_enabled = bool(os.environ.get("SUGARKUBE_DEBUG"))


def debug(message: str) -> None:
    if debug_enabled:
        print(f"[k3s-discover mdns] {message}", file=sys.stderr)

try:
    output = subprocess.check_output(
        [
            "avahi-browse",
            "--parsable",
            "--terminate",
            "--resolve",  # required for host/port/TXT details
            "--ignore-local",  # avoid matching local bootstrap adverts
            "_https._tcp",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
except (FileNotFoundError, subprocess.CalledProcessError):
    output = ""

records, resolved_lines = parse_avahi_output(output, cluster, environment)

if debug_enabled and not records and resolved_lines:
    debug("No matching mDNS candidates; writing browse dump to /tmp/sugarkube-mdns.txt")
    try:
        with open("/tmp/sugarkube-mdns.txt", "a", encoding="utf-8") as handle:
            handle.write("\n".join(resolved_lines))
            handle.write("\n")
    except OSError:
        debug("Failed to write /tmp/sugarkube-mdns.txt")

if mode == "server-first":
    for record in records:
        if record.txt.get("role") == "server":
            print(record.hostname)
            break
elif mode == "server-count":
    count = sum(1 for record in records if record.txt.get("role") == "server")
    print(count)
elif mode == "bootstrap-hosts":
    seen = set()
    for record in records:
        if record.txt.get("role") == "bootstrap" and record.hostname not in seen:
            seen.add(record.hostname)
            print(record.hostname)
elif mode == "bootstrap-leaders":
    seen = set()
    for record in records:
        if record.txt.get("role") == "bootstrap":
            leader = record.txt.get("leader", record.hostname)
            if leader not in seen:
                seen.add(leader)
                print(leader)
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

count_servers() {
  local count
  count="$(run_avahi_query server-count | head -n1)"
  if [ -z "${count}" ]; then
    count=0
  fi
  echo "${count}"
}

wait_for_bootstrap_activity() {
  while true; do
    local server
    server="$(discover_server_host || true)"
    if [ -n "${server}" ]; then
      echo "${server}"
      return 0
    fi

    local bootstrap
    bootstrap="$(discover_bootstrap_hosts || true)"
    if [ -z "${bootstrap}" ]; then
      return 1
    fi

    log "Bootstrap in progress on ${bootstrap//$'\n'/, }; waiting for server advertisement..."
    sleep_for_discovery
  done
}

publish_avahi_service() {
  local role="$1"
  shift
  local port="6443"
  if [ "$#" -gt 0 ]; then
    port="$1"
    shift
  fi

  if [ "${role}" = "server" ]; then
    publish_api_service "${port}" "$@"
    return 0
  fi

  sudo install -d -m 755 "${AVAHI_SERVICE_DIR}"
  sudo rm -f "${AVAHI_SERVICE_DIR}/k3s-https.service" || true
  local service_name
  service_name="k3s API ${CLUSTER}/${ENVIRONMENT} on %h"
  local xml_service_name xml_port xml_cluster xml_env xml_role
  xml_service_name="$(xml_escape "${service_name}")"
  xml_port="$(xml_escape "${port}")"
  xml_cluster="$(xml_escape "${CLUSTER}")"
  xml_env="$(xml_escape "${ENVIRONMENT}")"
  xml_role="$(xml_escape "${role}")"
  sudo tee "${AVAHI_SERVICE_FILE}" >/dev/null <<EOF_AVAHI
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">${xml_service_name}</name>
  <service>
    <type>_https._tcp</type>
    <port>${xml_port}</port>
    <txt-record>k3s=1</txt-record>
    <txt-record>cluster=${xml_cluster}</txt-record>
    <txt-record>env=${xml_env}</txt-record>
    <txt-record>role=${xml_role}</txt-record>
EOF_AVAHI
  local record
  for record in "$@"; do
    if [ -n "${record}" ]; then
      local escaped_record
      escaped_record="$(xml_escape "${record}")"
      printf '    <txt-record>%s</txt-record>\n' "${escaped_record}" | sudo tee -a "${AVAHI_SERVICE_FILE}" >/dev/null
    fi
  done
  sudo tee -a "${AVAHI_SERVICE_FILE}" >/dev/null <<'EOF_AVAHI'
  </service>
</service-group>
EOF_AVAHI
  sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
  AVAHI_ROLE="${role}"
}

publish_bootstrap_service() {
  log "Advertising bootstrap attempt for ${CLUSTER}/${ENVIRONMENT} via Avahi"
  publish_avahi_service bootstrap 6443 "leader=${MDNS_HOST}" "state=pending"
}

claim_bootstrap_leadership() {
  publish_bootstrap_service
  sleep_for_discovery
  local consecutive leader candidates total_attempts
  consecutive=0
  total_attempts="${DISCOVERY_ATTEMPTS}"
  if [ "${total_attempts}" -lt 1 ]; then
    total_attempts=1
  fi
  for attempt in $(seq 1 "${total_attempts}"); do
    mapfile -t candidates < <(discover_bootstrap_leaders || true)
    if [ "${#candidates[@]}" -eq 0 ]; then
      consecutive=0
      log "Bootstrap leadership attempt ${attempt}/${total_attempts}: no candidates discovered"
    else
      leader="$(printf '%s\n' "${candidates[@]}" | sort | head -n1)"
      if [ "${leader}" = "${MDNS_HOST}" ]; then
        consecutive=$((consecutive + 1))
        if [ "${consecutive}" -ge 3 ]; then
          log "Confirmed bootstrap leadership as ${MDNS_HOST}"
          return 0
        fi
      else
        log "Bootstrap leader ${leader} detected; deferring cluster initialization"
        cleanup_avahi_bootstrap
        return 1
      fi
    fi
    sleep_for_discovery
  done
  log "No stable bootstrap leader observed after ${total_attempts} attempts; proceeding as ${MDNS_HOST}"
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
  log "Bootstrapping single-server (SQLite) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST}"
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
  advertise_server_api
}

install_server_cluster_init() {
  log "Bootstrapping first HA server (embedded etcd) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST}"
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
  advertise_server_api
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
  advertise_server_api
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
  publish_avahi_service "${TEST_RENDER_ARGS[@]}"
  exit 0
fi

log "Discovering existing k3s API for ${CLUSTER}/${ENVIRONMENT} via mDNS..."
server_host="$(discover_server_host || true)"

if [ -z "${server_host:-}" ]; then
  wait_result="$(wait_for_bootstrap_activity || true)"
  if [ -n "${wait_result:-}" ]; then
    server_host="${wait_result}"
  fi
fi

if [ -z "${server_host:-}" ]; then
  jitter="${DISCOVERY_WAIT_SECS}"
  if [ "${jitter}" -gt 1 ]; then
    jitter=$((RANDOM % jitter + 1))
  fi
  if [ "${jitter}" -gt 0 ]; then
    log "No servers discovered yet; waiting ${jitter}s before attempting bootstrap..."
    sleep "${jitter}"
  else
    log "No servers discovered yet; retrying bootstrap discovery immediately..."
  fi
  server_host="$(discover_server_host || true)"
  if [ -z "${server_host:-}" ]; then
    wait_result="$(wait_for_bootstrap_activity || true)"
    if [ -n "${wait_result:-}" ]; then
      server_host="${wait_result}"
    fi
  fi
fi

bootstrap_selected="false"
if [ -z "${server_host:-}" ]; then
  if claim_bootstrap_leadership; then
    bootstrap_selected="true"
  else
    server_host="$(wait_for_bootstrap_activity || true)"
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
  sudo mkdir -p /root/.kube
  sudo cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
fi
