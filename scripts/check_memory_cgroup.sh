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

run_with_privilege() {
  if ((EUID == 0)); then
    "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi
  "$@"
}

file_has_flag() {
  local file="$1"
  local flag="$2"
  if run_with_privilege grep -qw "$flag" "$file" 2>/dev/null; then
    return 0
  fi
  return 1
}

append_flags() {
  local file="$1"
  shift
  local flags=("$@")
  if ((${#flags[@]} == 0)); then
    return 0
  fi
  local sed_expr="s/\$/ ${flags[*]}/"
  if run_with_privilege sed -i "$sed_expr" "$file"; then
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

required_flags=("cgroup_memory=1" "cgroup_enable=memory")
boot_missing_flags=()
if [[ -r /proc/cmdline ]]; then
  for flag in "${required_flags[@]}"; do
    if ! grep -qw "$flag" /proc/cmdline; then
      boot_missing_flags+=("$flag")
    fi
  done
else
  boot_missing_flags=("${required_flags[@]}")
fi

cmdline_target=""
for candidate in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [[ -e "$candidate" ]]; then
    cmdline_target="$candidate"
    break
  fi
done

file_missing_flags=()
if [[ -n "$cmdline_target" ]]; then
  for flag in "${required_flags[@]}"; do
    if ! file_has_flag "$cmdline_target" "$flag"; then
      file_missing_flags+=("$flag")
    fi
  done
fi

if ((${#boot_missing_flags[@]})); then
  if [[ -z "$cmdline_target" ]]; then
    err "Could not locate /boot/firmware/cmdline.txt or /boot/cmdline.txt."
    err "Add the following kernel parameters to your boot configuration: ${required_flags[*]}"
    err "After updating, reboot the Raspberry Pi and rerun 'just up dev'."
    exit 1
  fi

  if ((${#file_missing_flags[@]})); then
    err "Adding required kernel parameters (${file_missing_flags[*]}) to ${cmdline_target}..."
    if append_flags "$cmdline_target" "${file_missing_flags[@]}"; then
      err "Updated ${cmdline_target}. Reboot the Raspberry Pi so the changes take effect, then rerun 'just up dev'."
      exit 1
    fi
    err "Failed to update ${cmdline_target} automatically."
    err "Add the following parameters manually: ${required_flags[*]}"
    err "After updating, reboot the Raspberry Pi and rerun 'just up dev'."
    exit 1
  fi

  err "The required kernel parameters are already present in ${cmdline_target}."
  err "Reboot the Raspberry Pi so the new parameters take effect, then rerun 'just up dev'."
  exit 1
fi

err "Enable the memory controller in your boot configuration and reboot the node."
err "After updating, reboot the Raspberry Pi and rerun 'just up dev'."

exit 1
