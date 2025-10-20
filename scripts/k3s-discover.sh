#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVERS_DESIRED="${SUGARKUBE_SERVERS:-1}"

case "${ENVIRONMENT}" in
  dev)
    TOKEN="${SUGARKUBE_TOKEN_DEV:-${SUGARKUBE_TOKEN:-}}"
    ;;
  int)
    TOKEN="${SUGARKUBE_TOKEN_INT:-${SUGARKUBE_TOKEN:-}}"
    ;;
  prod)
    TOKEN="${SUGARKUBE_TOKEN_PROD:-${SUGARKUBE_TOKEN:-}}"
    ;;
  *)
    TOKEN="${SUGARKUBE_TOKEN:-}"
    ;;
esac

if [ -z "${TOKEN:-}" ]; then
  echo "SUGARKUBE_TOKEN (or per-env variant) required" >&2
  exit 1
fi

HN="$(hostname -s)"
MDNS_HOST="${HN}.local"

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

count_servers() {
  avahi-browse -rt _https._tcp 2>/dev/null \
    | awk -F';' -v cluster="${CLUSTER}" -v env="${ENVIRONMENT}" '
        /;_https._tcp;/ {
          port = $10
          txt = $0
          if (port == "6443" &&
              index(txt, "k3s=1") &&
              index(txt, "cluster=" cluster) &&
              index(txt, "env=" env) &&
              index(txt, "role=server")) {
            count++
          }
        }
        END { print count + 0 }
      '
}

publish_avahi_service() {
  sudo tee /etc/avahi/services/k3s-https.service >/dev/null <<EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">k3s API ${CLUSTER}/${ENVIRONMENT} on %h</name>
  <service>
    <type>_https._tcp</type>
    <port>6443</port>
    <txt-record>k3s=1</txt-record>
    <txt-record>cluster=${CLUSTER}</txt-record>
    <txt-record>env=${ENVIRONMENT}</txt-record>
    <txt-record>role=server</txt-record>
  </service>
</service-group>
EOF
  sudo systemctl reload avahi-daemon || sudo systemctl restart avahi-daemon
}

install_server_single() {
  log "Bootstrapping single-server (SQLite) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST}"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_TOKEN="${TOKEN}" sh -s - server \
      --tls-san "${MDNS_HOST}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  publish_avahi_service
}

install_server_cluster_init() {
  log "Bootstrapping first HA server (embedded etcd) ${CLUSTER}/${ENVIRONMENT} on ${MDNS_HOST}"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_TOKEN="${TOKEN}" sh -s - server \
      --cluster-init \
      --tls-san "${MDNS_HOST}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  publish_avahi_service
}

install_server_join() {
  local server="$1"
  log "Joining HA server via https://${server}:6443 (target=${SERVERS_DESIRED})"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_TOKEN="${TOKEN}" sh -s - server \
      --server "https://${server}:6443" \
      --tls-san "${server}" \
      --tls-san "${MDNS_HOST}" \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}" \
      --node-taint "node-role.kubernetes.io/control-plane=true:NoSchedule"
  publish_avahi_service
}

install_agent() {
  local server="$1"
  log "Joining as agent via https://${server}:6443"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_CHANNEL="${K3S_CHANNEL:-stable}" \
      K3S_URL="https://${server}:6443" \
      K3S_TOKEN="${TOKEN}" sh -s - agent \
      --node-label "sugarkube.cluster=${CLUSTER}" \
      --node-label "sugarkube.env=${ENVIRONMENT}"
}

log "Discovering existing k3s API for ${CLUSTER}/${ENVIRONMENT} via mDNS..."
server_host="$(discover_server_host || true)"
if [ -z "${server_host:-}" ]; then
  sleep $((RANDOM % 20 + 5))
  server_host="$(discover_server_host || true)"
fi

if [ -z "${server_host:-}" ]; then
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
