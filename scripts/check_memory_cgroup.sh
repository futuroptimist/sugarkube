#!/usr/bin/env bash
# scripts/check_memory_cgroup.sh
set -Eeuo pipefail

STATE_DIR="${SUGARKUBE_STATE_DIR:-/etc/sugarkube}"
ENV_FILE="${STATE_DIR}/env"
SYSTEMD_DIR="${SUGARKUBE_SYSTEMD_DIR:-/etc/systemd/system}"

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

ensure_kernel_params() {
  # Adds required params if missing; echoes 1 if changed, 0 if not
  local f
  if [ -n "${1-}" ]; then
    f="$1"
  else
    f="$(cmdline_path)"
  fi
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

  for token in "${tokens[@]}"; do
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

cmdline_runtime_path() {
  if [ -n "${SUGARKUBE_PROC_CMDLINE_PATH-}" ]; then
    if [ -f "${SUGARKUBE_PROC_CMDLINE_PATH}" ]; then
      printf %s "${SUGARKUBE_PROC_CMDLINE_PATH}"
      return 0
    fi
    log "ERROR: Cannot locate overridden proc cmdline at ${SUGARKUBE_PROC_CMDLINE_PATH}"
    return 1
  fi
  printf %s /proc/cmdline
}

CMDLINE_HAS_DISABLE=0
CMDLINE_HAS_ENABLE=0
CMDLINE_HAS_MEMORY=0

analyze_cmdline_tokens() {
  local f="$1"
  local line=""
  local -a tokens=()
  CMDLINE_HAS_DISABLE=0
  CMDLINE_HAS_ENABLE=0
  CMDLINE_HAS_MEMORY=0

  if [ ! -f "$f" ]; then
    return 1
  fi

  line="$(tr -d '\n' <"$f" | tr -d '\r')"

  if [ -n "$line" ]; then
    read -r -a tokens <<<"$line"
  fi

  for token in "${tokens[@]}"; do
    case "$token" in
      cgroup_disable=memory|cgroup_disable=memory,*)
        CMDLINE_HAS_DISABLE=1
        ;;
      cgroup_enable=memory)
        CMDLINE_HAS_ENABLE=1
        ;;
      cgroup_memory=1)
        CMDLINE_HAS_MEMORY=1
        ;;
    esac
  done

  return 0
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

  cat >"$SYSTEMD_DIR/$svc" <<EOF
[Unit]
Description=Resume Sugarkube bootstrap after cgroup change
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$user
Group=$user
Environment=HOME=$home
EnvironmentFile=$ENV_FILE
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
  ensure_root "$@"

  if memctrl_active; then
    log "Memory cgroup controller is active; nothing to do."
    exit 0
  fi

  log "k3s requires the Linux memory cgroup controller, but it is not active."

  local cmdline_file
  cmdline_file="$(cmdline_path)"

  local changed
  changed="$(ensure_kernel_params "$cmdline_file" || echo 0)"

  if ! analyze_cmdline_tokens "$cmdline_file"; then
    log "ERROR: Unable to inspect $(realpath "$cmdline_file")"
    exit 1
  fi

  if [ "$CMDLINE_HAS_DISABLE" -eq 1 ]; then
    log "$(realpath "$cmdline_file") still contains cgroup_disable=memory; aborting."
    exit 1
  fi

  if [ "$CMDLINE_HAS_ENABLE" -eq 0 ] || [ "$CMDLINE_HAS_MEMORY" -eq 0 ]; then
    log "$(realpath "$cmdline_file") is missing required cgroup parameters; aborting."
    exit 1
  fi

  local runtime_disable=0
  local runtime_enable=0
  local runtime_memory=0
  local runtime_path
  if ! runtime_path="$(cmdline_runtime_path)"; then
    exit 1
  fi

  if grep -qw 'cgroup_disable=memory' "$runtime_path" 2>/dev/null; then
    runtime_disable=1
  fi
  if grep -qw 'cgroup_enable=memory' "$runtime_path" 2>/dev/null; then
    runtime_enable=1
  fi
  if grep -qw 'cgroup_memory=1' "$runtime_path" 2>/dev/null; then
    runtime_memory=1
  fi

  local needs_reboot="$changed"
  if [ "$runtime_disable" -eq 1 ] || [ "$runtime_enable" -eq 0 ] || [ "$runtime_memory" -eq 0 ]; then
    needs_reboot=1
  fi

  if [ "$needs_reboot" = "1" ]; then
    persist_env || true
    install_resume_service || true
    sync || true
    log "Rebooting now to apply kernel parameters…"
    sleep 2
    systemctl reboot
    exit 0
  fi

  # Parameters are present but controller still inactive; provide diagnostics.
  log "Required kernel parameters are already present but memory cgroup is still inactive."
  log "Diagnostics:"
  log "  runtime cmdline (${runtime_path}): $(cat "$runtime_path" 2>/dev/null || true)"
  if [ "$(cgroup_mode)" = v2 ]; then
    log "  cgroup v2 controllers: $(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || true)"
  else
    log "  /proc/cgroups:"
    awk '{print "[sugarkube]   "$0}' /proc/cgroups 2>/dev/null || true
  fi
  exit 1
}

main "$@"
