#!/usr/bin/env bash
set -euo pipefail

warn() {
  printf 'warning: %s\n' "$1" >&2
}

JSON=false
REPORT_PATH=""
ENABLE_LOG=true
SKIP_COMPOSE=${SKIP_COMPOSE:-false}
FULL=false
DEFAULT_REPORT="/boot/first-boot-report.txt"
MIGRATION_LOG=${MIGRATION_LOG:-/var/log/sugarkube/migrations.log}
TOKEN_PLACE_HEALTH_URL=${TOKEN_PLACE_HEALTH_URL:-http://127.0.0.1:5000/}
TOKEN_PLACE_HEALTH_INSECURE=${TOKEN_PLACE_HEALTH_INSECURE:-false}
DSPACE_HEALTH_URL=${DSPACE_HEALTH_URL:-http://127.0.0.1:3000/}
DSPACE_HEALTH_INSECURE=${DSPACE_HEALTH_INSECURE:-false}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-5}

set_skip_compose() {
  local value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1|true|yes|on)
      SKIP_COMPOSE=true
      ;;
    0|false|no|off)
      SKIP_COMPOSE=false
      ;;
    *)
      echo "Invalid value for --skip-compose: $1" >&2
      exit 1
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      JSON=true
      ;;
    --log)
      if [[ $# -lt 2 ]]; then
        echo "--log requires a path" >&2
        exit 1
      fi
      REPORT_PATH="$2"
      shift
      ;;
    --log=*)
      REPORT_PATH="${1#*=}"
      ;;
    --skip-compose)
      if [[ $# -ge 2 && "$2" != --* ]]; then
        set_skip_compose "$2"
        shift
      else
        SKIP_COMPOSE=true
      fi
      ;;
    --skip-compose=*)
      set_skip_compose "${1#*=}"
      ;;
    --full)
      FULL=true
      JSON=true
      ;;
    --no-log)
      ENABLE_LOG=false
      ;;
    --help)
      cat <<'EOF'
Usage: pi_node_verifier.sh [--json] [--log PATH] [--no-log] [--skip-compose[=BOOL]] [--full]

Options:
  --json       Emit machine-readable JSON results.
  --log PATH   Append a Markdown summary to PATH.
               Defaults to /boot/first-boot-report.txt when writable.
  --no-log     Disable report generation entirely.
  --full       Print text output and a JSON summary (implies --json).
  --skip-compose[=BOOL]
               Skip the projects-compose.service health check. Defaults to false.
  --help       Show this message.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--json] [--log PATH] [--no-log]" >&2
      exit 1
      ;;
  esac
  shift
done

if $ENABLE_LOG && [[ -z "$REPORT_PATH" ]] && [[ -d /boot ]]; then
  if [[ -w /boot ]]; then
    REPORT_PATH="$DEFAULT_REPORT"
  else
    warn "/boot exists but is not writable; skipping default report path"
  fi
fi

json_parts=()
check_names=()
check_statuses=()
print_result() {
  local name="$1"
  local status="$2"
  if ! $JSON || $FULL; then
    printf '%s: %s\n' "$name" "$status"
  fi
  json_parts+=('{"name":"'"$name"'","status":"'"$status"'"}')
  check_names+=("$name")
  check_statuses+=("$status")
}

append_report() {
  local dest="$1"
  local required_tools=(mktemp date hostname uname mkdir cat sed cut tr)
  local missing=false
  for tool in "${required_tools[@]}"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      missing=true
      break
    fi
  done
  if $missing; then
    return
  fi

  local timestamp
  timestamp=$(date --iso-8601=seconds 2>/dev/null || date)
  local host
  host=$(hostname 2>/dev/null || echo "unknown")
  local kernel
  kernel=$(uname -sr 2>/dev/null || echo "unknown")
  local model=""
  if [[ -r /proc/device-tree/model ]]; then
    model=$(tr -d '\0' </proc/device-tree/model)
  elif command -v hostnamectl >/dev/null 2>&1; then
    model=$(hostnamectl 2>/dev/null || true)
    model=$(printf '%s\n' "$model" | head -n 1 | cut -d':' -f2- | sed 's/^ *//')
  fi

  local tmp
  tmp=$(mktemp)
  {
    printf '## %s\n\n' "$timestamp"
    printf '* Hostname: `%s`\n' "$host"
    printf '* Kernel: `%s`\n' "$kernel"
    if [[ -n "$model" ]]; then
      printf '* Hardware: `%s`\n' "$model"
    fi
    printf '\n### Verifier Checks\n\n'
    printf '| Check | Status |\n'
    printf '| --- | --- |\n'
    local idx=0
    local total=${#check_names[@]}
    while [[ $idx -lt $total ]]; do
      printf '| %s | %s |\n' "${check_names[$idx]}" "${check_statuses[$idx]}"
      idx=$((idx + 1))
    done

    printf '\n### Migration Steps\n\n'
    if [[ -f "$MIGRATION_LOG" && -s "$MIGRATION_LOG" ]]; then
      while IFS= read -r line; do
        printf '* %s\n' "$line"
      done <"$MIGRATION_LOG"
    else
      printf '_No migration steps recorded yet._\n'
    fi

    if command -v cloud-init >/dev/null 2>&1; then
      printf '\n### cloud-init Status\n\n'
      if ! cloud-init status --long 2>/dev/null | sed 's/^/    /'; then
        printf '    (cloud-init status unavailable)\n'
      fi
    fi

    if command -v lsblk >/dev/null 2>&1; then
      printf '\n### Storage Snapshot\n\n'
      if ! lsblk -o NAME,SIZE,MODEL,SERIAL 2>/dev/null | sed 's/^/    /'; then
        printf '    (lsblk output unavailable)\n'
      fi
    fi

    printf '\n'
  } >"$tmp"

  mkdir -p "$(dirname "$dest")" >/dev/null 2>&1 || true
  if cat "$tmp" >>"$dest"; then
    :
  else
    warn "Failed to append verifier report to $dest"
  fi
  rm -f "$tmp"
}

find_kubeconfig() {
  local candidates=()
  if [[ -n ${KUBECONFIG:-} ]]; then
    local cfg
    local IFS=':'
    read -ra candidates <<<"$KUBECONFIG"
    for cfg in "${candidates[@]}"; do
      if [[ -r "$cfg" ]]; then
        printf '%s' "$cfg"
        return 0
      fi
    done
  fi

  candidates=(
    /etc/rancher/k3s/k3s.yaml
    /root/.kube/config
    /home/pi/.kube/config
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -r "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

run_kubectl() {
  local kubeconfig="$1"
  shift
  if command -v kubectl >/dev/null 2>&1; then
    kubectl --kubeconfig "$kubeconfig" "$@"
  elif command -v k3s >/dev/null 2>&1; then
    k3s kubectl --kubeconfig "$kubeconfig" "$@"
  else
    return 127
  fi
}

http_health_check() {
  local name="$1"
  local url="$2"
  local insecure="$3"
  local timeout="$4"

  local cmd=("curl" "--silent" "--show-error" "--max-time" "$timeout" "--fail")
  local alt_cmd=("wget" "-qO-" "--timeout=$timeout")

  if command -v curl >/dev/null 2>&1; then
    if [[ "$insecure" == "true" ]]; then
      cmd+=('-k')
    fi
    if "${cmd[@]}" "$url" >/dev/null 2>&1; then
      print_result "$name" "pass"
    else
      print_result "$name" "fail"
    fi
  elif command -v wget >/dev/null 2>&1; then
    if [[ "$insecure" == "true" ]]; then
      alt_cmd+=("--no-check-certificate")
    fi
    if "${alt_cmd[@]}" "$url" >/dev/null 2>&1; then
      print_result "$name" "pass"
    else
      print_result "$name" "fail"
    fi
  else
    print_result "$name" "skip"
  fi
}

check_k3s_node_ready() {
  local kubeconfig
  if ! kubeconfig=$(find_kubeconfig); then
    print_result "k3s_node_ready" "skip"
    return
  fi

  local output
  if ! output=$(run_kubectl "$kubeconfig" get nodes --no-headers 2>/dev/null); then
    local status=$?
    if [[ $status -eq 127 ]]; then
      print_result "k3s_node_ready" "skip"
    else
      print_result "k3s_node_ready" "fail"
    fi
    return
  fi

  local ready=1
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local -a fields
    read -r -a fields <<<"$line"
    local status="${fields[1]:-}"
    if [[ -n "$status" && "$status" == Ready* ]]; then
      ready=0
      break
    fi
  done <<<"$output"

  if [[ $ready -eq 0 ]]; then
    print_result "k3s_node_ready" "pass"
  else
    print_result "k3s_node_ready" "fail"
  fi
}

check_projects_compose_active() {
  if $SKIP_COMPOSE; then
    print_result "projects_compose_active" "skip"
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    print_result "projects_compose_active" "skip"
    return
  fi

  local output
  if output=$(systemctl is-active projects-compose.service 2>&1); then
    print_result "projects_compose_active" "pass"
    return
  fi

  local status=$?
  if [[ $status -eq 3 || $status -eq 4 ]]; then
    print_result "projects_compose_active" "fail"
  elif [[ "$output" == *"System has not been booted"* ]] || \
       [[ "$output" == *"Failed to connect to bus"* ]]; then
    print_result "projects_compose_active" "skip"
  else
    print_result "projects_compose_active" "fail"
  fi
}

# cgroup memory
if [[ -f /sys/fs/cgroup/cgroup.controllers ]] && \
   grep -qw 'cgroup_memory=1' /proc/cmdline && \
   grep -qw 'cgroup_enable=memory' /proc/cmdline; then
  print_result "cgroup_memory" "pass"
else
  print_result "cgroup_memory" "fail"
fi

# cloud-init status
if command -v cloud-init >/dev/null 2>&1; then
  if cloud-init status --wait >/dev/null 2>&1; then
    print_result "cloud_init" "pass"
  else
    print_result "cloud_init" "fail"
  fi
else
  print_result "cloud_init" "skip"
fi

# time synchronization
if command -v timedatectl >/dev/null 2>&1; then
  if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes; then
    print_result "time_sync" "pass"
  else
    print_result "time_sync" "fail"
  fi
else
  print_result "time_sync" "skip"
fi

# iptables backend
if command -v iptables >/dev/null 2>&1; then
  if iptables --version 2>/dev/null | grep -qi nf_tables; then
    print_result "iptables_backend" "pass"
  else
    print_result "iptables_backend" "fail"
  fi
else
  print_result "iptables_backend" "skip"
fi

# optional k3s check-config
if command -v k3s >/dev/null 2>&1; then
  if k3s check-config >/dev/null 2>&1; then
    print_result "k3s_check_config" "pass"
  else
    print_result "k3s_check_config" "fail"
  fi
else
  print_result "k3s_check_config" "skip"
fi

check_k3s_node_ready
check_projects_compose_active

if [[ -n "$TOKEN_PLACE_HEALTH_URL" && "$TOKEN_PLACE_HEALTH_URL" != "skip" ]]; then
  http_health_check "token_place_http" "$TOKEN_PLACE_HEALTH_URL" \
    "$TOKEN_PLACE_HEALTH_INSECURE" "$HEALTH_TIMEOUT"
else
  print_result "token_place_http" "skip"
fi

if [[ -n "$DSPACE_HEALTH_URL" && "$DSPACE_HEALTH_URL" != "skip" ]]; then
  http_health_check "dspace_http" "$DSPACE_HEALTH_URL" \
    "$DSPACE_HEALTH_INSECURE" "$HEALTH_TIMEOUT"
else
  print_result "dspace_http" "skip"
fi

if $ENABLE_LOG && [[ -n "$REPORT_PATH" ]]; then
  append_report "$REPORT_PATH"
fi

if $JSON; then
  printf '{"checks":[%s]}\n' "$(IFS=,; echo "${json_parts[*]}")"
fi
