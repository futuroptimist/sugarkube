#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVERS_DESIRED="${SUGARKUBE_SERVERS:-1}"

log() {
  echo "[sugarkube ${CLUSTER}/${ENVIRONMENT}] $*"
}

AVAHI_SERVICES_DIR="${SUGARKUBE_AVAHI_SERVICES_DIR:-/etc/avahi/services}"
AVAHI_DEFAULT_SERVICE="${AVAHI_SERVICES_DIR}/k3s-https.service"
AVAHI_SERVICE_FILE="${AVAHI_SERVICES_DIR}/k3s-${CLUSTER}-${ENVIRONMENT}.service"
AVAHI_ROLE=""

TOKEN_SOURCE=""
TOKEN=""

resolve_token_from_files() {
  local -a candidates
  local hints="${SUGARKUBE_TOKEN_PATH_HINTS:-}"

  if [ -n "${hints}" ]; then
    IFS=: read -r -a hint_array <<<"${hints}"
    for path in "${hint_array[@]}"; do
      if [ -n "${path}" ]; then
        candidates+=("${path}")
      fi
    done
  fi

  candidates+=(
    "/var/lib/rancher/k3s/server/node-token"
    "/var/lib/rancher/k3s/server/token"
    "/var/lib/rancher/k3s/server/agent-token"
    "/var/lib/rancher/k3s/agent/node-token"
    "/var/lib/rancher/k3s/agent/token"
    "/run/k3s/token"
  )

  local candidate raw trimmed
  for candidate in "${candidates[@]}"; do
    if [ -r "${candidate}" ]; then
      raw="$(head -n1 "${candidate}" 2>/dev/null || true)"
      trimmed="$(printf '%s' "${raw}" | tr -d '[:space:]')"
      if [ -n "${trimmed}" ]; then
        TOKEN="${trimmed}"
        TOKEN_SOURCE="${candidate}"
        return 0
      fi
    fi
  done

  local env_path="${SUGARKUBE_K3S_SERVICE_ENV:-/etc/systemd/system/k3s.service.env}"
  if [ -r "${env_path}" ]; then
    local env_token
    env_token="$(python3 - "${env_path}" <<'PY' 2>/dev/null
import sys

path = sys.argv[1]
token = None
try:
    with open(path, 'r', encoding='utf-8') as handle:
        for line in handle:
            if line.startswith('K3S_TOKEN='):
                token = line.split('=', 1)[1].strip()
                break
except FileNotFoundError:
    token = None

if token:
    if token[0] in {'"', "'"} and token[-1] == token[0]:
        token = token[1:-1]
    print(token)
PY
)"
    env_token="$(printf '%s' "${env_token}" | tr -d '[:space:]')"
    if [ -n "${env_token}" ]; then
      TOKEN="${env_token}"
      TOKEN_SOURCE="${env_path}"
      return 0
    fi
  fi

  return 1
}

case "${ENVIRONMENT}" in
  dev)
    if [ -n "${SUGARKUBE_TOKEN_DEV:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN_DEV}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN_DEV"
    elif [ -n "${SUGARKUBE_TOKEN:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN"
    fi
    ;;
  int)
    if [ -n "${SUGARKUBE_TOKEN_INT:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN_INT}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN_INT"
    elif [ -n "${SUGARKUBE_TOKEN:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN"
    fi
    ;;
  prod)
    if [ -n "${SUGARKUBE_TOKEN_PROD:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN_PROD}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN_PROD"
    elif [ -n "${SUGARKUBE_TOKEN:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN"
    fi
    ;;
  *)
    if [ -n "${SUGARKUBE_TOKEN:-}" ]; then
      TOKEN="${SUGARKUBE_TOKEN}"
      TOKEN_SOURCE="environment variable SUGARKUBE_TOKEN"
    fi
    ;;
esac

if [ -z "${TOKEN:-}" ] && ! resolve_token_from_files; then
  echo "SUGARKUBE_TOKEN (or per-env variant) required"
  exit 1
fi

if [ -z "${TOKEN_SOURCE}" ]; then
  TOKEN_SOURCE="automatically discovered token"
fi

log "Using join token from ${TOKEN_SOURCE}"

HN="$(hostname -s)"
MDNS_HOST="${HN}.local"

cleanup_avahi_bootstrap() {
  if [ "${AVAHI_ROLE}" = "bootstrap" ]; then
    sudo rm -f "${AVAHI_SERVICE_FILE}" || true
    sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
    AVAHI_ROLE=""
  fi
}

trap cleanup_avahi_bootstrap EXIT

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
  sudo install -d -m 755 "${AVAHI_SERVICES_DIR}"
  sudo rm -f "${AVAHI_DEFAULT_SERVICE}" || true
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

install_server_single() {
  log "Bootstrapping single-server (SQLite) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST}"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_TOKEN="${TOKEN}" \
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
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_TOKEN="${TOKEN}" \
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
  log "Joining as additional HA server via https://${server}:6443 (desired servers=${SERVERS_DESIRED})"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_TOKEN="${TOKEN}" \
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
  log "Joining as agent via https://${server}:6443"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_URL="https://${server}:6443" \
      K3S_TOKEN="${TOKEN}" \
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
