#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVERS_DESIRED="${SUGARKUBE_SERVERS:-1}"

case "${ENVIRONMENT}" in
  dev) TOKEN="${SUGARKUBE_TOKEN_DEV:-${SUGARKUBE_TOKEN:-}}" ;;
  int) TOKEN="${SUGARKUBE_TOKEN_INT:-${SUGARKUBE_TOKEN:-}}" ;;
  prod) TOKEN="${SUGARKUBE_TOKEN_PROD:-${SUGARKUBE_TOKEN:-}}" ;;
  *) TOKEN="${SUGARKUBE_TOKEN:-}" ;;
esac

if [ -z "${TOKEN:-}" ]; then
  echo "SUGARKUBE_TOKEN (or per-env variant) required"
  exit 1
fi

HN="$(hostname -s)"
MDNS_HOST="${HN}.local"
AVAHI_SERVICE_FILE="/etc/avahi/services/k3s-${CLUSTER}-${ENVIRONMENT}.service"
AVAHI_ROLE=""

cleanup_avahi_bootstrap() {
  if [ "${AVAHI_ROLE}" = "bootstrap" ]; then
    sudo rm -f "${AVAHI_SERVICE_FILE}" || true
    sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
  fi
}

trap cleanup_avahi_bootstrap EXIT

log() {
  echo "[sugarkube ${CLUSTER}/${ENVIRONMENT}] $*"
}

discover_server_host() {
  avahi-browse -rt _https._tcp 2>/dev/null \
    | awk -F';' '/;_https._tcp;/{print}' \
    | while IFS=';' read -r _ _ _ _ _ _ _ host _ port txt; do
        if [ "${port}" = "6443" ] \
          && echo "${txt}" | grep -q 'k3s=1' \
          && echo "${txt}" | grep -q "cluster=${CLUSTER}" \
          && echo "${txt}" | grep -q "env=${ENVIRONMENT}" \
          && echo "${txt}" | grep -q 'role=server'; then
          echo "${host}"
          break
        fi
      done \
    | head -n1
}

discover_bootstrap_hosts() {
  avahi-browse -rt _https._tcp 2>/dev/null \
    | awk -F';' '/;_https._tcp;/{print}' \
    | while IFS=';' read -r _ _ _ _ _ _ _ host _ port txt; do
        if [ "${port}" = "6443" ] \
          && echo "${txt}" | grep -q 'k3s=1' \
          && echo "${txt}" | grep -q "cluster=${CLUSTER}" \
          && echo "${txt}" | grep -q "env=${ENVIRONMENT}" \
          && echo "${txt}" | grep -q 'role=bootstrap'; then
          echo "${host}"
        fi
      done \
    | sort -u
}

count_servers() {
  avahi-browse -rt _https._tcp 2>/dev/null \
    | awk -F';' '/;_https._tcp;/{print}' \
    | grep ';6443;' \
    | grep 'k3s=1' \
    | grep "cluster=${CLUSTER}" \
    | grep "env=${ENVIRONMENT}" \
    | grep -c 'role=server'
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
  local port="${2:-6443}"
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
  </service>
</service-group>
EOF_AVAHI
  sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
  AVAHI_ROLE="${role}"
}

publish_bootstrap_service() {
  log "Advertising bootstrap attempt for ${CLUSTER}/${ENVIRONMENT} via Avahi"
  publish_avahi_service bootstrap 6443
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
  publish_avahi_service server
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
  publish_avahi_service server
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
  publish_avahi_service server
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

if [ -z "${server_host:-}" ]; then
  publish_bootstrap_service
  if [ "${SERVERS_DESIRED}" = "1" ]; then
    install_server_single
  else
    install_server_cluster_init
  fi
else
  servers_now="$(count_servers)"
  if [ "${servers_now}" -lt "${SERVERS_DESIRED}" ]; then
    install_server_join "${server_host}"
  else
    install_agent "${server_host}"
  fi
fi

if [ -f /etc/rancher/k3s/k3s.yaml ]; then
  sudo mkdir -p /root/.kube
  sudo cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
fi

