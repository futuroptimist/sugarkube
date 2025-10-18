#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

TARGET=${TARGET:-/dev/nvme0n1}
MOUNT_BASE=${MOUNT_BASE:-/mnt/clone}
FORCE_LAZY=${FORCE_LAZY:-0}

log() {
  printf '[clean-mounts] %s\n' "$*"
}

fail() {
  printf '[clean-mounts] error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command '$1' is not available"
  fi
}

require_cmd findmnt
require_cmd umount
require_cmd lsblk

cleanup_wrapper() {
  local status=$?
  trap - EXIT
  # shellcheck disable=SC2317
  finalize_cleanup "$status"
}
trap cleanup_wrapper EXIT

list_blockers() {
  local path="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -vm "$path" 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof +f -- "$path" 2>/dev/null || true
  else
    return 1
  fi
}

try_umount() {
  local mount_point="$1"
  local label="$2"

  if ! findmnt -rn --target "$mount_point" >/dev/null 2>&1; then
    return 0
  fi

  log "Unmounting $label at $mount_point"
  if [[ "$mount_point" == "$MOUNT_BASE" ]]; then
    if umount -R "$mount_point" 2>/dev/null; then
      return 0
    fi
  fi

  if umount "$mount_point" 2>/dev/null; then
    return 0
  fi

  log "Primary unmount failed for $mount_point; inspecting blockers"
  list_blockers "$mount_point"

  if [[ "$mount_point" == "$MOUNT_BASE" ]]; then
    if umount -Rl "$mount_point" 2>/dev/null; then
      log "Lazy unmounted $mount_point recursively (will detach once idle)"
      return 0
    fi
  fi

  if umount -l "$mount_point" 2>/dev/null; then
    log "Lazy unmounted $mount_point (will detach once idle)"
    return 0
  fi

  if [[ "$FORCE_LAZY" == "1" ]]; then
    sleep 1
    if [[ "$mount_point" == "$MOUNT_BASE" ]]; then
      if umount -Rl "$mount_point" 2>/dev/null; then
        log "Lazy unmounted $mount_point recursively after retry"
        return 0
      fi
    fi
    if umount -l "$mount_point" 2>/dev/null; then
      log "Lazy unmounted $mount_point after retry"
      return 0
    fi
  fi

  log "Failed to unmount $mount_point"
  return 1
}

remove_if_empty() {
  local path="$1"
  if [[ -d "$path" ]] && [[ -z $(find "$path" -mindepth 1 -print -quit 2>/dev/null) ]]; then
    rmdir "$path" 2>/dev/null || true
  fi
}

finalize_cleanup() {
  local original_status="$1"
  local cleanup_status=0

  if [[ "$TARGET" != /dev/* ]]; then
    TARGET="/dev/${TARGET}"
  fi

  log "Scanning mounts for $TARGET under $MOUNT_BASE"
  mapfile -t base_mounts < <(findmnt -rn -o TARGET --submounts "$MOUNT_BASE" 2>/dev/null || true)
  if [[ ${#base_mounts[@]} -gt 0 ]]; then
    log "Found mounts under $MOUNT_BASE:"
    printf '  %s\n' "${base_mounts[@]}"
    if ! try_umount "$MOUNT_BASE" "$MOUNT_BASE"; then
      cleanup_status=1
    fi
  else
    log "No mounts detected under $MOUNT_BASE"
  fi

  if [[ -b "$TARGET" ]]; then
    mapfile -t target_nodes < <(lsblk -nrpo NAME "$TARGET" 2>/dev/null || true)
    for node in "${target_nodes[@]}"; do
      mapfile -t node_mounts < <(findmnt -rn -o TARGET --source "$node" 2>/dev/null || true)
      for mp in "${node_mounts[@]}"; do
        [[ -z "$mp" ]] && continue
        if [[ "$mp" == "$MOUNT_BASE"* ]]; then
          continue
        fi
        if ! try_umount "$mp" "$node"; then
          cleanup_status=1
        fi
      done
    done
  else
    log "Target $TARGET is not a block device; skipping partition scan"
  fi

  if findmnt -rn --target "$MOUNT_BASE" >/dev/null 2>&1; then
    log "Mounts remain under $MOUNT_BASE after cleanup"
    list_blockers "$MOUNT_BASE"
    cleanup_status=1
  fi

  remove_if_empty "$MOUNT_BASE/boot/firmware"
  remove_if_empty "$MOUNT_BASE/boot"
  remove_if_empty "$MOUNT_BASE"

  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle 2>/dev/null || true
  fi

  if [[ "$cleanup_status" -ne 0 ]]; then
    exit "$cleanup_status"
  fi

  exit "$original_status"
}

# The actual work is handled in finalize_cleanup via the EXIT trap.
true
