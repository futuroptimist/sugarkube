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

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run] [--verbose|-v] [--force] [--keep-dirs]

Safely unmount residual clone mounts and tidy their mount directories.

Environment variables:
  TARGET      Block device to inspect for partitions (default: /dev/nvme0n1)
  MOUNT_BASE  Base directory for clone mounts (default: /mnt/clone)

Flags:
  --dry-run     Only print intended actions
  --verbose|-v  Increase log verbosity
  --force       Terminate blocking processes if required
  --keep-dirs   Preserve empty mount directories
  --help        Show this message
USAGE
}

fail() {
  log "Error: $*"
  exit 1
}

is_mounted() {
  local path=$1
  if command -v findmnt >/dev/null 2>&1; then
    if findmnt -rn --target "$path" >/dev/null 2>&1; then
      return 0
    fi
  elif command -v mountpoint >/dev/null 2>&1; then
    if mountpoint -q "$path" 2>/dev/null; then
      return 0
    fi
  elif grep -F -- " $path " /proc/mounts >/dev/null 2>&1; then
    return 0
  fi
  return 1
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
        usage >&2
        fail "Unknown argument: $1"
        ;;
    esac
    shift
  done
  if [ "$#" -gt 0 ]; then
    usage >&2
    fail "Unexpected positional arguments: $*"
  fi
}

read_mounts() {
  local entry source target
  if command -v findmnt >/dev/null 2>&1; then
    while IFS= read -r entry; do
      target=${entry#TARGET="}
      target=${target%%"*}
      source=${entry##*SOURCE="}
      source=${source%"*}
      printf '%s|%s\n' "$source" "$target"
    done < <(findmnt -rn -o TARGET,SOURCE -P)
  else
    while IFS= read -r source _ target _; do
      printf '%s|%s\n' "$source" "$target"
    done < <(mount)
  fi
}

list_relevant_mounts() {
  local pair source target
  declare -A seen=()
  while IFS= read -r pair; do
    source=${pair%%|*}
    target=${pair#*|}
    if [ -z "$source" ] || [ -z "$target" ]; then
      continue
    fi
    if [[ "$target" == "$MOUNT_BASE" ]] || [[ "$target" == "$MOUNT_BASE"/* ]]; then
      if [ -z "${seen["$source|$target"]:-}" ]; then
        seen["$source|$target"]=1
        printf '%s|%s\n' "$source" "$target"
      fi
    elif [[ "$source" == "$TARGET" ]] || [[ "$source" == "$TARGET"p* ]]; then
      if [ -z "${seen["$source|$target"]:-}" ]; then
        seen["$source|$target"]=1
        printf '%s|%s\n' "$source" "$target"
      fi
    fi
  done < <(read_mounts)
}

print_mount_table() {
  local mounts=()
  mapfile -t mounts < <(list_relevant_mounts)
  if [ "${#mounts[@]}" -eq 0 ]; then
    log "No mounts found under ${MOUNT_BASE} or for ${TARGET} partitions."
    return 1
  fi
  log "Detected mounts:"
  local entry source target
  for entry in "${mounts[@]}"; do
    source=${entry%%|*}
    target=${entry#*|}
    printf '  %-25s -> %s\n' "$source" "$target"
  done
  return 0
}

stop_automounts() {
  if ! command -v systemctl >/dev/null 2>&1; then
    vlog "systemctl not available; skipping automount shutdown."
    return
  fi

  local base_unit escaped unit
  escaped=$MOUNT_BASE
  if command -v systemd-escape >/dev/null 2>&1; then
    base_unit=$(systemd-escape --path "$MOUNT_BASE")
  else
    base_unit=${MOUNT_BASE#/}
    base_unit=${base_unit//\//-}
  fi

  for unit in "mnt-clone.automount" "mnt-clone.mount" \
    "${base_unit}.automount" "${base_unit}.mount"; do
    if [ -n "$unit" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        vlog "DRY: systemctl stop $unit"
      else
        systemctl stop "$unit" >/dev/null 2>&1 || true
      fi
    fi
  done

  local filter
  filter=$base_unit
  if [ -n "$filter" ]; then
    while IFS= read -r unit; do
      if [ -z "$unit" ] || [[ "$unit" != *"$filter"* ]]; then
        continue
      fi
      if [ "$DRY_RUN" -eq 1 ]; then
        vlog "DRY: systemctl stop $unit"
      else
        systemctl stop "$unit" >/dev/null 2>&1 || true
      fi
    done < <(
      systemctl list-units --all --type=automount --type=mount --no-legend 2>/dev/null |
        awk '{print $1}'
    )
  fi
}

collect_blocker_pids() {
  local -n __pids=$1
  local tool output
  __pids=()
  if command -v lsof >/dev/null 2>&1; then
    tool="lsof"
    while IFS= read -r pid; do
      if [ -n "$pid" ]; then
        __pids+=("$pid")
      fi
    done < <(lsof -t +f -- "$MOUNT_BASE" 2>/dev/null | sort -u)
  elif command -v fuser >/dev/null 2>&1; then
    tool="fuser"
    output=$(fuser -vm "$MOUNT_BASE" 2>/dev/null || true)
    if [ -n "$output" ]; then
      printf '%s\n' "$output"
    fi
    while IFS= read -r pid; do
      if [ -n "$pid" ]; then
        __pids+=("$pid")
      fi
    done < <(
      printf '%s\n' "$output" |
        awk 'NR>1 {for(i=1;i<=NF;i++) if($i ~ /^[0-9]+$/) print $i}' |
        sort -u
    )
  else
    tool=""
  fi

  if [ -z "$tool" ]; then
    vlog "Neither lsof nor fuser available; skipping blocker inspection."
    return 0
  fi

  if [ "${#__pids[@]}" -gt 0 ]; then
    log "Mount ${MOUNT_BASE} is busy (detected via ${tool})."
    if [ "$tool" = "lsof" ]; then
      while IFS= read -r line; do
        [ -n "$line" ] && printf '[clean-mounts]   %s\n' "$line"
      done < <(lsof +f -- "$MOUNT_BASE" 2>/dev/null)
    fi
  fi
}

terminate_blockers() {
  local -a pids=()
  collect_blocker_pids pids
  if [ "${#pids[@]}" -eq 0 ]; then
    return 0
  fi
  log "Blocking PIDs: ${pids[*]}"
  if [ "$FORCE" -eq 0 ]; then
    log "Re-run with --force to terminate blocking processes."
    return 1
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: kill -TERM ${pids[*]}"
    vlog "DRY: kill -KILL ${pids[*]} (if needed)"
    return 0
  fi
  log "Sending SIGTERM to blockers."
  kill -TERM "${pids[@]}" 2>/dev/null || true
  sleep 2
  local -a remaining=()
  collect_blocker_pids remaining
  if [ "${#remaining[@]}" -eq 0 ]; then
    return 0
  fi
  log "Escalating with SIGKILL to remaining PIDs: ${remaining[*]}"
  kill -KILL "${remaining[@]}" 2>/dev/null || true
  sleep 1
  collect_blocker_pids remaining
  if [ "${#remaining[@]}" -gt 0 ]; then
    log "Warning: processes still holding ${MOUNT_BASE}: ${remaining[*]}"
    return 1
  fi
  return 0
}

umount_with_fallback() {
  local target=$1
  local recursive=$2
  local output
  local status
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$recursive" = "1" ]; then
      vlog "DRY: umount -R -- $target"
    else
      vlog "DRY: umount -- $target"
    fi
    return 0
  fi

  if [ "$recursive" = "1" ]; then
    if output=$(umount -R -- "$target" 2>&1); then
      return 0
    fi
  else
    if output=$(umount -- "$target" 2>&1); then
      return 0
    fi
  fi

  status=$?
  if printf '%s' "$output" | grep -qi 'not mounted'; then
    vlog "$target already unmounted."
    return 0
  fi

  if printf '%s' "$output" | grep -qi 'busy'; then
    log "Unmount of $target reported busy."
    return 32
  fi

  log "Unmount of $target failed (${output:-status $status}). Attempting lazy unmount."
  if umount -l -- "$target" 2>/dev/null; then
    log "Lazy unmounted $target."
    return 0
  fi
  log "Lazy unmount of $target failed."
  return $status
}

cleanup_mount_dirs() {
  if [ "$KEEP_DIRS" -eq 1 ]; then
    return
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: find ${MOUNT_BASE} -mindepth 1 -type d -empty -delete"
    vlog "DRY: mkdir -p ${MOUNT_BASE}/boot/firmware"
    return
  fi
  if [ -d "$MOUNT_BASE" ]; then
    find "$MOUNT_BASE" -mindepth 1 -type d -empty -delete 2>/dev/null || true
  fi
  mkdir -p "$MOUNT_BASE/boot/firmware"
}

settle_devices() {
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: udevadm settle"
    return
  fi
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle >/dev/null 2>&1 || true
  else
    vlog "udevadm not available; skipping settle."
  fi
}

main() {
  parse_args "$@"
  log "Inspecting mounts under ${MOUNT_BASE} and device ${TARGET}."
  local mounts_found=0
  if print_mount_table; then
    mounts_found=1
  fi

  stop_automounts

  if [ "$mounts_found" -eq 1 ]; then
    if ! terminate_blockers; then
      fail "Mounts are busy."
    fi
  fi

  local status
  if is_mounted "$MOUNT_BASE"; then
    log "Unmounting ${MOUNT_BASE} (recursive)."
    if umount_with_fallback "$MOUNT_BASE" 1; then
      status=0
    else
      status=$?
    fi
    if [ "$status" -eq 32 ]; then
      fail "${MOUNT_BASE} is still busy after attempting to terminate blockers."
    elif [ "$status" -ne 0 ]; then
      fail "Failed to unmount ${MOUNT_BASE}."
    fi
  else
    vlog "${MOUNT_BASE} is not currently a mountpoint."
  fi

  local pair source target
  while IFS= read -r pair; do
    source=${pair%%|*}
    target=${pair#*|}
    if [[ "$source" == "$TARGET" ]] || [[ "$source" == "$TARGET"p* ]]; then
      if is_mounted "$target"; then
        log "Unmounting partition $source from $target."
        if umount_with_fallback "$target" 0; then
          status=0
        else
          status=$?
        fi
        if [ "$status" -eq 32 ]; then
          fail "$target remains busy (source $source)."
        elif [ "$status" -ne 0 ]; then
          fail "Failed to unmount $target (source $source)."
        fi
      else
        vlog "$target is not currently mounted."
      fi
    fi
  done < <(list_relevant_mounts)

  settle_devices
  cleanup_mount_dirs
  log "Cleanup complete."
}

main "$@"
