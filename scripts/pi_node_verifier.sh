#!/usr/bin/env bash
set -euo pipefail

warn() {
  printf 'warning: %s\n' "$1" >&2
}

JSON=false
REPORT_PATH=""
ENABLE_LOG=true
DEFAULT_REPORT="/boot/first-boot-report.txt"
MIGRATION_LOG=${MIGRATION_LOG:-/var/log/sugarkube/migrations.log}

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
    --no-log)
      ENABLE_LOG=false
      ;;
    --help)
      cat <<'EOF'
Usage: pi_node_verifier.sh [--json] [--log PATH] [--no-log]

Options:
  --json       Emit machine-readable JSON results.
  --log PATH   Append a Markdown summary to PATH.
               Defaults to /boot/first-boot-report.txt when writable.
  --no-log     Disable report generation entirely.
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
  if ! $JSON; then
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

if $ENABLE_LOG && [[ -n "$REPORT_PATH" ]]; then
  append_report "$REPORT_PATH"
fi

if $JSON; then
  printf '{"checks":[%s]}\n' "$(IFS=,; echo "${json_parts[*]}")"
fi
