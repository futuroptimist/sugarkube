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

err() {
  printf '[clean-mounts] ERROR: %s\n' "$*" >&2
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run] [--verbose|-v] [--force] [--keep-dirs]

Flags:
  --dry-run      Show the actions that would be taken without making changes.
  --verbose, -v  Increase log verbosity.
  --force        Terminate processes holding mounts before unmounting.
  --keep-dirs    Do not remove empty mount directories during cleanup.
  --help         Show this help text and exit.

Environment:
  TARGET      Block device to inspect (default: ${TARGET})
  MOUNT_BASE  Mount base directory to clean (default: ${MOUNT_BASE})
USAGE
}

run_cmd() {
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: $*"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "RUN: $*"
  fi
  "$@"
}

run_ignore() {
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY (ignore errors): $*"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "RUN (ignore errors): $*"
  fi
  set +e
  "$@"
  local status=$?
  set -e
  if [ $status -ne 0 ]; then
    vlog "Ignoring failure (exit $status): $*"
  fi
  return 0
}

is_mounted_path() {
  findmnt -rn --target "$1" >/dev/null 2>&1
}

is_source_mounted() {
  findmnt -rn -S "$1" >/dev/null 2>&1
}

print_mount_table() {
  local -a rows=("$@")
  if [ ${#rows[@]} -eq 0 ]; then
    log "No matching mounts found."
    return
  fi
  log "Detected mounts:"
  local entry src target
  for entry in "${rows[@]}"; do
    src=${entry%% *}
    target=${entry#* }
    printf '[clean-mounts]   %-30s -> %s\n' "$src" "$target"
  done
}

collect_mount_points() {
  local -n _rows=$1
  shift
  local -n _points=$1
  shift
  local -A seen=()
  local entry target
  for entry in "${_rows[@]}"; do
    target=${entry#* }
    if [ -z "$target" ]; then
      continue
    fi
    if [ -z "${seen[$target]+x}" ]; then
      _points+=("$target")
      seen[$target]=1
    fi
  done
}

holder_pids_for_path() {
  local path=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -t +f -- "$path" 2>/dev/null | sort -u
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -m "$path" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u
    return
  fi
  return 0
}

show_holders() {
  local path=$1
  if command -v fuser >/dev/null 2>&1; then
    local output
    output=$(fuser -vm "$path" 2>&1 || true)
    if [ -n "$output" ]; then
      while IFS= read -r line; do
        log "holder: $line"
      done <<<"$output"
    fi
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    local output
    output=$(lsof +f -- "$path" 2>/dev/null || true)
    if [ -n "$output" ]; then
      while IFS= read -r line; do
        log "holder: $line"
      done <<<"$output"
    fi
  fi
}

collect_holder_pids() {
  local -a mounts=("$@")
  local -a pids=()
  local -A seen=()
  local path pid
  for path in "${mounts[@]}"; do
    while IFS= read -r pid; do
      if [ -z "$pid" ]; then
        continue
      fi
      if [ -z "${seen[$pid]+x}" ]; then
        pids+=("$pid")
        seen[$pid]=1
      fi
    done < <(holder_pids_for_path "$path")
  done
  printf '%s\n' "${pids[@]}"
}

terminate_pids() {
  local -a pids=("$@")
  if [ ${#pids[@]} -eq 0 ]; then
    return 0
  fi
  log "Terminating holder processes: ${pids[*]}"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  set +e
  kill -TERM "${pids[@]}" 2>/dev/null
  set -e
  sleep 2
  local -a remaining=()
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      remaining+=("$pid")
    fi
  done
  if [ ${#remaining[@]} -eq 0 ]; then
    return 0
  fi
  log "Escalating to SIGKILL for: ${remaining[*]}"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  set +e
  kill -KILL "${remaining[@]}" 2>/dev/null
  set -e
  sleep 1
  return 0
}

ensure_mount_base_exists() {
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: mkdir -p ${MOUNT_BASE}"
    return 0
  fi
  mkdir -p "$MOUNT_BASE"
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
        err "Unknown argument: $1"
        usage >&2
        exit 1
        ;;
    esac
    shift
  done
}

stop_systemd_units() {
  if ! command -v systemctl >/dev/null 2>&1; then
    vlog "systemctl not available; skipping automount stop."
    return
  fi
  local escaped
  if ! escaped=$(systemd-escape -p "$MOUNT_BASE" 2>/dev/null); then
    vlog "systemd-escape failed for ${MOUNT_BASE}; skipping unit stop."
    return
  fi
  local units=("${escaped}.automount" "${escaped}.mount")
  local unit
  for unit in "${units[@]}"; do
    vlog "Stopping systemd unit ${unit}"
    run_ignore systemctl stop "$unit"
  done
  local extra_units
  extra_units=$(systemctl list-units --type automount --all --no-legend 2>/dev/null | awk '{print $1" "$2}' | grep -F "$escaped" || true)
  if [ -n "$extra_units" ]; then
    while IFS= read -r line; do
      unit=${line%% *}
      if [ -n "$unit" ]; then
        vlog "Stopping related automount unit ${unit}"
        run_ignore systemctl stop "$unit"
      fi
    done <<<"$extra_units"
  fi
  extra_units=$(systemctl list-units --type mount --all --no-legend 2>/dev/null | awk '{print $1" "$2}' | grep -F "$escaped" || true)
  if [ -n "$extra_units" ]; then
    while IFS= read -r line; do
      unit=${line%% *}
      if [ -n "$unit" ]; then
        vlog "Stopping related mount unit ${unit}"
        run_ignore systemctl stop "$unit"
      fi
    done <<<"$extra_units"
  fi
}

umount_recursive() {
  local path=$1
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: umount -R $path"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "RUN: umount -R $path"
  fi
  set +e
  umount -R "$path"
  local status=$?
  set -e
  return $status
}

umount_target() {
  local path=$1
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: umount $path"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "RUN: umount $path"
  fi
  set +e
  umount "$path"
  local status=$?
  set -e
  return $status
}

lazy_umount() {
  local path=$1
  if [ "$DRY_RUN" -eq 1 ]; then
    vlog "DRY: umount -l $path"
    return 0
  fi
  if [ "$VERBOSE" -eq 1 ]; then
    log "RUN: umount -l $path"
  fi
  set +e
  umount -l "$path"
  local status=$?
  set -e
  return $status
}

post_cleanup() {
  if command -v udevadm >/dev/null 2>&1; then
    log "Waiting for udev events to settle"
    run_cmd udevadm settle
  else
    vlog "udevadm not present; skipping settle."
  fi
  if [ "$KEEP_DIRS" -eq 0 ] && [ -d "$MOUNT_BASE" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      vlog "DRY: find ${MOUNT_BASE} -mindepth 1 -type d -empty -delete"
    else
      find "$MOUNT_BASE" -mindepth 1 -type d -empty -print -delete | while IFS= read -r line; do
        log "Removed empty directory: $line"
      done
    fi
  fi
  ensure_mount_base_exists
  run_cmd mkdir -p "$MOUNT_BASE/boot/firmware"
}

main() {
  parse_args "$@"

  vlog "Configuration: TARGET=${TARGET}, MOUNT_BASE=${MOUNT_BASE}, DRY_RUN=${DRY_RUN}, FORCE=${FORCE}"

  if [ ! -d "$MOUNT_BASE" ]; then
    vlog "Mount base ${MOUNT_BASE} does not exist yet."
  fi

  local -a base_mounts=()
  local -a partition_mounts=()
  if command -v findmnt >/dev/null 2>&1; then
    readarray -t base_mounts < <(findmnt -rn -R -o SOURCE,TARGET --target "$MOUNT_BASE" 2>/dev/null || true)
  else
    err "findmnt is required for this script."
    exit 1
  fi

  if [ -b "$TARGET" ]; then
    readarray -t partition_mounts < <(findmnt -rn -S "${TARGET}p*" -o SOURCE,TARGET 2>/dev/null || true)
  else
    vlog "Block device ${TARGET} not present; skipping partition scan."
  fi

  local -a all_rows=()
  all_rows+=("${base_mounts[@]}")
  all_rows+=("${partition_mounts[@]}")
  if [ ${#all_rows[@]} -eq 0 ]; then
    log "Nothing mounted under ${MOUNT_BASE} or matching ${TARGET}p*."
    post_cleanup
    return 0
  fi

  print_mount_table "${all_rows[@]}"

  stop_systemd_units

  local -a mount_points=()
  collect_mount_points base_mounts mount_points
  collect_mount_points partition_mounts mount_points

  local -a holder_pids=()
  readarray -t holder_pids < <(collect_holder_pids "${mount_points[@]}")

  if [ ${#holder_pids[@]} -gt 0 ]; then
    log "Mounts are currently busy. Holders: ${holder_pids[*]}"
    local path
    for path in "${mount_points[@]}"; do
      show_holders "$path"
    done
    if [ "$FORCE" -eq 0 ]; then
      err "Mounts are busy. Re-run with --force to terminate holder processes."
      exit 1
    fi
    terminate_pids "${holder_pids[@]}"
    sleep 1
    readarray -t holder_pids < <(collect_holder_pids "${mount_points[@]}")
    if [ ${#holder_pids[@]} -gt 0 ]; then
      log "Some processes still hold mounts: ${holder_pids[*]}"
    fi
  fi

  local status
  if [ ${#base_mounts[@]} -gt 0 ] && is_mounted_path "$MOUNT_BASE"; then
    log "Unmounting ${MOUNT_BASE} recursively"
    status=0
    umount_recursive "$MOUNT_BASE" || status=$?
    if [ $status -ne 0 ]; then
      if [ $status -eq 32 ]; then
        err "Failed to unmount ${MOUNT_BASE}: busy"
        if [ "$FORCE" -eq 0 ]; then
          exit 1
        fi
        log "Retrying lazy unmount of ${MOUNT_BASE}"
        if ! lazy_umount "$MOUNT_BASE"; then
          err "Lazy unmount of ${MOUNT_BASE} failed"
          exit 1
        fi
      else
        log "Unmount of ${MOUNT_BASE} failed with status $status; attempting lazy detach"
        if ! lazy_umount "$MOUNT_BASE"; then
          err "Lazy unmount of ${MOUNT_BASE} failed"
          exit 1
        fi
      fi
    fi
  fi

  if [ -b "$TARGET" ]; then
    readarray -t partition_mounts < <(findmnt -rn -S "${TARGET}p*" -o SOURCE,TARGET 2>/dev/null || true)
    local entry source target
    for entry in "${partition_mounts[@]}"; do
      source=${entry%% *}
      target=${entry#* }
      if [ -z "$target" ]; then
        continue
      fi
      if ! is_source_mounted "$source"; then
        continue
      fi
      log "Unmounting partition ${source} from ${target}"
      status=0
      umount_target "$target" || status=$?
      if [ $status -ne 0 ]; then
        if [ $status -eq 32 ]; then
          err "Failed to unmount ${target}: busy"
          show_holders "$target"
          if [ "$FORCE" -eq 0 ]; then
            exit 1
          fi
          log "Retrying lazy unmount of ${target}"
          if ! lazy_umount "$target"; then
            err "Lazy unmount of ${target} failed"
            exit 1
          fi
        else
          if [ ! -e "$source" ]; then
            log "Device ${source} missing; using lazy unmount for stale mount"
            if ! lazy_umount "$target"; then
              err "Lazy unmount of ${target} failed"
              exit 1
            fi
          else
            log "Unmount of ${target} failed with status $status; attempting lazy detach"
            if ! lazy_umount "$target"; then
              err "Lazy unmount of ${target} failed"
              exit 1
            fi
          fi
        fi
      fi
    done
  fi

  post_cleanup
  log "Cleanup complete."
}

main "$@"
