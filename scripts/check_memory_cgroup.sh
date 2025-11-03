#!/usr/bin/env bash
# scripts/check_memory_cgroup.sh
set -Eeuo pipefail

STATE_DIR="${SUGARKUBE_STATE_DIR:-/etc/sugarkube}"
ENV_FILE="${STATE_DIR}/env"
SYSTEMD_DIR="${SUGARKUBE_SYSTEMD_DIR:-/etc/systemd/system}"
PROC_CMDLINE_PATH="${SUGARKUBE_PROC_CMDLINE_PATH:-/proc/cmdline}"

log() { printf '[sugarkube] %s\n' "$*"; }

if [ "$(uname -s)" != "Linux" ]; then
  log "Non-Linux host detected; skipping memory cgroup configuration."
  exit 0
fi

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
  if [ -n "${SUGARKUBE_MEMCTRL_FORCE-}" ]; then
    case "${SUGARKUBE_MEMCTRL_FORCE}" in
      active) return 0 ;;
      inactive) return 1 ;;
    esac
  fi
  if [ "$(cgroup_mode)" = v2 ]; then memctrl_active_v2; else memctrl_active_v1; fi
}

cmdline_path() {
  if [ -n "${SUGARKUBE_CMDLINE_PATH-}" ]; then
    if [ -f "${SUGARKUBE_CMDLINE_PATH}" ]; then
      printf %s "${SUGARKUBE_CMDLINE_PATH}"
      return 0
    fi
    log "ERROR: Cannot locate overridden cmdline.txt at ${SUGARKUBE_CMDLINE_PATH}"
    return 1
  fi
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

runtime_cmdline() {
  cat "$PROC_CMDLINE_PATH" 2>/dev/null || true
}

runtime_cmdline_has_mem_disable() {
  local line
  line="$(runtime_cmdline)"
  if [ -z "$line" ]; then
    return 1
  fi
  if printf '%s\n' "$line" | grep -Eq '(^|[[:space:]])cgroup_disable=memory($|[[:space:],])'; then
    return 0
  fi
  return 1
}

ensure_kernel_params() {
  # Adds required params if missing; echoes 1 if changed, 0 if not
  local f; f="$(cmdline_path)"
  local want1="cgroup_memory=1"
  local want2="cgroup_enable=memory"
  local line changed=0
  local -a tokens=()
  local -a keep=()
  local -a added=()
  local -a removed=()

  # Read single-line cmdline, preserve other args
  line="$(tr -d '\n' <"$f")"

  if [ -n "$line" ]; then
    read -r -a tokens <<<"$line"
  fi

  local token clean
  for token in "${tokens[@]}"; do
    clean="${token//$'\r'/}"
    if [ "$clean" != "$token" ]; then
      changed=1
    fi
    token="$clean"
    case "$token" in
      cgroup_disable=memory|cgroup_disable=memory,*)
        removed+=("$token")
        changed=1
        continue
        ;;
    esac
    keep+=("$token")
  done

  tokens=()
  if [ "${#keep[@]}" -gt 0 ]; then
    tokens=("${keep[@]}")
  fi

  for want in "$want1" "$want2"; do
    local found=0
    for token in "${tokens[@]}"; do
      if [ "$token" = "$want" ]; then
        found=1
        break
      fi
    done
    if [ "$found" -eq 0 ]; then
      tokens+=("$want")
      added+=("$want")
      changed=1
    fi
  done

  line="${tokens[*]}"
  # Normalize whitespace and trim
  line="$(printf '%s' "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"

  if [ "$changed" -eq 1 ]; then
    backup_file "$f"
    printf '%s\n' "$line" >"$f"
    sync
    local msg
    msg="Updated $(realpath "$f")"
    local -a parts=()
    if [ "${#added[@]}" -gt 0 ]; then
      parts+=("added: ${added[*]}")
    fi
    if [ "${#removed[@]}" -gt 0 ]; then
      parts+=("removed: ${removed[*]}")
    fi
    if [ "${#parts[@]}" -gt 0 ]; then
      local summary="${parts[0]}"
      local idx
      for idx in "${!parts[@]}"; do
        if [ "$idx" -ne 0 ]; then
          summary="$summary; ${parts[$idx]}"
        fi
      done
      msg="$msg ($summary)"
    fi
    log "$msg" >&2
  fi

  printf '%s' "$changed"
}

persist_env() {
  install -d -m 0755 -o root -g root "$STATE_DIR"
  : >"$ENV_FILE"
  chmod 0640 "$ENV_FILE"
  chown root:root "$ENV_FILE"

  # Persist the variables most likely needed by the bootstrap
  for n in SUGARKUBE_ENV SUGARKUBE_SERVERS SUGARKUBE_TOKEN SUGARKUBE_TOKEN_DEV SUGARKUBE_TOKEN_INT SUGARKUBE_TOKEN_PROD; do
    if [ -n "${!n-}" ]; then
      printf '%s=%q\n' "$n" "${!n}" >>"$ENV_FILE"
    fi
  done

  # If SUGARKUBE_TOKEN not set but an env-specific token is, derive it now
  if [ -z "${SUGARKUBE_TOKEN-}" ] && [ -n "${SUGARKUBE_ENV-}" ]; then
    case "${SUGARKUBE_ENV}" in
      dev)  [ -n "${SUGARKUBE_TOKEN_DEV-}"  ] && printf 'SUGARKUBE_TOKEN=%q\n'  "${SUGARKUBE_TOKEN_DEV}"  >>"$ENV_FILE" ;;
      int)  [ -n "${SUGARKUBE_TOKEN_INT-}"  ] && printf 'SUGARKUBE_TOKEN=%q\n'  "${SUGARKUBE_TOKEN_INT}"  >>"$ENV_FILE" ;;
      prod) [ -n "${SUGARKUBE_TOKEN_PROD-}" ] && printf 'SUGARKUBE_TOKEN=%q\n'  "${SUGARKUBE_TOKEN_PROD}" >>"$ENV_FILE" ;;
    esac
  fi
}

install_resume_service() {
  local svc="sugarkube-post-reboot.service"
  local user="${SUDO_USER:-$(/usr/bin/logname 2>/dev/null || echo pi)}"
  local home="/home/$user"
  local wd="$home/sugarkube"

  install -d -m 0755 -o root -g root "$SYSTEMD_DIR"

  python3 - <<'PY' "$SYSTEMD_DIR" "$svc" "$user" "$home" "$ENV_FILE" "$wd"
from __future__ import annotations

import pathlib
import sys


def main() -> None:
    systemd_dir, service_name, user, home, env_file, working_dir = sys.argv[1:]
    path = pathlib.Path(systemd_dir) / service_name
    path.write_text(
        f"""[Unit]
Description=Resume Sugarkube bootstrap after cgroup change
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={user}
Group={user}
Environment=HOME={home}
EnvironmentFile={env_file}
WorkingDirectory={working_dir}
ExecStart=/usr/bin/just up dev
ExecStartPost=/bin/systemctl disable --now {service_name}

[Install]
WantedBy=multi-user.target
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
PY

  systemctl daemon-reload
  systemctl enable "$svc"
}

main() {
  ensure_root "$@"

  if memctrl_active; then
    log "Memory cgroup controller is active; nothing to do."
    exit 0
  fi

  log "k3s requires the Linux memory cgroup controller, but it is not active."
  local changed
  changed="$(ensure_kernel_params || echo 0)"

  local needs_reboot="0"
  if [ "$changed" = "1" ]; then
    needs_reboot="1"
  fi

  if runtime_cmdline_has_mem_disable; then
    if [ "$changed" != "1" ]; then
      log "Running kernel booted with cgroup_disable=memory; reboot required to pick up new parameters."
    fi
    needs_reboot="1"
  fi

  if [ "$needs_reboot" = "1" ]; then
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
  log "  ${PROC_CMDLINE_PATH}: $(runtime_cmdline)"
  if [ "$(cgroup_mode)" = v2 ]; then
    log "  cgroup v2 controllers: $(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || true)"
  else
    log "  /proc/cgroups:"
    awk '{print "[sugarkube]   "$0}' /proc/cgroups 2>/dev/null || true
  fi
  exit 1
}

main "$@"
