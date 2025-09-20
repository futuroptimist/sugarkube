#!/usr/bin/env bash
set -euo pipefail

log_dir="/var/log/sugarkube"
log_file="${log_dir}/k3s-ready.log"
mkdir -p "${log_dir}"

log() {
  local ts
  ts=$(date --iso-8601=seconds 2>/dev/null || date)
  printf '%s %s\n' "$ts" "$1" | tee -a "$log_file"
}

select_kubectl() {
  if command -v kubectl >/dev/null 2>&1; then
    echo "kubectl"
    return 0
  fi
  if command -v k3s >/dev/null 2>&1; then
    echo "k3s kubectl"
    return 0
  fi
  return 1
}

kubectl_cmd=$(select_kubectl)
if [[ -z "${kubectl_cmd:-}" ]]; then
  log "kubectl not found; cannot verify k3s readiness"
  exit 1
fi

# shellcheck disable=SC2206 # intentional word splitting into array
kubectl_arr=($kubectl_cmd)

ready_timeout="${K3S_READY_TIMEOUT:-900}"
retry_interval="${K3S_READY_RETRY:-15}"

declare -i elapsed=0
log "Waiting for kubernetes node readiness (timeout: ${ready_timeout}s)"

while (( elapsed < ready_timeout )); do
  if "${kubectl_arr[@]}" wait --for=condition=Ready node --all \
    --timeout="${retry_interval}s" >/tmp/k3s-ready.out 2>/tmp/k3s-ready.err; then
    log "k3s reported Ready nodes"
    cat /tmp/k3s-ready.out >>"$log_file" 2>/dev/null || true
    rm -f /tmp/k3s-ready.out /tmp/k3s-ready.err
    exit 0
  fi

  if grep -qi "no matching resources" /tmp/k3s-ready.err 2>/dev/null; then
    log "kubectl reports no nodes yet; retrying"
  else
    log "kubectl wait failed: $(tr '\n' ' ' </tmp/k3s-ready.err)"
  fi

  sleep "$retry_interval"
  elapsed=$((elapsed + retry_interval))
done

log "Timed out waiting for k3s nodes to become Ready after ${ready_timeout}s"
exit 2
