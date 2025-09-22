#!/usr/bin/env bash
set -euo pipefail

SRC="/etc/rancher/k3s/k3s.yaml"
DEST="/boot/sugarkube-kubeconfig"
DEST_FULL="/boot/sugarkube-kubeconfig-full"
NODE_TOKEN_SRC="/var/lib/rancher/k3s/server/node-token"
NODE_TOKEN_DEST="/boot/sugarkube-node-token"
LOG_DIR="/var/log/sugarkube"
LOG_FILE="${LOG_DIR}/kubeconfig-export.log"
WAIT_SECONDS=${WAIT_SECONDS:-120}
SLEEP_INTERVAL=${SLEEP_INTERVAL:-3}
CLIENT_CERT_PATTERN='client-certificate-data[[:space:]]*:'
CLIENT_KEY_PATTERN='client-key-data[[:space:]]*:'
TOKEN_PATTERN='token[[:space:]]*:'

mkdir -p "$LOG_DIR" >/dev/null 2>&1 || true
log() {
  local ts
  ts=$(date --iso-8601=seconds 2>/dev/null || date)
  printf '%s %s\n' "$ts" "$1" >>"$LOG_FILE" 2>/dev/null || true
}

if [ ! -d /boot ]; then
  log "/boot not mounted; skipping kubeconfig export"
  exit 0
fi

attempts=$(( WAIT_SECONDS / SLEEP_INTERVAL ))
if [ $attempts -lt 1 ]; then
  attempts=1
fi

for ((i=0; i<attempts; i++)); do
  if [ -s "$SRC" ]; then
    break
  fi
  sleep "$SLEEP_INTERVAL"
done

if [ ! -s "$SRC" ]; then
  log "k3s kubeconfig missing after ${WAIT_SECONDS}s; wrote placeholder"
  {
    printf '# Sugarkube kubeconfig export (pending)\n'
    printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf '# k3s has not yet created %s. Run this script again later.\n' "$SRC"
  } >"$DEST" 2>/dev/null || true
  {
    printf '# Sugarkube kubeconfig export (pending)\n'
    printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf '# A full kubeconfig will be written once %s is present.\n' "$SRC"
  } >"$DEST_FULL" 2>/dev/null || true
  {
    printf '# Sugarkube node token export (pending)\n'
    printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf '# Node token not yet present at %s.\n' "$NODE_TOKEN_SRC"
    printf '# Once k3s finishes bootstrapping the server role, rerun:\n'
    printf '#   sudo cp %s %s\n' "$NODE_TOKEN_SRC" "$NODE_TOKEN_DEST"
  } >"$NODE_TOKEN_DEST" 2>/dev/null || true
  chmod 600 "$DEST" "$DEST_FULL" "$NODE_TOKEN_DEST" 2>/dev/null || true
  log "k3s kubeconfig and node token missing; wrote placeholders to /boot"
  exit 0
fi

tmp_raw=$(mktemp)
tmp_clean=$(mktemp)
trap 'rm -f "$tmp_raw" "$tmp_clean"' EXIT

if command -v k3s >/dev/null 2>&1; then
  if ! k3s kubectl config view --raw >"$tmp_raw" 2>/dev/null; then
    cp "$SRC" "$tmp_raw"
  fi
else
  cp "$SRC" "$tmp_raw"
fi

# Strip sensitive credentials but keep cluster metadata intact.
sed -E \
  -e "s/(${CLIENT_CERT_PATTERN}).*/\\1 REDACTED/" \
  -e "s/(${CLIENT_KEY_PATTERN}).*/\\1 REDACTED/" \
  -e "s/(${TOKEN_PATTERN}).*/\\1 REDACTED/" \
  "$tmp_raw" >"$tmp_clean"

{
  printf '# Sugarkube kubeconfig export (sanitized)\n'
  printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
  printf '# Secrets such as client certificates, keys, and tokens are redacted.\n'
  printf '# Retrieve a full admin config with:\n'
  printf '#   sudo k3s kubectl config view --raw > ~/sugarkube-kubeconfig-full\n'
  printf '# Merge your own credentials before using this file with kubectl.\n\n'
  cat "$tmp_clean"
} >"$DEST"

{
  printf '# Sugarkube kubeconfig export (full)\n'
  printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
  printf '# Contains full admin credentials. Protect this file.\n'
  printf '# Retrieve a fresh copy anytime with:\n'
  printf '#   sudo k3s kubectl config view --raw > /boot/sugarkube-kubeconfig-full\n\n'
  cat "$tmp_raw"
} >"$DEST_FULL"

if ! sync "$DEST" 2>/dev/null; then
  sync
fi

if ! sync "$DEST_FULL" 2>/dev/null; then
  sync
fi

if ! chmod 600 "$DEST" "$DEST_FULL" 2>/dev/null; then
  :
fi

if [ -s "$NODE_TOKEN_SRC" ]; then
  if ! cp "$NODE_TOKEN_SRC" "$NODE_TOKEN_DEST" 2>/dev/null; then
    log "Failed to copy node token from $NODE_TOKEN_SRC"
  else
    if ! sync "$NODE_TOKEN_DEST" 2>/dev/null; then
      sync
    fi
    if ! chmod 600 "$NODE_TOKEN_DEST" 2>/dev/null; then
      :
    fi
    log "Wrote k3s node token to $NODE_TOKEN_DEST"
  fi
else
  {
    printf '# Sugarkube node token export (pending)\n'
    printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf '# Node token not yet present at %s.\n' "$NODE_TOKEN_SRC"
    printf '# Once k3s finishes bootstrapping the server role, rerun:\n'
    printf '#   sudo cp %s %s\n' "$NODE_TOKEN_SRC" "$NODE_TOKEN_DEST"
  } >"$NODE_TOKEN_DEST" 2>/dev/null || true
  if ! chmod 600 "$NODE_TOKEN_DEST" 2>/dev/null; then
    :
  fi
  log "Node token missing at $NODE_TOKEN_SRC; wrote placeholder to $NODE_TOKEN_DEST"
fi

log "Wrote sanitized kubeconfig to $DEST"
log "Wrote full kubeconfig to $DEST_FULL"
