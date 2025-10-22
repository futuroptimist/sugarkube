#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVERS_DESIRED="${SUGARKUBE_SERVERS:-1}"
NODE_TOKEN_PATH="${SUGARKUBE_NODE_TOKEN_PATH:-/var/lib/rancher/k3s/server/node-token}"
BOOT_TOKEN_PATH="${SUGARKUBE_BOOT_TOKEN_PATH:-/boot/sugarkube-node-token}"

PRINT_TOKEN_ONLY=0
CHECK_TOKEN_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --print-resolved-token)
      PRINT_TOKEN_ONLY=1
      ;;
    --check-token-only)
      CHECK_TOKEN_ONLY=1
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

  if [ -s "${NODE_TOKEN_PATH}" ]; then
    TOKEN="$(tr -d '\n' <"${NODE_TOKEN_PATH}")"
    RESOLVED_TOKEN_SOURCE="${NODE_TOKEN_PATH}"
    return 0
  fi

  if [ -s "${BOOT_TOKEN_PATH}" ]; then
    local line
    line="$(grep -m1 '^NODE_TOKEN=' "${BOOT_TOKEN_PATH}" 2>/dev/null || true)"
    if [ -n "${line}" ]; then
      TOKEN="${line#NODE_TOKEN=}"
      TOKEN="${TOKEN%$'\r'}"
      TOKEN="${TOKEN%$'\n'}"
      RESOLVED_TOKEN_SOURCE="${BOOT_TOKEN_PATH}"
      return 0
    fi
  fi

  return 1
}

resolve_local_token || true

ALLOW_BOOTSTRAP_WITHOUT_TOKEN=0
if [ -z "${TOKEN:-}" ] && [ "${SERVERS_DESIRED}" = "1" ]; then
  ALLOW_BOOTSTRAP_WITHOUT_TOKEN=1
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
AVAHI_SERVICE_FILE="/etc/avahi/services/k3s-${CLUSTER}-${ENVIRONMENT}.service"
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

run_avahi_query() {
  local mode="$1"
  python3 - "${mode}" "${CLUSTER}" "${ENVIRONMENT}" <<'PY'
import subprocess
import sys

mode, cluster, environment = sys.argv[1:4]

try:
    output = subprocess.check_output(
        [
            "avahi-browse",
            "--parsable",
            "--terminate",
            "_https._tcp",
        ],
        stderr=subprocess.DEVNULL,
        text=True,
    )
except (FileNotFoundError, subprocess.CalledProcessError):
    output = ""

records = []
for line in output.splitlines():
    if not line or line[0] not in {"=", "+", "@"}:
        continue
    parts = line.split(";")
    if len(parts) < 9:
        continue
    host = parts[7]
    port = parts[8]
    if port != "6443":
        continue
    txt = {}
    for field in parts[9:]:
        if field.startswith("txt="):
            payload = field[4:]
            if "=" in payload:
                key, value = payload.split("=", 1)
                txt[key] = value
    if txt.get("k3s") != "1":
        continue
    if txt.get("cluster") != cluster:
        continue
    if txt.get("env") != environment:
        continue
    records.append((host, txt))

if mode == "server-first":
    for host, txt in records:
        if txt.get("role") == "server":
            print(host)
            break
elif mode == "server-count":
    count = sum(1 for _, txt in records if txt.get("role") == "server")
    print(count)
elif mode == "bootstrap-hosts":
    seen = set()
    for host, txt in records:
        if txt.get("role") == "bootstrap" and host not in seen:
            seen.add(host)
            print(host)
elif mode == "bootstrap-leaders":
    seen = set()
    for host, txt in records:
        if txt.get("role") == "bootstrap":
            leader = txt.get("leader", host)
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
    sleep 5
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
  sudo install -d -m 755 /etc/avahi/services
  sudo rm -f /etc/avahi/services/k3s-https.service || true
  sudo tee "${AVAHI_SERVICE_FILE}" >/dev/null <<EOF_AVAHI
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">k3s API ${CLUSTER}/${ENVIRONMENT} on %h</name>
  <service>
    <type>_https._tcp</type>
    <port>${port}</port>
    <txt-record>k3s=1</txt-record>
    <txt-record>cluster=${CLUSTER}</txt-record>
    <txt-record>env=${ENVIRONMENT}</txt-record>
    <txt-record>role=${role}</txt-record>
EOF_AVAHI
  for record in "$@"; do
    if [ -n "${record}" ]; then
      printf '    <txt-record>%s</txt-record>\n' "${record}" | sudo tee -a "${AVAHI_SERVICE_FILE}" >/dev/null
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
  sleep 2
  local consecutive leader candidates
  consecutive=0
  for attempt in $(seq 1 15); do
    mapfile -t candidates < <(discover_bootstrap_leaders || true)
    if [ "${#candidates[@]}" -eq 0 ]; then
      consecutive=0
      log "Bootstrap leadership attempt ${attempt}/15: no candidates discovered"
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
    sleep 2
  done
  log "No stable bootstrap leader observed; proceeding as ${MDNS_HOST}"
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
    | "${env_assignments[@]}" \
      sh -s - server \
      --tls-san "${MDNS_HOST}" \
      --tls-san "${HN}" \
      --kubelet-arg "node-labels=sugarkube.cluster=${CLUSTER},sugarkube.env=${ENVIRONMENT}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  publish_avahi_service server 6443 "leader=${MDNS_HOST}"
}

install_server_cluster_init() {
  log "Bootstrapping first HA server (embedded etcd) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST}"
  local env_assignments
  build_install_env env_assignments
  curl -sfL https://get.k3s.io \
    | "${env_assignments[@]}" \
      sh -s - server \
      --cluster-init \
      --tls-san "${MDNS_HOST}" \
      --tls-san "${HN}" \
      --kubelet-arg "node-labels=sugarkube.cluster=${CLUSTER},sugarkube.env=${ENVIRONMENT}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  publish_avahi_service server 6443 "leader=${MDNS_HOST}"
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
    | "${env_assignments[@]}" \
      sh -s - server \
      --server "https://${server}:6443" \
      --tls-san "${server}" \
      --tls-san "${MDNS_HOST}" \
      --tls-san "${HN}" \
      --kubelet-arg "node-labels=sugarkube.cluster=${CLUSTER},sugarkube.env=${ENVIRONMENT}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  publish_avahi_service server 6443 "leader=${MDNS_HOST}"
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
  curl -sfL https://get.k3s.io \
    | "${env_assignments[@]}" \
      K3S_URL="https://${server}:6443" \
      sh -s - agent \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}"
}

log "Discovering existing k3s API for ${CLUSTER}/${ENVIRONMENT} via mDNS..."
server_host="$(discover_server_host || true)"

if [ -z "${server_host:-}" ]; then
  wait_result="$(wait_for_bootstrap_activity || true)"
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
