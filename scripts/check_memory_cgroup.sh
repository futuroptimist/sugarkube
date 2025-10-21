#!/usr/bin/env bash
# scripts/check_memory_cgroup.sh
set -Eeuo pipefail

log() { printf '[sugarkube] %s\n' "$*"; }

ensure_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    exec sudo -E -- "$0" "$@"
  fi
}

cgroup_mode() {
  # "cgroup2fs" => unified v2; otherwise assume legacy v1
  local t
  t="$(stat -fc %T /sys/fs/cgroup 2>/dev/null || true)"
  if [ "$t" = "cgroup2fs" ]; then echo v2; else echo v1; fi
}

memctrl_active_v2() {
  grep -qw memory /sys/fs/cgroup/cgroup.controllers 2>/dev/null
}

memctrl_active_v1() {
  [ -d /sys/fs/cgroup/memory ] && return 0
  # /proc/cgroups: subsys_name hierarchy num_cgroups enabled
  # enabled==1 means the controller is on
  [ "$(awk '$1=="memory"{print $4}' /proc/cgroups 2>/dev/null || echo 0)" = "1" ]
}

memctrl_active() {
  if [ "$(cgroup_mode)" = v2 ]; then memctrl_active_v2; else memctrl_active_v1; fi
}

cmdline_path() {
  if [ -f /boot/firmware/cmdline.txt ]; then
    printf %s /boot/firmware/cmdline.txt
    return 0
  fi
  if [ -f /boot/cmdline.txt ]; then
    if grep -qi 'moved to /boot/firmware/cmdline.txt' /boot/cmdline.txt 2>/dev/null; then
      printf %s /boot/firmware/cmdline.txt
    else
      printf %s /boot/cmdline.txt
    fi
    return 0
  fi
  log "ERROR: Cannot locate cmdline.txt (expected /boot/firmware/cmdline.txt or /boot/cmdline.txt)"
  return 1
}

backup_file() {
  local f="$1"
  cp -a -- "$f" "${f}.bak.$(date +%Y%m%d%H%M%S)"
}

ensure_kernel_params() {
  # Adds required params if missing; echoes 1 if changed, 0 if not
  local f; f="$(cmdline_path)"
  local want1="cgroup_memory=1"
  local want2="cgroup_enable=memory"
  local line changed=0

  # Read single-line cmdline, preserve other args
  line="$(tr -d '\n' <"$f")"

  if ! printf '%s\n' "$line" | grep -qw "$want1"; then
    line="$line $want1"; changed=1
  fi
  if ! printf '%s\n' "$line" | grep -qw "$want2"; then
    line="$line $want2"; changed=1
  fi

  # Normalize whitespace and trim
  line="$(printf '%s' "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"

  if [ "$changed" -eq 1 ]; then
    backup_file "$f"
    printf '%s\n' "$line" >"$f"
    sync
    log "Updated $(realpath "$f") with: $want1 $want2"
  fi

  printf '%s' "$changed"
}

persist_env() {
  install -d -m 0755 -o root -g root /etc/sugarkube
  local envfile="/etc/sugarkube/env"
  : >"$envfile"
  chmod 0640 "$envfile"
  chown root:root "$envfile"

  # Persist the variables most likely needed by the bootstrap
  for n in SUGARKUBE_ENV SUGARKUBE_SERVERS SUGARKUBE_TOKEN SUGARKUBE_TOKEN_DEV SUGARKUBE_TOKEN_INT SUGARKUBE_TOKEN_PROD; do
    if [ -n "${!n-}" ]; then
      printf '%s=%q\n' "$n" "${!n}" >>"$envfile"
    fi
  done

  # If SUGARKUBE_TOKEN not set but an env-specific token is, derive it now
  if [ -z "${SUGARKUBE_TOKEN-}" ] && [ -n "${SUGARKUBE_ENV-}" ]; then
    case "${SUGARKUBE_ENV}" in
      dev)  [ -n "${SUGARKUBE_TOKEN_DEV-}"  ] && printf 'SUGARKUBE_TOKEN=%q\n'  "${SUGARKUBE_TOKEN_DEV}"  >>"$envfile" ;;
      int)  [ -n "${SUGARKUBE_TOKEN_INT-}"  ] && printf 'SUGARKUBE_TOKEN=%q\n'  "${SUGARKUBE_TOKEN_INT}"  >>"$envfile" ;;
      prod) [ -n "${SUGARKUBE_TOKEN_PROD-}" ] && printf 'SUGARKUBE_TOKEN=%q\n'  "${SUGARKUBE_TOKEN_PROD}" >>"$envfile" ;;
    esac
  fi
}

install_resume_service() {
  local svc="sugarkube-post-reboot.service"
  local user="${SUDO_USER:-$(/usr/bin/logname 2>/dev/null || echo pi)}"
  local home="/home/$user"
  local wd="$home/sugarkube"

  cat >/etc/systemd/system/$svc <<EOF
[Unit]
Description=Resume Sugarkube bootstrap after cgroup change
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$user
Group=$user
Environment=HOME=$home
EnvironmentFile=/etc/sugarkube/env
WorkingDirectory=$wd
ExecStart=/usr/bin/just up dev
ExecStartPost=/bin/systemctl disable --now $svc

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$svc"
}

main() {
  ensure_root

  if memctrl_active; then
    log "Memory cgroup controller is active; nothing to do."
    exit 0
  fi

  log "k3s requires the Linux memory cgroup controller, but it is not active."
  local changed
  changed="$(ensure_kernel_params || echo 0)"

  if [ "$changed" = "1" ]; then
    persist_env || true
    install_resume_service || true
    log "Rebooting now to apply kernel parameters…"
    sleep 2
    systemctl reboot
    exit 0
  fi

  # Parameters are present but controller still inactive; provide diagnostics.
  log "Required kernel parameters are already present but memory cgroup is still inactive."
  log "Diagnostics:"
  log "  /proc/cmdline: $(cat /proc/cmdline 2>/dev/null || true)"
  if [ "$(cgroup_mode)" = v2 ]; then
    log "  cgroup v2 controllers: $(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || true)"
  else
    log "  /proc/cgroups:"
    awk '{print "[sugarkube]   "$0}' /proc/cgroups 2>/dev/null || true
  fi
  exit 1
}

main "$@"
