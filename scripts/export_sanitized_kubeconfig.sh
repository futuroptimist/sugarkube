#!/usr/bin/env bash
# Export a sanitized kubeconfig to the boot partition for offline retrieval.
set -euo pipefail

SRC_PATH=${SUGARKUBE_KUBECONFIG_SOURCE:-/etc/rancher/k3s/k3s.yaml}
DEST_DIR=${SUGARKUBE_KUBECONFIG_DEST_DIR:-/boot/sugarkube}
DEST_PATH=${SUGARKUBE_KUBECONFIG_PATH:-${DEST_DIR}/kubeconfig}
SECONDARY_PATH=${SUGARKUBE_KUBECONFIG_SECONDARY:-/boot/sugarkube-kubeconfig}
LOG_PATH=${SUGARKUBE_KUBECONFIG_LOG:-/var/log/sugarkube/kubeconfig-export.log}
WAIT_TIMEOUT=${SUGARKUBE_KUBECONFIG_TIMEOUT:-300}
POLL_INTERVAL=${SUGARKUBE_KUBECONFIG_POLL_INTERVAL:-5}

umask 077

log() {
  local timestamp
  timestamp="$(date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z')"
  local message="[sugarkube-export-kubeconfig] $*"
  printf '%s %s\n' "$timestamp" "$message"
  mkdir -p "$(dirname "$LOG_PATH")"
  printf '%s %s\n' "$timestamp" "$message" >>"$LOG_PATH"
}

wait_for_source() {
  local waited=0
  while [ ! -f "$SRC_PATH" ]; do
    if [ "$waited" -ge "$WAIT_TIMEOUT" ]; then
      log "Timed out waiting for kubeconfig at $SRC_PATH"
      return 1
    fi
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
  done
  return 0
}

select_current_server() {
  awk '
    $1 == "clusters:" { in_cluster = 1; next }
    $1 == "contexts:" { exit }
    in_cluster && $1 == "server:" { print $2; exit }
  ' "$1"
}

resolve_server_override() {
  local override="${SUGARKUBE_KUBECONFIG_SERVER:-}"
  if [ -n "$override" ]; then
    printf '%s' "$override"
    return 0
  fi

  local current_server
  current_server="$(select_current_server "$1" || true)"
  case "$current_server" in
    https://127.0.0.1:6443|https://localhost:6443|'')
      ;;
    *)
      printf '%s' "$override"
      return 0
      ;;
  esac

  local ip
  ip="$(
    hostname -I 2>/dev/null | tr ' ' '\n' |
      grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' |
      grep -v '^127\.' | head -n1 || true
  )"
  if [ -n "$ip" ]; then
    printf 'https://%s:6443' "$ip"
    return 0
  fi

  local host
  host="$(hostname 2>/dev/null || true)"
  if [ -n "$host" ]; then
    printf 'https://%s.local:6443' "$host"
    return 0
  fi

  printf ''
  return 0
}

update_server_endpoint() {
  local file="$1"
  local server="$2"
  if [ -z "$server" ]; then
    return 0
  fi

  SERVER_URL="$server" perl -0pi -e '
    next unless $ENV{SERVER_URL};
    my $updated;
    s{
      (clusters:\s*\n(?:\s+.+\n)*?\s+server:\s*)
      (\S+)
    }{
      $updated = 1;
      $1 . $ENV{SERVER_URL}
    }ex;
    s/(server:\s*)\S+/$1$ENV{SERVER_URL}/ if !$updated;
  ' "$file"
}

flatten_config() {
  local source="$1"
  local destination="$2"
  # The stock k3s config only defines a single context; rewrite it verbatim.
  # Preserve ordering while stripping trailing spaces.
  awk '{ sub(/[[:space:]]+$/, ""); print }' "$source" >"$destination"
}

write_outputs() {
  local temp="$1"

  mkdir -p "$DEST_DIR"
  chmod 750 "$DEST_DIR" 2>/dev/null || true
  cp "$temp" "$DEST_PATH"
  chmod 600 "$DEST_PATH" 2>/dev/null || true
  log "Wrote sanitized kubeconfig to $DEST_PATH"

  if [ -n "$SECONDARY_PATH" ] && [ "$SECONDARY_PATH" != "$DEST_PATH" ]; then
    local secondary_dir
    secondary_dir="$(dirname "$SECONDARY_PATH")"
    mkdir -p "$secondary_dir"
    chmod 750 "$secondary_dir" 2>/dev/null || true
    cp "$temp" "$SECONDARY_PATH"
    chmod 600 "$SECONDARY_PATH" 2>/dev/null || true
    log "Mirrored kubeconfig to $SECONDARY_PATH"
  fi
}

main() {
  if ! wait_for_source; then
    return 1
  fi

  local tmp tmp_filtered
  tmp="$(mktemp)"
  tmp_filtered="$(mktemp)"
  trap 'rm -f "$tmp" "$tmp_filtered"' EXIT

  cp "$SRC_PATH" "$tmp"
  chmod 600 "$tmp" 2>/dev/null || true

  local server_override
  server_override="$(resolve_server_override "$tmp" || true)"
  update_server_endpoint "$tmp" "$server_override"
  if [ -n "$server_override" ]; then
    log "Updated cluster server endpoint to $server_override"
  fi

  flatten_config "$tmp" "$tmp_filtered"
  mv "$tmp_filtered" "$tmp"

  write_outputs "$tmp"
  log "Kubeconfig export completed"
  return 0
}

main "$@"
