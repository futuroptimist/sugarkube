#!/usr/bin/env bash
set -euo pipefail

JSON=false
for arg in "$@"; do
  case "$arg" in
    --json) JSON=true ;;
    --help) echo "Usage: $0 [--json]"; exit 0 ;;
  esac
done

json_parts=()
print_result() {
  local name="$1"
  local status="$2"
  if ! $JSON; then
    printf '%s: %s\n' "$name" "$status"
  fi
  json_parts+=('{"name":"'"$name"'","status":"'"$status"'"}')
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

if $JSON; then
  printf '{"checks":[%s]}\n' "$(IFS=,; echo "${json_parts[*]}")"
fi
