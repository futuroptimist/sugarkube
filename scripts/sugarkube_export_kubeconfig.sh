#!/usr/bin/env bash
set -euo pipefail

log() {
  local msg="sugarkube-export-kubeconfig: $1"
  if command -v logger >/dev/null 2>&1; then
    logger -t sugarkube-export-kubeconfig "$1" || echo "$msg"
  else
    echo "$msg"
  fi
}

SOURCE_PATH=${SUGARKUBE_KUBECONFIG_SOURCE:-/etc/rancher/k3s/k3s.yaml}
DEST_PATH=${SUGARKUBE_KUBECONFIG_DEST:-/boot/sugarkube-kubeconfig}
LEGACY_DEST=${SUGARKUBE_LEGACY_KUBECONFIG:-/boot/sugarkube/kubeconfig}
WAIT_SECS=${SUGARKUBE_KUBECONFIG_WAIT_SECS:-120}
PORT=${SUGARKUBE_API_PORT:-6443}
ENDPOINT_OVERRIDE=${SUGARKUBE_API_ENDPOINT:-}

escape_for_sed() {
  printf '%s' "$1" | sed -e 's/[#\\&]/\\&/g'
}

wait_for_source() {
  local waited=0
  while [ ! -s "$SOURCE_PATH" ]; do
    if [ "$waited" -ge "$WAIT_SECS" ]; then
      log "source kubeconfig not found at $SOURCE_PATH after ${WAIT_SECS}s"
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
  return 0
}

resolve_endpoint() {
  if [ -n "$ENDPOINT_OVERRIDE" ]; then
    printf '%s\n' "$ENDPOINT_OVERRIDE"
    return 0
  fi
  local host
  if [ -n "${SUGARKUBE_API_HOST:-}" ]; then
    host="$SUGARKUBE_API_HOST"
  else
    host=$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf 'sugarkube')
    if [[ "$host" != *.* ]]; then
      host="${host}.local"
    fi
  fi
  if [[ "$host" =~ ^https?:// ]]; then
    printf '%s\n' "$host"
  else
    printf 'https://%s:%s\n' "$host" "$PORT"
  fi
}

main() {
  if ! wait_for_source; then
    return 1
  fi

  if [ ! -d /boot ]; then
    log "/boot is not mounted; cannot export kubeconfig"
    return 1
  fi

  local endpoint
  endpoint=$(resolve_endpoint)

  umask 077
  local tmp
  tmp=$(mktemp)
  local annotated
  annotated=$(mktemp)
  trap 'rm -f "$tmp" "$annotated"' EXIT

  cp "$SOURCE_PATH" "$tmp"

  if grep -q 'server: https://127.0.0.1:6443' "$tmp"; then
    local escaped_endpoint
    escaped_endpoint=$(escape_for_sed "$endpoint")
    sed -i "s#server: https://127\\.0\\.0\\.1:6443#server: ${escaped_endpoint}#" "$tmp"
  fi

  {
    printf '# Sugarkube remote kubeconfig\n'
    printf '# Generated on %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
    printf '# API endpoint: %s\n\n' "$endpoint"
    cat "$tmp"
  } >"$annotated"

  install -D -m 0600 "$annotated" "$DEST_PATH"
  log "wrote sanitized kubeconfig to $DEST_PATH"

  if [ -d "$(dirname "$LEGACY_DEST")" ] || [ -f "$LEGACY_DEST" ]; then
    install -D -m 0600 "$annotated" "$LEGACY_DEST"
    log "updated legacy kubeconfig at $LEGACY_DEST"
  fi
}

main "$@"
