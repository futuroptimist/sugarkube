#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -s) != "Linux" ]]; then
  exit 0
fi

have_memory_cgroup() {
  if [[ -d /sys/fs/cgroup/memory ]]; then
    return 0
  fi
  if [[ -f /sys/fs/cgroup/cgroup.controllers ]] && \
     grep -qw memory /sys/fs/cgroup/cgroup.controllers; then
    return 0
  fi
  return 1
}

if have_memory_cgroup; then
  exit 0
fi

err() {
  echo "[sugarkube] $*" >&2
}

err "k3s requires the Linux memory cgroup controller, but it is not active."

missing_flags=()
if [[ -r /proc/cmdline ]]; then
  if ! grep -qw 'cgroup_memory=1' /proc/cmdline; then
    missing_flags+=("cgroup_memory=1")
  fi
  if ! grep -qw 'cgroup_enable=memory' /proc/cmdline; then
    missing_flags+=("cgroup_enable=memory")
  fi
fi

if ((${#missing_flags[@]})); then
  cmdline_hint="/boot/firmware/cmdline.txt"
  example_target=""
  if [[ -e /boot/firmware/cmdline.txt ]]; then
    example_target="/boot/firmware/cmdline.txt"
  elif [[ -e /boot/cmdline.txt ]]; then
    cmdline_hint="/boot/cmdline.txt"
    example_target="/boot/cmdline.txt"
  else
    cmdline_hint="/boot/firmware/cmdline.txt or /boot/cmdline.txt"
  fi

  err "Add the following kernel parameters to ${cmdline_hint}: ${missing_flags[*]}"
  if [[ -n "${example_target}" ]]; then
    err "Example (append while keeping the file on a single line):"
    err "  sudo sed -i 's/$/ ${missing_flags[*]}/' ${example_target}"
  fi
else
  err "Enable the memory controller in your boot configuration and reboot the node."
fi
err "After updating, reboot the Raspberry Pi and rerun 'just up'."

exit 1
