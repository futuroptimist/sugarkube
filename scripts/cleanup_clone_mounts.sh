#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

DRY_RUN=0
VERBOSE=0
FORCE=0
KEEP_DIRS=0
TARGET="${TARGET:-/dev/nvme0n1}"
MOUNT_BASE="${MOUNT_BASE:-/mnt/clone}"

log() {
  printf '[clean-mounts] %s\n' "$*"
}

vlog() {
  if [ "$VERBOSE" -eq 1 ]; then
    log "$@"
  fi
}

format_cmd() {
  local formatted=""
  local arg
  for arg in "$@"; do
    if [ -n "$formatted" ]; then
      formatted+=" "
    fi
    formatted+=$(printf '%q' "$arg")
  done
  printf '%s' "$formatted"
}

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY: $(format_cmd "$@")"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "Running: $(format_cmd "$@")"
  fi
  set +e
  "$@"
  local status=$?
  set -e
  return $status
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--verbose|-v] [--force] [--keep-dirs]
Env vars: TARGET=$TARGET MOUNT_BASE=$MOUNT_BASE
EOF
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

parse_findmnt_line() {
  local line="$1" source target tmp
  tmp=${line#SOURCE="}
  source=${tmp%%"*}
  tmp=${line#*TARGET="}
  target=${tmp%%"*}
  printf '%s\t%s\n' "$source" "$target"
}

collect_blocker_pids() {
  local mount_path="$1"
  local -a pids=()
  if command_exists lsof; then
    while IFS= read -r pid; do
      [ -n "$pid" ] && pids+=("$pid")
    done < <(lsof -t +f -- "$mount_path" 2>/dev/null | sort -u)
  elif command_exists fuser; then
    while IFS= read -r pid; do
      [ -n "$pid" ] && pids+=("$pid")
    done < <(fuser -vm "$mount_path" 2>/dev/null | awk 'NR>1 {for (i=1; i<=NF; i++) if ($i ~ /^[0-9]+$/) print $i}' | sort -u)
  fi
  printf '%s\n' "${pids[*]:-}"
}

show_blockers() {
  local mount_path="$1"
  if command_exists fuser; then
    log "Inspecting processes holding $mount_path"
    if ! fuser -vm "$mount_path" 2>/dev/null; then
      vlog "No active processes reported by fuser for $mount_path"
    fi
  elif command_exists lsof; then
    log "Inspecting processes holding $mount_path"
    if ! lsof +f -- "$mount_path" 2>/dev/null; then
      vlog "No active processes reported by lsof for $mount_path"
    fi
  else
    log "Cannot list blockers: fuser/lsof not available"
  fi
}

terminate_blockers() {
  local mount_path="$1"
  if [ "$FORCE" -ne 1 ]; then
    return 0
  fi
  local pid_line
  pid_line=$(collect_blocker_pids "$mount_path")
  if [ -z "$pid_line" ]; then
    vlog "No blocker PIDs found for $mount_path"
    return 0
  fi
  # shellcheck disable=SC2206
  local pids=( $pid_line )
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY: would send SIGTERM to ${pids[*]} for $mount_path"
    log "DRY: would send SIGKILL if needed for $mount_path"
    return 0
  fi
  log "Sending SIGTERM to processes holding $mount_path: ${pids[*]}"
  kill -TERM "${pids[@]}" 2>/dev/null || true
  sleep 2
  pid_line=$(collect_blocker_pids "$mount_path")
  if [ -n "$pid_line" ]; then
    # shellcheck disable=SC2206
    pids=( $pid_line )
    log "Escalating to SIGKILL for $mount_path: ${pids[*]}"
    kill -KILL "${pids[@]}" 2>/dev/null || true
    sleep 1
  fi
}

unmount_path() {
  local path="$1"
  shift
  local -a opts=()
  if [ "$#" -gt 0 ]; then
    opts=("$@")
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY: umount ${opts[*]} $path"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "Attempting to unmount $path (${opts[*]})"
  fi
  set +e
  umount "${opts[@]}" "$path"
  local status=$?
  set -e
  if [ "$status" -eq 0 ]; then
    log "Unmounted $path"
    return 0
  fi
  if [ "$status" -eq 32 ]; then
    log "Unmount failed for $path: device busy"
    show_blockers "$path"
    if [ "$FORCE" -eq 1 ]; then
      terminate_blockers "$path"
      set +e
      umount "${opts[@]}" "$path"
      status=$?
      set -e
      if [ "$status" -eq 0 ]; then
        log "Unmounted $path after terminating blockers"
        return 0
      fi
      if [ "$status" -eq 32 ]; then
        log "Still busy after termination; attempting lazy unmount of $path"
        set +e
        umount -l "$path"
        status=$?
        set -e
        if [ "$status" -eq 0 ]; then
          log "Lazy unmount succeeded for $path"
          return 0
        fi
      fi
    else
      log "Use --force to terminate blocking processes for $path"
      return 32
    fi
  else
    log "Unmount failed for $path (status $status); attempting lazy unmount"
    set +e
    umount -l "$path"
    local lazy_status=$?
    set -e
    if [ "$lazy_status" -eq 0 ]; then
      log "Lazy unmount succeeded for $path"
      return 0
    fi
    log "Lazy unmount failed for $path (status $lazy_status)"
    return $status
  fi
  return $status
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --verbose|-v)
      VERBOSE=1
      ;;
    --force)
      FORCE=1
      ;;
    --keep-dirs)
      KEEP_DIRS=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      log "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

if [ "$#" -gt 0 ]; then
  log "Unexpected argument: $1"
  usage
  exit 1
fi

if ! command_exists findmnt; then
  log "findmnt is required but not available"
  exit 1
fi

log "Target device: $TARGET"
log "Mount base: $MOUNT_BASE"

declare -a base_mounts=()
while IFS= read -r line; do
  [ -n "$line" ] && base_mounts+=("$line")
done < <(findmnt -rn -P -o SOURCE,TARGET --target "$MOUNT_BASE" --submounts 2>/dev/null || true)

declare -a partition_mounts=()
if [ -b "$TARGET" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] && partition_mounts+=("$line")
  done < <(findmnt -rn -P -o SOURCE,TARGET --source "${TARGET}p*" 2>/dev/null || true)
else
  vlog "Target device $TARGET not present; skipping partition detection"
fi

if [ "${#base_mounts[@]}" -eq 0 ] && [ "${#partition_mounts[@]}" -eq 0 ]; then
  log "No mounts detected under $MOUNT_BASE or matching ${TARGET}p*"
  exit 0
fi

log "Detected mounts:"
declare -A seen_mountpoints=()
declare -a mountpoints=()
for entry in "${base_mounts[@]}" "${partition_mounts[@]}"; do
  [ -z "$entry" ] && continue
  parsed=$(parse_findmnt_line "$entry")
  src=${parsed%%\t*}
  tgt=${parsed#*\t}
  printf '  %-30s -> %s\n' "$src" "$tgt"
  if [ -n "$tgt" ] && [ -z "${seen_mountpoints[$tgt]:-}" ]; then
    seen_mountpoints["$tgt"]=1
    mountpoints+=("$tgt")
  fi
done

if command_exists systemctl; then
  log "Stopping systemd automount units (best effort)"
  declare -a units=("mnt-clone.automount" "mnt-clone.mount")
  if command_exists systemd-escape; then
    unit_name=$(systemd-escape --path "$MOUNT_BASE")
    units+=("${unit_name}.automount" "${unit_name}.mount")
  fi
  declare -A seen_units=()
  for unit in "${units[@]}"; do
    [ -z "$unit" ] && continue
    if [ -n "${seen_units[$unit]:-}" ]; then
      continue
    fi
    seen_units["$unit"]=1
    if ! run systemctl stop "$unit"; then
      vlog "Ignoring failure when stopping $unit"
    fi
  done
else
  vlog "systemctl not available; skipping automount stop"
fi

for mp in "${mountpoints[@]}"; do
  show_blockers "$mp"
  if [ "$FORCE" -eq 1 ]; then
    terminate_blockers "$mp"
  fi
done

if findmnt -rn --target "$MOUNT_BASE" >/dev/null 2>&1; then
  if ! unmount_path "$MOUNT_BASE" -R; then
    status=$?
    if [ "$status" -eq 32 ] && [ "$FORCE" -ne 1 ]; then
      log "Mount at $MOUNT_BASE remains busy. Rerun with --force to terminate holders."
    fi
    exit $status
  fi
else
  vlog "$MOUNT_BASE is not currently a mountpoint"
fi

if [ "${#partition_mounts[@]}" -gt 0 ]; then
  for entry in "${partition_mounts[@]}"; do
    parsed=$(parse_findmnt_line "$entry")
    src=${parsed%%\t*}
    tgt=${parsed#*\t}
    if [ -z "$tgt" ]; then
      continue
    fi
    if findmnt -rn --target "$tgt" >/dev/null 2>&1; then
      if ! unmount_path "$tgt"; then
        status=$?
        if [ "$status" -eq 32 ] && [ "$FORCE" -ne 1 ]; then
          log "Partition $src at $tgt remains busy. Rerun with --force to terminate holders."
        fi
        exit $status
      fi
    fi
  done
fi

remaining=$(findmnt -rn -P -o SOURCE,TARGET --target "$MOUNT_BASE" --submounts 2>/dev/null || true)
if [ -n "$remaining" ]; then
  log "Mount points still detected under $MOUNT_BASE:"
  printf '%s\n' "$remaining"
  if [ "$FORCE" -eq 0 ]; then
    log "Run again with --force if safe to terminate lingering processes."
  fi
  exit 1
fi
if [ -b "$TARGET" ]; then
  lingering=$(findmnt -rn -P -o SOURCE,TARGET --source "${TARGET}p*" 2>/dev/null || true)
  if [ -n "$lingering" ]; then
    log "Device partitions still mounted:"
    printf '%s\n' "$lingering"
    if [ "$FORCE" -eq 0 ]; then
      log "Run again with --force if safe to terminate lingering processes."
    fi
    exit 1
  fi
fi

if command_exists udevadm; then
  if ! run udevadm settle; then
    vlog "udevadm settle failed (ignored)"
  fi
else
  vlog "udevadm not available; skipping settle"
fi

if [ "$KEEP_DIRS" -ne 1 ]; then
  if [ -d "$MOUNT_BASE" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY: would prune empty directories under $MOUNT_BASE"
    else
      vlog "Pruning empty directories under $MOUNT_BASE"
      find "$MOUNT_BASE" -mindepth 1 -type d -empty -print -delete 2>/dev/null || true
    fi
  fi
else
  vlog "--keep-dirs set; skipping directory cleanup"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY: would ensure $MOUNT_BASE/boot/firmware exists"
else
  if ! run mkdir -p "$MOUNT_BASE/boot/firmware"; then
    vlog "Unable to create $MOUNT_BASE/boot/firmware (ignored)"
  fi
fi

log "Cleanup complete"
exit 0
