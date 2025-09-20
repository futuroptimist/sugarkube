#!/usr/bin/env bash
set -euo pipefail

SOURCE_KUBECONFIG="${K3S_KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
TARGET_KUBECONFIG="${KUBECONFIG_EXPORT_PATH:-/boot/sugarkube-kubeconfig}"
LOG_DIR="${EXPORT_LOG_DIR:-/var/log/sugarkube}"
LOG_PATH="${LOG_DIR}/export-kubeconfig.log"
COLON=$'\072'

mkdir -p "${LOG_DIR}" "$(dirname "${TARGET_KUBECONFIG}")"

timestamp() {
  date --iso-8601=seconds 2>/dev/null || date
}

log() {
  local message
  message="[$(timestamp)] $*"
  echo "${message}"
  echo "${message}" >>"${LOG_PATH}"
}

log "Starting kubeconfig export from ${SOURCE_KUBECONFIG} to ${TARGET_KUBECONFIG}" \
  || true

if [ ! -f "${SOURCE_KUBECONFIG}" ]; then
  log "Source kubeconfig missing; skipping export"
  exit 0
fi

tmpfile="$(mktemp)"
cleanup() {
  rm -f "${tmpfile}"
}
trap cleanup EXIT

cp "${SOURCE_KUBECONFIG}" "${tmpfile}"

sed -i -E "/^[[:space:]]*token[[:space:]]*${COLON}/d" "${tmpfile}" || true
sed -i -E 's/(client-certificate-data:).*/\1 <redacted>/' "${tmpfile}" || true
sed -i -E 's/(client-key-data:).*/\1 <redacted>/' "${tmpfile}" || true
sed -i -E 's/(certificate-authority-data:).*/\1 <redacted - available on the node>/' "${tmpfile}" || true

cat <<EONOTES >>"${tmpfile}"

# Sugarkube kubeconfig export
# - Re-add a `token` entry with the contents of
#   /var/lib/rancher/k3s/server/node-token before use.
# - Copy this file to ~/.kube/config (or set KUBECONFIG) on your workstation.
# - Adjust the "server" field if you expose the API via a tunnel or LAN IP.
EONOTES

install -D -m 0644 "${tmpfile}" "${TARGET_KUBECONFIG}"
log "Wrote sanitized kubeconfig to ${TARGET_KUBECONFIG}"
