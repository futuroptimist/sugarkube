#!/usr/bin/env bash
set -euo pipefail

SRC="/var/lib/rancher/k3s/server/node-token"
DEST="/boot/sugarkube-node-token"
LOG_DIR="/var/log/sugarkube"
LOG_FILE="${LOG_DIR}/node-token-export.log"
WAIT_SECONDS=${WAIT_SECONDS:-120}
SLEEP_INTERVAL=${SLEEP_INTERVAL:-3}

mkdir -p "$LOG_DIR" >/dev/null 2>&1 || true
log() {
  local ts
  ts=$(date --iso-8601=seconds 2>/dev/null || date)
  printf '%s %s\n' "$ts" "$1" >>"$LOG_FILE" 2>/dev/null || true
}

if [ ! -d /boot ]; then
  log "/boot not mounted; skipping node token export"
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
  log "k3s node token missing after ${WAIT_SECONDS}s; wrote placeholder"
  {
    printf '# Sugarkube k3s node token export (pending)\n'
    printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf '# %s was not found. Run this script again later.\n' "$SRC"
  } >"$DEST" 2>/dev/null || true
  chmod 600 "$DEST" 2>/dev/null || true
  exit 0
fi

join_secret=$(tr -d '\n' < "$SRC" 2>/dev/null || true)

if [ -z "$join_secret" ]; then
  log "k3s node token empty; aborting export"
  exit 0
fi

{
  printf '# Sugarkube k3s node token export\n'
  printf '# Generated: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
  printf '# Token grants cluster join permissions. Handle with care.\n'
  printf '# Retrieve a fresh copy anytime with:\n'
  printf '#   sudo cat %s > /boot/sugarkube-node-token\n\n' "$SRC"
  printf '%s=%s\n' "NODE_TOKEN" "$join_secret"
} >"$DEST"

if ! sync "$DEST" 2>/dev/null; then
  sync
fi

if ! chmod 600 "$DEST" 2>/dev/null; then
  :
fi

log "Wrote k3s node token to $DEST"
