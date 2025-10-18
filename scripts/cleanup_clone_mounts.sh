#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

DRY_RUN=0
VERBOSE=0
FORCE=0
KEEP_DIRS=0
TARGET=${TARGET:-/dev/nvme0n1}
MOUNT_BASE=${MOUNT_BASE:-/mnt/clone}
CLEANUP_READY=0
cleanup_invoked=0

log() {
  local IFS=' '
  printf '[clean-mounts] %s\n' "$*"
}

vlog() {
  if (( VERBOSE )); then
    log "$@"
  fi
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run] [--verbose|-v] [--force] [--keep-dirs] [--help]

Environment variables:
  TARGET      Target block device (default: ${TARGET})
  MOUNT_BASE  Base directory for clone mounts (default: ${MOUNT_BASE})
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Required command '$1' not found in PATH"
    exit 1
  fi
}

parse_args() {
  while (($#)); do
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

  if (($#)); then
    log "Unexpected argument: $1"
    usage
    exit 1
  fi
}

show_blockers() {
  local path="$1"
  if command -v fuser >/dev/null 2>&1; then
    local output
    if output=$(fuser -vm "$path" 2>/dev/null); then
      printf '%s\n' "$output"
      return 0
    fi
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof +f -- "$path" 2>/dev/null || true
  else
    log "Install 'psmisc' for fuser output or 'lsof' for detailed handles."
  fi
}

collect_blocker_pids() {
  local path="$1"
  if ! command -v fuser >/dev/null 2>&1; then
    return 1
  fi
  fuser -vm "$path" 2>/dev/null | awk 'NR>1 {print $2}' | sort -u
}

terminate_blockers() {
  local path="$1"
  local -a pids=()
  mapfile -t pids < <(collect_blocker_pids "$path" || true)
  if ((${#pids[@]} == 0)); then
    return 1
  fi
  log "Force flag set; sending SIGTERM to ${#pids[@]} process(es) holding ${path}."
  if (( DRY_RUN )); then
    log "DRY-RUN: kill -TERM ${pids[*]}"
  else
    kill -TERM "${pids[@]}" 2>/dev/null || true
    sleep 2
  fi
  mapfile -t pids < <(collect_blocker_pids "$path" || true)
  if ((${#pids[@]} == 0)); then
    return 0
  fi
  log "Escalating to SIGKILL for ${#pids[@]} process(es) still using ${path}."
  if (( DRY_RUN )); then
    log "DRY-RUN: kill -KILL ${pids[*]}"
  else
    kill -KILL "${pids[@]}" 2>/dev/null || true
    sleep 1
  fi
  mapfile -t pids < <(collect_blocker_pids "$path" || true)
  ((${#pids[@]} == 0))
}

print_mount_table() {
  local label="$1" query="$2"
  mapfile -t table < <(eval "$query" 2>/dev/null || true)
  if ((${#table[@]} == 0)); then
    vlog "No ${label} mounts detected."
    return
  fi
  log "${label}:"
  printf '  %-35s %s\n' "DEVICE" "MOUNTPOINT"
  local entry device point
  for entry in "${table[@]}"; do
    device=${entry%%:::*}
    point=${entry##*:::}
    printf '  %-35s %s\n' "$device" "$point"
  done
}

format_mounts() {
  local target="$1"
  findmnt -rn -o SOURCE,TARGET --submounts "$target" 2>/dev/null |
    awk '{print $1":::"$2}'
}

format_target_mounts() {
  local disk="$1"
  mapfile -t partitions < <(lsblk -nr -o PATH "$disk" 2>/dev/null || true)
  local part
  for part in "${partitions[@]:1}"; do
    if [ -z "$part" ]; then
      continue
    fi
    findmnt -rn -o SOURCE,TARGET --source "$part" 2>/dev/null |
      awk '{print $1":::"$2}'
  done
}

attempt_umount() {
  local mountpoint="$1"
  local label="$2"
  if (( DRY_RUN )); then
    log "DRY-RUN: umount ${mountpoint}"
    return 0
  fi
  if umount "$mountpoint" 2>/dev/null; then
    log "Unmounted ${mountpoint} (${label})."
    return 0
  fi
  local status=$?
  log "umount ${mountpoint} (${label}) failed with status ${status}."
  show_blockers "$mountpoint"
  if (( FORCE )); then
    terminate_blockers "$mountpoint" || true
    if umount "$mountpoint" 2>/dev/null; then
      log "Unmounted ${mountpoint} after terminating blockers."
      return 0
    fi
  fi
  return 1
}

lazy_umount() {
  local mountpoint="$1"
  if (( DRY_RUN )); then
    log "DRY-RUN: umount -l ${mountpoint}"
    return 0
  fi
  if umount -l "$mountpoint" 2>/dev/null; then
    log "Lazy unmounted ${mountpoint}; detaching when idle."
    return 0
  fi
  return 1
}

perform_cleanup() {
  local status=0

  print_mount_table "Mounts under ${MOUNT_BASE}" "format_mounts '${MOUNT_BASE}'"
  print_mount_table "Mounts sourced from ${TARGET}" "format_target_mounts '${TARGET}'"

  if findmnt -rn --submounts "$MOUNT_BASE" >/dev/null 2>&1; then
    if (( DRY_RUN )); then
      log "DRY-RUN: umount -R ${MOUNT_BASE}"
    else
      if ! umount -R "$MOUNT_BASE" 2>/dev/null; then
        log "Recursive unmount of ${MOUNT_BASE} failed."
        show_blockers "$MOUNT_BASE"
        if (( FORCE )); then
          terminate_blockers "$MOUNT_BASE" || true
          if ! umount -R "$MOUNT_BASE" 2>/dev/null; then
            log "Retrying lazy recursive unmount of ${MOUNT_BASE}."
            lazy_umount "$MOUNT_BASE" || status=1
          fi
        else
          log "Falling back to lazy recursive unmount of ${MOUNT_BASE}."
          lazy_umount "$MOUNT_BASE" || status=1
        fi
      else
        log "Recursively unmounted ${MOUNT_BASE}."
      fi
    fi
  fi

  mapfile -t partitions < <(lsblk -nr -o PATH "$TARGET" 2>/dev/null || true)
  local part
  for part in "${partitions[@]:1}"; do
    if [ -z "$part" ]; then
      continue
    fi
    mapfile -t points < <(findmnt -rn -o TARGET --source "$part" 2>/dev/null || true)
    local point
    for point in "${points[@]}"; do
      if [ -z "$point" ]; then
        continue
      fi
      if ! attempt_umount "$point" "$part"; then
        log "Unable to unmount ${point} sourced from ${part}."
        if ! lazy_umount "$point"; then
          status=1
        fi
      fi
    done
  done

  if findmnt -rn --submounts "$MOUNT_BASE" >/dev/null 2>&1; then
    log "Some mounts remain under ${MOUNT_BASE} after cleanup."
    show_blockers "$MOUNT_BASE"
    status=1
  fi

  if (( KEEP_DIRS )); then
    vlog "Preserving mount directories as requested."
  else
    if (( DRY_RUN )); then
      log "DRY-RUN: find ${MOUNT_BASE} -mindepth 1 -type d -empty -delete"
      log "DRY-RUN: rmdir ${MOUNT_BASE}"
    else
      if [ -d "$MOUNT_BASE" ]; then
        find "$MOUNT_BASE" -mindepth 1 -type d -empty -delete 2>/dev/null || true
        rmdir "$MOUNT_BASE" 2>/dev/null || true
      fi
    fi
  fi

  if (( status == 0 )); then
    log "Cleanup complete."
  else
    log "Cleanup finished with outstanding mounts or busy resources."
  fi
  return "$status"
}

cleanup() {
  local exit_code=$1
  if (( cleanup_invoked )); then
    exit "$exit_code"
  fi
  cleanup_invoked=1
  set +e
  local status=0
  if (( CLEANUP_READY )); then
    perform_cleanup
    status=$?
  fi
  trap - EXIT
  if (( exit_code == 0 )) && (( status != 0 )); then
    exit_code=$status
  fi
  exit "$exit_code"
}

trap 'cleanup "$?"' EXIT

parse_args "$@"
require_command findmnt
require_command lsblk
if ! [ -b "$TARGET" ]; then
  log "Target device ${TARGET} not present; continuing with mount cleanup only."
fi
CLEANUP_READY=1
log "Requested cleanup for TARGET=${TARGET} under ${MOUNT_BASE}."

exit 0
