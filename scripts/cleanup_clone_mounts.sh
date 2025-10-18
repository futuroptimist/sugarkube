#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_NAME=$(basename "$0")
DRY_RUN=0
VERBOSE=0
FORCE=0
KEEP_DIRS=0
TARGET=${TARGET:-/dev/nvme0n1}
MOUNT_BASE=${MOUNT_BASE:-/mnt/clone}
CLEANUP_DONE=0
CLEANUP_STATUS=0

usage() {
  cat <<USAGE
Usage: ${SCRIPT_NAME} [--dry-run] [--verbose|-v] [--force] [--keep-dirs] [--help]

Environment variables:
  TARGET      Target block device (default: ${TARGET})
  MOUNT_BASE  Base directory for clone mounts (default: ${MOUNT_BASE})
USAGE
}

log() {
  local IFS=' '
  printf '[clean-mounts] %s\n' "$*"
}

vlog() {
  if [ "$VERBOSE" -eq 1 ]; then
    log "$@"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1"
    exit 1
  fi
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

require_cmd findmnt
require_cmd awk
require_cmd lsblk

collect_mounts() {
  BASE_MOUNTS=()
  TARGET_MOUNTS=()
  if findmnt -rn --submounts "$MOUNT_BASE" >/dev/null 2>&1; then
    while IFS= read -r line; do
      local target=${line%% *}
      local source=${line#* }
      BASE_MOUNTS+=("$source -> $target")
    done < <(findmnt -rn -o TARGET,SOURCE --submounts "$MOUNT_BASE" || true)
  fi
  if [ -b "$TARGET" ]; then
    while IFS= read -r name; do
      local device="/dev/${name}"
      while IFS= read -r line; do
        local target=${line%% *}
        local source=${line#* }
        TARGET_MOUNTS+=("$source -> $target")
      done < <(findmnt -rn -o TARGET,SOURCE --source "$device" 2>/dev/null || true)
    done < <(lsblk -nr -o NAME "$TARGET" 2>/dev/null || true)
  fi
}

print_mounts() {
  collect_mounts
  if [ "${#BASE_MOUNTS[@]}" -eq 0 ] && [ "${#TARGET_MOUNTS[@]}" -eq 0 ]; then
    log "No mounts detected under $MOUNT_BASE or sourced from $TARGET"
    return
  fi
  log "Detected mounts:"
  for entry in "${BASE_MOUNTS[@]}"; do
    printf '  %s\n' "$entry"
  done
  for entry in "${TARGET_MOUNTS[@]}"; do
    printf '  %s\n' "$entry"
  done
}

print_busy() {
  local path=$1
  if command -v fuser >/dev/null 2>&1; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY-RUN: fuser -vm $path"
    else
      fuser -vm "$path" || true
    fi
  else
    log "fuser not available to list busy processes for $path"
  fi
}

attempt_lazy() {
  local mount_point=$1
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: umount -l $mount_point"
    return 0
  fi
  if umount -l "$mount_point" 2>/dev/null; then
    log "Lazy unmounted $mount_point"
    log "Note: lazy unmount completes once the filesystem is no longer busy."
    return 0
  fi
  return 1
}

attempt_umount() {
  local mount_point=$1
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: umount $mount_point"
    return 0
  fi
  if umount "$mount_point" 2>/dev/null; then
    log "Unmounted $mount_point"
    return 0
  fi
  log "umount $mount_point failed"
  print_busy "$mount_point"
  if attempt_lazy "$mount_point"; then
    return 0
  fi
  if [ "$FORCE" -eq 1 ]; then
    log "--force set; retrying lazy unmount of $mount_point"
    attempt_lazy "$mount_point"
    return $?
  fi
  return 1
}

remove_empty_dir() {
  local dir=$1
  if [ ! -d "$dir" ]; then
    return
  fi
  if mountpoint -q "$dir" 2>/dev/null; then
    return
  fi
  if [ "$KEEP_DIRS" -eq 1 ]; then
    return
  fi
  if [ -n "$(find "$dir" -mindepth 1 -print -quit 2>/dev/null)" ]; then
    return
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: rmdir $dir"
  else
    rmdir "$dir" 2>/dev/null || true
  fi
}

finalize_directories() {
  remove_empty_dir "$MOUNT_BASE/boot/firmware"
  remove_empty_dir "$MOUNT_BASE/boot"
  remove_empty_dir "$MOUNT_BASE"
}

perform_cleanup() {
  local status=0

  print_mounts

  if [ "$DRY_RUN" -eq 0 ] && [ ! -d "$MOUNT_BASE" ]; then
    vlog "$MOUNT_BASE does not exist; skipping base unmount"
  else
    if findmnt -rn --submounts "$MOUNT_BASE" >/dev/null 2>&1; then
      if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: umount -R $MOUNT_BASE"
      else
        if ! umount -R "$MOUNT_BASE" 2>/dev/null; then
          log "umount -R $MOUNT_BASE failed"
          print_busy "$MOUNT_BASE"
          if ! attempt_lazy "$MOUNT_BASE"; then
            status=1
          fi
        else
          log "Recursively unmounted $MOUNT_BASE"
        fi
      fi
    fi
  fi

  if [ -b "$TARGET" ]; then
    declare -A seen_mounts=()
    while IFS= read -r name; do
      local device="/dev/${name}"
      while IFS= read -r mount_point; do
        if [ -z "$mount_point" ] || [ -n "${seen_mounts[$mount_point]:-}" ]; then
          continue
        fi
        seen_mounts[$mount_point]=1
        if ! attempt_umount "$mount_point"; then
          status=1
        fi
      done < <(findmnt -rn -o TARGET --source "$device" 2>/dev/null || true)
    done < <(lsblk -nr -o NAME "$TARGET" 2>/dev/null || true)
  fi

  if findmnt -rn --submounts "$MOUNT_BASE" >/dev/null 2>&1; then
    log "$MOUNT_BASE still has active mounts"
    print_busy "$MOUNT_BASE"
    status=1
  fi

  finalize_directories

  CLEANUP_STATUS=$status
  CLEANUP_DONE=1
  if [ "$status" -eq 0 ]; then
    log "Cleanup complete."
  else
    log "Cleanup finished with warnings."
  fi
}

# shellcheck disable=SC2317
cleanup_handler() {
  local status=$?
  if [ "$CLEANUP_DONE" -eq 1 ]; then
    exit "$status"
  fi
  set +e
  perform_cleanup
  if [ "$CLEANUP_STATUS" -ne 0 ] && [ "$status" -eq 0 ]; then
    status=$CLEANUP_STATUS
  fi
  exit "$status"
}

# shellcheck disable=SC2317
trap cleanup_handler EXIT

perform_cleanup
exit "$CLEANUP_STATUS"
