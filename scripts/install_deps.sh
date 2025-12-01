#!/usr/bin/env bash
# scripts/install_deps.sh
set -euo pipefail

log() {
  printf '[sugarkube] %s\n' "$*"
}

require_root() {
  if [ "${SUGARKUBE_ALLOW_ROOTLESS_DEPS:-0}" = "1" ]; then
    log 'WARNING: Running install_deps.sh without root privileges (tests or dry-run mode).'
    return 0
  fi

  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    log 'ERROR: This script must be run as root (try via sudo).'
    exit 1
  fi
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

apt_packages=(
  avahi-daemon
  avahi-utils
  libnss-mdns
  dbus
  libglib2.0-bin
  jq
  curl
  python3
  tcpdump
  nftables
)

check_apt_support() {
  if ! have_command apt-get; then
    log 'WARNING: apt-get not found; cannot automatically install dependencies.'
    log "Missing packages may break mDNS discovery or k3s bootstrap."
    return 1
  fi
  return 0
}

missing_packages() {
  local pkg
  for pkg in "$@"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
      printf '%s\n' "$pkg"
    fi
  done
}

install_missing_packages() {
  local missing
  missing="$(missing_packages "$@" | tr '\n' ' ')"
  if [ -z "${missing// }" ]; then
    log 'All apt packages already installed.'
    return 0
  fi

  log "Installing missing packages: ${missing}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  # shellcheck disable=SC2086
  apt-get install -y --no-install-recommends ${missing}
}

ensure_avahi_enabled() {
  local units
  if ! have_command systemctl; then
    log 'WARNING: systemctl not available; cannot manage avahi-daemon service.'
    return
  fi

  if ! pidof systemd >/dev/null 2>&1; then
    log 'WARNING: systemd is not running; skipping avahi-daemon enablement.'
    return
  fi

  if ! units=$(systemctl list-unit-files --type=service 2>&1); then
    log 'WARNING: Unable to query systemd unit files; skipping avahi-daemon enablement.'
    return
  fi

  if ! grep -q '^avahi-daemon\.service' <<<"${units}"; then
    log 'avahi-daemon service unit not found; ensure Avahi is supported on this host.'
    return
  fi

  if ! systemctl is-enabled avahi-daemon >/dev/null 2>&1; then
    log 'Enabling avahi-daemon service.'
    systemctl enable --now avahi-daemon
    return
  fi

  if ! systemctl is-active avahi-daemon >/dev/null 2>&1; then
    log 'Starting avahi-daemon service.'
    systemctl start avahi-daemon
  else
    log 'avahi-daemon service already active.'
  fi
}

ensure_nsswitch_mdns() {
  local nsswitch='/etc/nsswitch.conf'
  local backup
  if [ ! -f "$nsswitch" ]; then
    log 'WARNING: /etc/nsswitch.conf missing; cannot validate mDNS resolver configuration.'
    return
  fi

  if grep -Eq '^hosts:.*mdns4_minimal' "$nsswitch"; then
    log 'mDNS resolver already configured in /etc/nsswitch.conf.'
    return
  fi

  backup="${nsswitch}.bak.$(date +%Y%m%d%H%M%S)"
  cp -a -- "$nsswitch" "$backup"
  log "Updating hosts line in /etc/nsswitch.conf (backup at ${backup})."
  sed -i 's/^hosts:.*/hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4/' "$nsswitch"
}

cgroup_mode() {
  stat -fc %T /sys/fs/cgroup 2>/dev/null || true
}

memory_controller_active() {
  local mode
  mode="$(cgroup_mode)"
  case "$mode" in
    cgroup2fs)
      grep -qw memory /sys/fs/cgroup/cgroup.controllers 2>/dev/null
      ;;
    *)
      if [ -d /sys/fs/cgroup/memory ]; then
        return 0
      fi
      [ "$(awk '$1=="memory"{print $4}' /proc/cgroups 2>/dev/null || echo 0)" = "1" ]
      ;;
  esac
}

print_cgroup_hints() {
  if [ "$(uname -s)" != 'Linux' ]; then
    return
  fi

  if memory_controller_active; then
    log 'Memory cgroup controller detected.'
  else
    log 'WARNING: Memory cgroup controller is disabled; k3s will fail to start.'
    log "Hint: run scripts/check_memory_cgroup.sh or add 'cgroup_memory=1 cgroup_enable=memory' to /boot/cmdline.txt and reboot."
  fi

  if [ -f /proc/cmdline ]; then
    if ! grep -Eq '(^|[[:space:]])cgroup_memory=1([[:space:]]|$)' /proc/cmdline; then
      log "Hint: runtime cmdline is missing 'cgroup_memory=1'."
    fi
    if ! grep -Eq '(^|[[:space:]])cgroup_enable=memory([[:space:]]|$)' /proc/cmdline; then
      log "Hint: runtime cmdline is missing 'cgroup_enable=memory'."
    fi
  fi
}

main() {
  require_root

  if check_apt_support; then
    install_missing_packages "${apt_packages[@]}"
  else
    log 'Proceeding without automatic package installation.'
  fi

  ensure_avahi_enabled
  ensure_nsswitch_mdns
  print_cgroup_hints
}

main "$@"
