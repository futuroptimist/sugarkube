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
  local IFS=' '
  printf '[clean-mounts] %s\n' "$*"
}

vlog() {
  if [ "$VERBOSE" -eq 1 ]; then
    log "$@"
  fi
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run] [--verbose|-v] [--force] [--keep-dirs]
       $(basename "$0") --help

Environment variables:
  TARGET      Target block device (default: ${TARGET})
  MOUNT_BASE  Base directory for clone mounts (default: ${MOUNT_BASE})

Flags:
  --dry-run     Only log intended actions without making changes
  --verbose|-v  Increase logging verbosity
  --force       Terminate processes holding the mounts if required
  --keep-dirs   Preserve empty mount directories (skip cleanup)
  --help        Show this help and exit
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Required command '$1' not found in PATH"
    exit 1
  fi
}

join_args() {
  local IFS=' '
  printf '%s' "$*"
}

run_cmd() {
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: $(join_args "$@")"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "RUN: $(join_args "$@")"
  fi
  "$@"
}

sleep_maybe() {
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: sleep $1"
    return 0
  fi
  sleep "$1"
}

parse_args() {
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
}

parse_args "$@"
require_command findmnt

declare -a BASE_POINTS=()
declare -a TARGET_SOURCES=()
declare -a TARGET_POINTS=()
declare -a MOUNT_DEVICES=()
declare -a MOUNT_POINTS=()
declare -A SEEN_MOUNTS=()

add_mount() {
  local device="$1"
  local point="$2"
  local key="${device}::${point}"
  if [ -z "$device" ] || [ -z "$point" ]; then
    return 0
  fi
  if [ -n "${SEEN_MOUNTS[$key]:-}" ]; then
    return 0
  fi
  SEEN_MOUNTS[$key]=1
  MOUNT_DEVICES+=("$device")
  MOUNT_POINTS+=("$point")
}

collect_base_mounts() {
  mapfile -t BASE_POINTS < <(findmnt -rn -o TARGET --submounts "$MOUNT_BASE" 2>/dev/null || true)
  local point
  for point in "${BASE_POINTS[@]}"; do
    if [ -z "$point" ]; then
      continue
    fi
    local src
    src=$(findmnt -rn -o SOURCE --target "$point" 2>/dev/null || true)
    if [ -z "$src" ]; then
      continue
    fi
    add_mount "$src" "$point"
  done
}

collect_target_mounts() {
  if [ ! -e "$TARGET" ]; then
    vlog "Target device $TARGET not present; skipping partition scan."
    return
  fi
  mapfile -t TARGET_SOURCES < <(findmnt -rn -o SOURCE -S "${TARGET}p*" 2>/dev/null || true)
  local src
  for src in "${TARGET_SOURCES[@]}"; do
    if [ -z "$src" ]; then
      continue
    fi
    mapfile -t TARGET_POINTS < <(findmnt -rn -o TARGET --source "$src" 2>/dev/null || true)
    local point
    for point in "${TARGET_POINTS[@]}"; do
      if [ -z "$point" ]; then
        continue
      fi
      add_mount "$src" "$point"
    done
  done
}

collect_base_mounts
collect_target_mounts

if [ "${#MOUNT_POINTS[@]}" -eq 0 ]; then
  log "No mounts detected under $MOUNT_BASE or sourced from ${TARGET}p*."
else
  log "Detected mounts:"
  printf '  %-32s %s\n' "DEVICE" "MOUNTPOINT"
  for idx in "${!MOUNT_POINTS[@]}"; do
    printf '  %-32s %s\n' "${MOUNT_DEVICES[$idx]}" "${MOUNT_POINTS[$idx]}"
  done
fi

stop_systemd_units() {
  if ! command -v systemctl >/dev/null 2>&1; then
    vlog "systemctl not available; skipping automount stop."
    return
  fi

  local escaped
  escaped=$(systemd-escape --path "$MOUNT_BASE")
  local units=("mnt-clone.automount" "mnt-clone.mount" "${escaped}.automount" "${escaped}.mount")

  local seen=()
  local unit
  for unit in "${units[@]}"; do
    if [ -z "$unit" ]; then
      continue
    fi
    if [ "${#seen[@]}" -gt 0 ] && printf '%s\n' "${seen[@]}" | grep -Fxq "$unit"; then
      continue
    fi
    seen+=("$unit")
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY-RUN: systemctl stop $unit"
      continue
    fi
    if systemctl stop "$unit" >/dev/null 2>&1; then
      vlog "Stopped $unit"
    else
      vlog "Unit $unit not active or failed to stop (ignored)."
    fi
  done
}

stop_systemd_units

declare BLOCKER_TOOL=""
declare BLOCKER_OUTPUT=""
declare -a BLOCKER_PIDS=()

collect_blockers() {
  local path="$1"
  BLOCKER_TOOL=""
  BLOCKER_OUTPUT=""
  BLOCKER_PIDS=()

  if command -v fuser >/dev/null 2>&1; then
    local output
    if output=$(fuser -vm "$path" 2>&1); then
      BLOCKER_TOOL="fuser"
      BLOCKER_OUTPUT="$output"
      mapfile -t BLOCKER_PIDS < <(printf '%s\n' "$output" | awk 'NR>1 {print $2}' | sort -u)
      if [ "${#BLOCKER_PIDS[@]}" -gt 0 ]; then
        return 0
      fi
    else
      local status=$?
      if [ "$status" -gt 1 ]; then
        log "fuser reported an error on $path (exit $status)."
      fi
      if [ "$status" -eq 0 ]; then
        # Should not happen because success implies output; treat as blockers.
        BLOCKER_TOOL="fuser"
        BLOCKER_OUTPUT="$output"
        mapfile -t BLOCKER_PIDS < <(printf '%s\n' "$output" | awk 'NR>1 {print $2}' | sort -u)
        if [ "${#BLOCKER_PIDS[@]}" -gt 0 ]; then
          return 0
        fi
      fi
    fi
  fi

  if [ -z "$BLOCKER_TOOL" ] && command -v lsof >/dev/null 2>&1; then
    local output
    output=$(lsof +f -- "$path" 2>/dev/null || true)
    if [ -n "$output" ]; then
      BLOCKER_TOOL="lsof"
      BLOCKER_OUTPUT="$output"
      mapfile -t BLOCKER_PIDS < <(printf '%s\n' "$output" | awk 'NR>1 {print $2}' | sort -u)
      if [ "${#BLOCKER_PIDS[@]}" -gt 0 ]; then
        return 0
      fi
    fi
  fi

  return 1
}

send_signal() {
  local signal="$1"
  shift
  local pid
  for pid in "$@"; do
    if [ -z "$pid" ]; then
      continue
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY-RUN: kill -$signal $pid"
    else
      if kill "-$signal" "$pid" 2>/dev/null; then
        vlog "Sent SIG$signal to PID $pid"
      else
        vlog "Failed to send SIG$signal to PID $pid (ignored)."
      fi
    fi
  done
}

ensure_unblocked() {
  local path="$1"
  if ! collect_blockers "$path"; then
    return 0
  fi

  log "Mount at $path is busy (detected via $BLOCKER_TOOL):"
  printf '%s\n' "$BLOCKER_OUTPUT"

  if [ "$FORCE" -eq 0 ]; then
    log "Re-run with --force to terminate blocking processes."
    return 1
  fi

  if [ "${#BLOCKER_PIDS[@]}" -eq 0 ]; then
    log "No PIDs parsed from blocker output; cannot forcefully clear $path."
    return 1
  fi

  log "Attempting graceful termination of ${#BLOCKER_PIDS[@]} process(es) holding $path."
  send_signal TERM "${BLOCKER_PIDS[@]}"
  sleep_maybe 2

  if collect_blockers "$path"; then
    log "Processes still holding $path after SIGTERM; escalating to SIGKILL."
    send_signal KILL "${BLOCKER_PIDS[@]}"
    sleep_maybe 1
    if collect_blockers "$path"; then
      log "Unable to clear blockers for $path even after SIGKILL."
      return 1
    fi
  fi

  log "Cleared blockers for $path."
  return 0
}

resolve_all_blockers() {
  local point
  local -A checked=()
  for point in "${MOUNT_POINTS[@]}"; do
    if [ -z "$point" ]; then
      continue
    fi
    if [ -n "${checked[$point]:-}" ]; then
      continue
    fi
    checked[$point]=1
    if ! ensure_unblocked "$point"; then
      exit 1
    fi
  done
}

resolve_all_blockers

attempt_umount() {
  local mount_point="$1"
  local source="$2"

  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: umount $mount_point"
    return 0
  fi

  if umount "$mount_point" 2>/dev/null; then
    log "Unmounted $mount_point"
    return 0
  fi

  local status=$?
  log "umount $mount_point failed with status $status"

  if [ -n "$source" ] && [ ! -e "$source" ]; then
    log "Source $source is missing; attempting lazy unmount of $mount_point."
    if umount -l "$mount_point" 2>/dev/null; then
      log "Lazy unmounted $mount_point"
      return 0
    fi
  fi

  if [ "$FORCE" -eq 1 ]; then
    log "Force flag set; retrying lazy unmount of $mount_point."
    if umount -l "$mount_point" 2>/dev/null; then
      log "Lazy unmounted $mount_point"
      return 0
    fi
  fi

  if collect_blockers "$mount_point"; then
    log "Mount at $mount_point remains busy after unmount attempt:"
    printf '%s\n' "$BLOCKER_OUTPUT"
  fi
  return 1
}

if [ "${#BASE_POINTS[@]}" -gt 0 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: umount -R $MOUNT_BASE"
  else
    if umount -R "$MOUNT_BASE" 2>/dev/null; then
      log "Recursively unmounted mounts under $MOUNT_BASE"
    else
      status=$?
      log "umount -R $MOUNT_BASE failed with status $status"
      if collect_blockers "$MOUNT_BASE"; then
        log "$MOUNT_BASE remains busy after recursive unmount attempt:"
        printf '%s\n' "$BLOCKER_OUTPUT"
      fi
      fallback_required=0
      if [ "$FORCE" -eq 1 ]; then
        fallback_required=1
      elif ! command -v findmnt >/dev/null 2>&1; then
        fallback_required=1
      elif findmnt -rn --target "$MOUNT_BASE" >/dev/null 2>&1; then
        fallback_required=1
      fi

      if [ "$fallback_required" -eq 1 ]; then
        log "Falling back to lazy recursive unmount of $MOUNT_BASE."
        if umount -Rl "$MOUNT_BASE" 2>/dev/null; then
          log "Lazy-recursively unmounted $MOUNT_BASE"
        else
          log "Lazy recursive unmount of $MOUNT_BASE failed."
        fi
      fi
    fi
  fi
fi

# Individually unmount any remaining TARGET partitions still mounted elsewhere.
cleanup_target_mounts() {
  if [ ! -e "$TARGET" ]; then
    return
  fi
  mapfile -t TARGET_SOURCES < <(findmnt -rn -o SOURCE -S "${TARGET}p*" 2>/dev/null || true)
  local part
  for part in "${TARGET_SOURCES[@]}"; do
    if [ -z "$part" ]; then
      continue
    fi
    mapfile -t TARGET_POINTS < <(findmnt -rn -o TARGET --source "$part" 2>/dev/null || true)
    local point
    for point in "${TARGET_POINTS[@]}"; do
      if [ -z "$point" ]; then
        continue
      fi
      if attempt_umount "$point" "$part"; then
        continue
      fi
      log "Failed to unmount $point (source $part)."
      exit 1
    done
  done
}

cleanup_target_mounts

if command -v findmnt >/dev/null 2>&1; then
  if findmnt -rn --submounts "$MOUNT_BASE" >/dev/null 2>&1; then
    log "Some mounts still remain under $MOUNT_BASE after cleanup."
    exit 1
  fi
fi

if command -v udevadm >/dev/null 2>&1; then
  run_cmd udevadm settle
else
  vlog "udevadm not available; skipping device settle."
fi

if [ "$KEEP_DIRS" -eq 0 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: find $MOUNT_BASE -mindepth 1 -type d -empty -delete"
  else
    if [ -d "$MOUNT_BASE" ]; then
      find "$MOUNT_BASE" -mindepth 1 -type d -empty -delete 2>/dev/null || true
    fi
  fi
else
  vlog "Preserving empty mount directories as requested."
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "DRY-RUN: mkdir -p $MOUNT_BASE/boot/firmware"
else
  run_cmd mkdir -p "$MOUNT_BASE/boot/firmware"
fi

log "Cleanup complete."
exit 0
