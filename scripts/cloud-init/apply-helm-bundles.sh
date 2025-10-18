#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR=${CONFIG_DIR:-/etc/sugarkube/helm-bundles.d}
LOG_DIR=${LOG_DIR:-/var/log/sugarkube}
LOG_FILE="${LOG_DIR}/helm-bundles.log"
REPORT_DIR=${REPORT_DIR:-/boot/first-boot-report/helm-bundles}
DEFAULT_WAIT_TIMEOUT=${DEFAULT_WAIT_TIMEOUT:-300}
HELM_BIN=${HELM_BIN:-helm}
KUBECTL_BIN=${KUBECTL_BIN:-kubectl}
DONE_MARKER=${DONE_MARKER:-/var/log/sugarkube/helm-bundles.done}
TIMEOUT_BIN=${TIMEOUT_BIN:-timeout}

mkdir -p "$LOG_DIR"
log() {
  local ts message
  ts=$(date --iso-8601=seconds 2>/dev/null || date)
  message="$1"
  printf '%s %s\n' "$ts" "$message" | tee -a "$LOG_FILE"
}

fail_release() {
  local release_path message
  release_path="$1"
  message="$2"
  printf '# Status: failed\n# Message: %s\n' "$message" >"${release_path}.failed"
  log "$message"
}

if ! command -v "$HELM_BIN" >/dev/null 2>&1; then
  log "helm binary not available; cannot apply bundles"
  exit 1
fi

if ! command -v "$KUBECTL_BIN" >/dev/null 2>&1; then
  log "kubectl binary not available; cannot run health checks"
  exit 1
fi

if command -v "$TIMEOUT_BIN" >/dev/null 2>&1; then
  HAVE_TIMEOUT=1
else
  HAVE_TIMEOUT=0
  log "timeout binary not available; custom health checks will run without deadlines"
fi

if [ ! -d "$CONFIG_DIR" ]; then
  log "Bundle directory $CONFIG_DIR missing; nothing to apply"
  exit 0
fi

shopt -s nullglob
bundle_files=("$CONFIG_DIR"/*.env)
shopt -u nullglob

if [ ${#bundle_files[@]} -eq 0 ]; then
  log "No Helm bundle definitions found in $CONFIG_DIR"
  exit 0
fi

if [ -d /boot ]; then
  mkdir -p "$REPORT_DIR"
else
  log "/boot not mounted; bundle reports will be logged only to $LOG_FILE"
fi

status=0

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

for bundle_file in "${bundle_files[@]}"; do
  unset RELEASE CHART NAMESPACE VERSION VALUES_FILE VALUES_FILES WAIT_TARGETS WAIT_TIMEOUT EXTRA_HELM_ARGS HEALTHCHECK_CMD HEALTHCHECK_TIMEOUT NOTES
  set +u
  # shellcheck disable=SC1090
  source "$bundle_file"
  set -u

  release=${RELEASE:-}
  chart=${CHART:-}
  namespace=${NAMESPACE:-default}
  version=${VERSION:-}
  values_file=${VALUES_FILE:-}
  values_files=${VALUES_FILES:-}
  wait_targets=${WAIT_TARGETS:-}
  wait_timeout=${WAIT_TIMEOUT:-$DEFAULT_WAIT_TIMEOUT}
  extra_args=${EXTRA_HELM_ARGS:-}
  healthcheck_cmd=${HEALTHCHECK_CMD:-}
  healthcheck_timeout=${HEALTHCHECK_TIMEOUT:-$wait_timeout}
  notes=${NOTES:-}

  bundle_name=$(basename "$bundle_file")
  bundle_slug=${bundle_name%%.env}

  if [ -z "$release" ] || [ -z "$chart" ]; then
    log "Skipping $bundle_name because RELEASE or CHART is missing"
    status=1
    if [ -d "$REPORT_DIR" ]; then
      fail_release "$REPORT_DIR/$bundle_slug" "Missing RELEASE or CHART values"
    fi
    continue
  fi

  report_file="$LOG_DIR/${bundle_slug}.log"
  if [ -d "$REPORT_DIR" ]; then
    report_file="$REPORT_DIR/${bundle_slug}.log"
    : >"$REPORT_DIR/${bundle_slug}.log"
    rm -f "$REPORT_DIR/${bundle_slug}.failed" "$REPORT_DIR/${bundle_slug}.status"
  else
    : >"$report_file"
  fi

  log "Applying Helm release $release from $chart into namespace $namespace"

  {
    printf '# Sugarkube Helm bundle\n'
    printf '# Release: %s\n' "$release"
    printf '# Chart: %s\n' "$chart"
    printf '# Namespace: %s\n' "$namespace"
    if [ -n "$version" ]; then
      printf '# Version: %s\n' "$version"
    fi
    if [ -n "$notes" ]; then
      printf '# Notes: %s\n' "$notes"
    fi
    printf '# Started: %s\n\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
  } >"$report_file"

  cmd=("$HELM_BIN" upgrade --install "$release" "$chart" --namespace "$namespace" --create-namespace --atomic)
  if [ -n "$version" ]; then
    cmd+=(--version "$version")
  fi

  add_values_file() {
    local file
    file="$1"
    if [ -z "$file" ]; then
      return
    fi
    if [ ! -f "$file" ]; then
      log "Values file $file for $release missing"
      if [ -d "$REPORT_DIR" ]; then
        fail_release "$REPORT_DIR/$bundle_slug" "Values file missing: $file"
      fi
      status=1
      return 1
    fi
    cmd+=(-f "$file")
  }

  if [ -n "$values_file" ]; then
    if ! add_values_file "$values_file"; then
      continue
    fi
  fi

  if [ -n "$values_files" ]; then
    IFS=',' read -r -a values_array <<<"$values_files"
    for raw in "${values_array[@]}"; do
      trimmed=$(trim "$raw")
      if [ -n "$trimmed" ]; then
        if ! add_values_file "$trimmed"; then
          continue 2
        fi
      fi
    done
  fi

  if [ -n "$extra_args" ]; then
    # shellcheck disable=SC2206
    extra_array=($extra_args)
    cmd+=("${extra_array[@]}")
  fi

  printf '$ %s\n' "$(printf '%q ' "${cmd[@]}")" >>"$report_file"
  if ! "${cmd[@]}" >>"$report_file" 2>&1; then
    log "Helm upgrade failed for release $release"
    if [ -d "$REPORT_DIR" ]; then
      fail_release "$REPORT_DIR/$bundle_slug" "helm upgrade failed"
    fi
    status=1
    continue
  fi

  if [ -n "$wait_targets" ]; then
    IFS=',' read -r -a targets <<<"$wait_targets"
    for raw_target in "${targets[@]}"; do
      trimmed_target=$(trim "$raw_target")
      if [ -z "$trimmed_target" ]; then
        continue
      fi
      target_ns="$namespace"
      resource="$trimmed_target"
      if [[ "$trimmed_target" == *:* ]]; then
        target_ns=${trimmed_target%%:*}
        resource=${trimmed_target#*:}
      fi
      resource=$(trim "$resource")
      printf '\n# Waiting for %s in namespace %s (timeout=%ss)\n' "$resource" "$target_ns" "$wait_timeout" >>"$report_file"
      if ! "$KUBECTL_BIN" rollout status "$resource" --namespace "$target_ns" --timeout "${wait_timeout}s" >>"$report_file" 2>&1; then
        log "Health check failed for $release on $resource"
        if [ -d "$REPORT_DIR" ]; then
          fail_release "$REPORT_DIR/$bundle_slug" "rollout status failed for $resource"
        fi
        status=1
        continue 2
      fi
    done
  fi

  if [ -n "$healthcheck_cmd" ]; then
    printf '\n$ %s\n' "$healthcheck_cmd" >>"$report_file"
    if [ "$HAVE_TIMEOUT" -eq 1 ]; then
      if ! "$TIMEOUT_BIN" "${healthcheck_timeout}s" bash -o pipefail -c "$healthcheck_cmd" >>"$report_file" 2>&1; then
        log "Custom health check failed for release $release"
        if [ -d "$REPORT_DIR" ]; then
          fail_release "$REPORT_DIR/$bundle_slug" "custom health check failed"
        fi
        status=1
        continue
      fi
    else
      if ! bash -o pipefail -c "$healthcheck_cmd" >>"$report_file" 2>&1; then
        log "Custom health check failed for release $release"
        if [ -d "$REPORT_DIR" ]; then
          fail_release "$REPORT_DIR/$bundle_slug" "custom health check failed"
        fi
        status=1
        continue
      fi
    fi
  fi

  printf '\n# Completed: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)" >>"$report_file"
  if [ -d "$REPORT_DIR" ]; then
    printf '# Status: success\n' >"$REPORT_DIR/${bundle_slug}.status"
  fi
  log "Helm release $release applied successfully"

done

if [ "$status" -eq 0 ]; then
  printf 'status=success\ncompleted=%s\n' "$(date --iso-8601=seconds 2>/dev/null || date)" >"$DONE_MARKER" 2>/dev/null || true
  log "All Helm bundles applied successfully"
else
  rm -f "$DONE_MARKER" 2>/dev/null || true
  log "One or more Helm bundles failed"
fi

exit "$status"
