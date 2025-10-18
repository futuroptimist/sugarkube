#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[preflight] %s\n' "$*"
}

fail() {
  local reason="$1"
  local next="$2"
  printf 'preflight: %s. Next: %s\n' "$reason" "$next" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "missing required command '$1'" "sudo apt-get install -y util-linux"
  fi
}

resolve_device() {
  local source="$1"
  if [[ -z "$source" ]]; then
    echo ""
    return 1
  fi
  if [[ "$source" == UUID=* ]]; then
    blkid -U "${source#UUID=}" || return 1
    return 0
  fi
  if [[ "$source" == PARTUUID=* ]]; then
    blkid -o device -t "${source}" || return 1
    return 0
  fi
  if [[ "$source" =~ ^/dev/ ]]; then
    readlink -f "$source"
    return 0
  fi
  echo ""
  return 1
}

device_basename() {
  local dev
  dev=$(resolve_device "$1") || return 1
  if [[ -z "$dev" ]]; then
    return 1
  fi
  local pk
  pk=$(lsblk -no PKNAME "$dev" 2>/dev/null || true)
  if [[ -n "$pk" ]]; then
    printf '/dev/%s\n' "$pk"
  else
    printf '%s\n' "$dev"
  fi
}

list_mounted_partitions() {
  local device="$1"
  mapfile -t mounted < <(
    lsblk -nr -o PATH,MOUNTPOINT "$device" 2>/dev/null | awk '$2!="" {print $1" -> "$2}'
  )
  printf '%s\n' "${mounted[@]:-}"
}

summarize_signatures() {
  local device="$1"
  wipefs -n "$device" 2>/dev/null || true
}

TARGET="${TARGET:-}"
WIPE="${WIPE:-0}"
MOUNT_BASE="${MOUNT_BASE:-/mnt/clone}"

require_cmd findmnt
require_cmd lsblk
require_cmd wipefs
require_cmd blkid

if [[ -z "$TARGET" ]]; then
  fail "TARGET is not set" "export TARGET=/dev/nvme0n1 just preflight"
fi

if [[ ! -b "$TARGET" ]]; then
  fail "TARGET $TARGET is not a block device" "lsblk -d --output NAME,PATH"
fi

target_device=$(resolve_device "$TARGET")
if [[ -z "$target_device" ]]; then
  fail "unable to resolve block device for $TARGET" "lsblk -d --output NAME,PATH"
fi

target_basename=$(device_basename "$target_device") || target_basename="$target_device"
current_source=$(findmnt -no SOURCE / 2>/dev/null || true)
if [[ -z "$current_source" ]]; then
  fail "unable to determine active root device" "findmnt -no SOURCE /"
fi

current_device=$(resolve_device "$current_source")
if [[ -z "$current_device" ]]; then
  fail "unable to resolve device for root source $current_source" "findmnt -no SOURCE /"
fi

current_basename=$(device_basename "$current_device") || current_basename="$current_device"
if [[ "$target_basename" == "$current_basename" ]]; then
  fail "refusing to operate on active root device ($target_basename)" \
    "set TARGET to the NVMe disk (e.g. /dev/nvme0n1)"
fi

mapfile -t mounted_parts < <(list_mounted_partitions "$target_device")
if [[ ${#mounted_parts[@]} -gt 0 ]]; then
  fail "target partitions are mounted: ${mounted_parts[*]}" \
    "sudo TARGET=$target_device MOUNT_BASE=$MOUNT_BASE just clean-mounts-hard"
fi

mapfile -t target_paths < <(lsblk -nr -o PATH "$target_device" 2>/dev/null || true)
declare -a signature_sources=("$target_device")
for path in "${target_paths[@]}"; do
  if [[ "$path" != "$target_device" ]]; then
    signature_sources+=("$path")
  fi
fi

signatures_found=()
for dev in "${signature_sources[@]}"; do
  sig_output=$(summarize_signatures "$dev")
  if [[ -n "$sig_output" ]]; then
    signatures_found+=("$dev:$sig_output")
  fi
done

if [[ ${#signatures_found[@]} -gt 0 ]]; then
  if [[ "$WIPE" != "1" ]]; then
    fail "found existing filesystem signatures on $target_device" \
      "WIPE=1 TARGET=$target_device just preflight"
  fi
  log "WIPE=1 detected; clearing stale signatures from ${#signature_sources[@]} device(s)."
  for dev in "${signature_sources[@]}"; do
    log "Running wipefs -a $dev"
    wipefs -a "$dev"
  done
else
  log "No existing signatures detected on $target_device."
fi

log "Target device: $target_device"
log "Active root device: $current_device"
log "Mount base for clone: $MOUNT_BASE"

cat <<CHECKLIST
[preflight] Checklist
  • Source root stays mounted at $current_device
  • Target disk $target_device is offline and ready
  • Next commands:
      1. sudo TARGET=$target_device WIPE=$WIPE just clone-ssd
      2. sudo TARGET=$target_device MOUNT_BASE=$MOUNT_BASE just verify-clone
      3. sudo just finalize-nvme
      4. sudo TARGET=$target_device MOUNT_BASE=$MOUNT_BASE just clean-mounts-hard (as needed)
  • Review docs: docs/storage/sd-to-nvme.md
CHECKLIST

log "Preflight complete."
