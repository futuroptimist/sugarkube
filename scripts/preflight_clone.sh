#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

TARGET=${TARGET:-}
WIPE=${WIPE:-0}
WIPE_CONFIRM=${WIPE_CONFIRM:-0}
boot_device=""
boot_parent=""

log() {
  printf '[preflight] %s\n' "$*"
}

fail() {
  printf '[preflight] error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command '$1' is not available"
  fi
}

canonical_device() {
  local path="$1"
  if [[ -z "$path" ]]; then
    return 1
  fi
  if [[ "$path" != /dev/* ]]; then
    path="/dev/${path}"
  fi
  readlink -f "$path"
}

require_cmd findmnt
require_cmd lsblk
require_cmd wipefs

if [[ -z "$TARGET" ]]; then
  fail "Set TARGET (e.g. /dev/nvme0n1) before running preflight"
fi

TARGET=$(canonical_device "$TARGET") || fail "Unable to resolve target device"
if [[ ! -b "$TARGET" ]]; then
  fail "Target $TARGET is not a block device"
fi

root_source=$(findmnt -no SOURCE /)
if [[ -z "$root_source" ]]; then
  fail "Unable to determine the root filesystem source"
fi
root_device=$(canonical_device "$root_source") || fail "Unable to resolve root device"
root_parent_name=$(lsblk -nr -o PKNAME "$root_device" 2>/dev/null || true)
if [[ -z "$root_parent_name" ]]; then
  fail "Unable to determine the parent device for $root_device"
fi
root_parent="/dev/${root_parent_name}"

if [[ "$TARGET" == "$root_device" || "$TARGET" == "$root_parent" ]]; then
  fail "Refusing to operate on the active root device ($root_device)"
fi

boot_source=$(findmnt -no SOURCE /boot 2>/dev/null || true)
if [[ -n "$boot_source" ]]; then
  boot_device=$(canonical_device "$boot_source" || true)
  if [[ -n "$boot_device" ]]; then
    boot_parent_name=$(lsblk -nr -o PKNAME "$boot_device" 2>/dev/null || true)
    if [[ -n "$boot_parent_name" ]]; then
      boot_parent="/dev/${boot_parent_name}"
      if [[ "$TARGET" == "$boot_device" || "$TARGET" == "$boot_parent" ]]; then
        fail "Refusing to operate on the active /boot device ($boot_device)"
      fi
    fi
  fi
fi

mapfile -t target_nodes < <(lsblk -nrpo NAME "$TARGET" 2>/dev/null || true)
if [[ ${#target_nodes[@]} -eq 0 ]]; then
  fail "Unable to enumerate partitions under $TARGET"
fi

mounted_points=()
for node in "${target_nodes[@]}"; do
  mapfile -t node_mounts < <(findmnt -rn -o TARGET --source "$node" 2>/dev/null || true)
  if [[ ${#node_mounts[@]} -gt 0 ]]; then
    for mp in "${node_mounts[@]}"; do
      if [[ -n "$mp" ]]; then
        mounted_points+=("$node -> $mp")
      fi
    done
  fi
done

if [[ ${#mounted_points[@]} -gt 0 ]]; then
  printf '[preflight] error: target partitions are mounted:%s' "\n" >&2
  printf '  %s\n' "${mounted_points[@]}" >&2
  exit 1
fi

existing_signatures=()
for node in "${target_nodes[@]}"; do
  mapfile -t sigs < <(wipefs --noheadings --parsable "$node" 2>/dev/null || true)
  if [[ ${#sigs[@]} -gt 0 ]]; then
    existing_signatures+=("$node")
  fi
done

if [[ ${#existing_signatures[@]} -gt 0 && "$WIPE" != "1" ]]; then
  printf '[preflight] error: existing filesystem signatures detected on:%s' "\n" >&2
  printf '  %s\n' "${existing_signatures[@]}" >&2
  printf '[preflight] hint: export WIPE=1 TARGET=%s just preflight\n' "$TARGET" >&2
  exit 1
fi

if [[ "$WIPE" == "1" ]]; then
  if [[ "$WIPE_CONFIRM" != "1" ]]; then
    fail "WIPE=1 requires WIPE_CONFIRM=1 to proceed with wipefs"
  fi
  log "Clearing filesystem signatures from $TARGET"
  wipefs -a "$TARGET"
  for node in "${target_nodes[@]}"; do
    if [[ "$node" != "$TARGET" && -b "$node" ]]; then
      wipefs -a "$node"
    fi
  done
  log "wipefs completed"
fi

model=$(lsblk -dn -o MODEL "$TARGET" 2>/dev/null | sed 's/[[:space:]]\+$//')
size=$(lsblk -dn -o SIZE "$TARGET" 2>/dev/null)
serial=$(lsblk -dn -o SERIAL "$TARGET" 2>/dev/null | sed 's/[[:space:]]\+$//')

printf '\n[preflight] Ready to clone:\n'
printf '  Source root:   %s\n' "$root_device"
if [[ -n "$boot_device" ]]; then
  printf '  Source boot:   %s\n' "$boot_device"
fi
printf '  Target:        %s (%s)\n' "$TARGET" "${size:-unknown size}"
if [[ -n "$model" ]]; then
  printf '  Model:         %s\n' "$model"
fi
if [[ -n "$serial" ]]; then
  printf '  Serial:        %s\n' "$serial"
fi
printf '  Signatures:    %s\n' "$( ([[ ${#existing_signatures[@]} -eq 0 ]] && printf 'clean') || printf 'cleared')"
if [[ "$WIPE" == "1" ]]; then
  printf '  Wipefs:        executed (WIPE=1)\n'
else
  printf '  Wipefs:        skipped (set WIPE=1 WIPE_CONFIRM=1 to initialize)\n'
fi

printf '\nChecklist:\n'
printf '  [ ] Backup important data on %s\n' "$TARGET"
printf '  [ ] Run: sudo WIPE=%s TARGET=%s just clone-ssd\n' "$WIPE" "$TARGET"
printf '  [ ] After clone: sudo TARGET=%s just verify-clone\n' "$TARGET"
printf '  [ ] Finish: sudo just finalize-nvme\n'

log "Preflight checks passed"
