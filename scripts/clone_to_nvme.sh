#!/usr/bin/env bash
# clone_to_nvme.sh - Clone the active SD card to an attached NVMe/SSD using rpi-clone.
# Usage: sudo ./scripts/clone_to_nvme.sh [TARGET=/dev/nvme0n1] [WIPE=1]
# Installs the maintained rpi-clone fork when needed, applies Bookworm UUID fixups,
# and writes logs to artifacts/clone-to-nvme.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/artifacts/clone-to-nvme"
LOG_FILE="${ARTIFACT_DIR}/clone.log"
DETECT_SCRIPT="${ROOT_DIR}/scripts/detect_target_disk.sh"
mkdir -p "${ARTIFACT_DIR}"
: >"${LOG_FILE}"

log() {
  printf '%s\n' "$1" | tee -a "${LOG_FILE}"
}

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log "Required command '${cmd}' missing"
    exit 1
  fi
}

install_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return
  fi
  log "[clone] Installing geerlingguy/rpi-clone"
  curl -fsSL https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install \
    | sudo bash | tee -a "${LOG_FILE}"
}

partition_path() {
  local disk="$1"
  local index="$2"
  if [[ "${disk}" =~ [0-9]$ ]]; then
    echo "${disk}p${index}"
  else
    echo "${disk}${index}"
  fi
}

ensure_not_mounted() {
  local disk="$1"
  local has_mounts=0
  while IFS= read -r line; do
    local mountpoint
    mountpoint=$(printf '%s' "${line}" | awk '{print $2}')
    if [ -n "${mountpoint}" ] && [ "${mountpoint}" != "[SWAP]" ]; then
      has_mounts=1
      break
    fi
  done < <(lsblk -nr -o NAME,MOUNTPOINT "${disk}")
  if [ "${has_mounts}" -eq 1 ]; then
    log "[clone] ${disk} has mounted partitions; aborting"
    exit 1
  fi
}

check_capacity() {
  local target="$1"
  local root_used target_size
  root_used=$(df --block-size=1 / | awk 'NR==2 {print $3}')
  target_size=$(lsblk -nb -o SIZE "${target}")
  if [ -z "${target_size}" ] || [ "${target_size}" -eq 0 ]; then
    log "[clone] Unable to determine size for ${target}"
    exit 1
  fi
  if [ "${target_size}" -le "${root_used}" ]; then
    log "[clone] Target ${target} (${target_size} bytes) smaller than root usage (${root_used} bytes)"
    exit 1
  fi
}

wipe_signatures() {
  local target="$1"
  if ! command -v wipefs >/dev/null 2>&1; then
    log "[clone] wipefs not available; cannot WIPE"
    exit 1
  fi
  log "[clone] Wiping old signatures on ${target}"
  sudo wipefs --all --force "${target}" | tee -a "${LOG_FILE}"
}

update_cmdline() {
  local cmdline_path="$1"
  local partuuid="$2"
  if [ ! -f "${cmdline_path}" ]; then
    log "[clone] cmdline.txt missing at ${cmdline_path}"
    return
  fi
  python3 <<PY
from pathlib import Path
import re
import sys
path = Path("${cmdline_path}")
content = path.read_text()
if 'root=' not in content:
    sys.exit(0)
updated = re.sub(r"root=\S+", f"root=PARTUUID=${partuuid}", content)
if updated != content:
    path.write_text(updated)
PY
  log "[clone] Updated cmdline root PARTUUID"
}

update_fstab() {
  local fstab_path="$1"
  local boot_partuuid="$2"
  local root_partuuid="$3"
  if [ ! -f "${fstab_path}" ]; then
    log "[clone] fstab missing at ${fstab_path}"
    return
  fi
  python3 <<PY
from pathlib import Path
import sys
path = Path("${fstab_path}")
boot = "PARTUUID=${boot_partuuid}"
root = "PARTUUID=${root_partuuid}"
lines = []
for line in path.read_text().splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        lines.append(line)
        continue
    parts = line.split()
    if len(parts) < 2:
        lines.append(line)
        continue
    if parts[1] == "/boot/firmware":
        parts[0] = boot
        line = "\t".join(parts)
    elif parts[1] == "/":
        parts[0] = root
        line = "\t".join(parts)
    lines.append(line)
path.write_text("\n".join(lines) + "\n")
PY
  log "[clone] Applied fstab PARTUUID updates"
}

post_clone_fixups() {
  local target="$1"
  local mount_base="/mnt/clone"
  local boot_part root_part
  boot_part="$(partition_path "${target}" 1)"
  root_part="$(partition_path "${target}" 2)"
  local boot_uuid root_uuid boot_partuuid root_partuuid
  boot_uuid=$(sudo blkid -s UUID -o value "${boot_part}")
  root_uuid=$(sudo blkid -s UUID -o value "${root_part}")
  boot_partuuid=$(sudo blkid -s PARTUUID -o value "${boot_part}")
  root_partuuid=$(sudo blkid -s PARTUUID -o value "${root_part}")
  local cmdline_path fstab_path
  cmdline_path="${mount_base}/boot/firmware/cmdline.txt"
  if [ ! -f "${cmdline_path}" ]; then
    cmdline_path="${mount_base}/boot/cmdline.txt"
  fi
  fstab_path="${mount_base}/etc/fstab"
  update_cmdline "${cmdline_path}" "${root_partuuid}"
  update_fstab "${fstab_path}" "${boot_partuuid}" "${root_partuuid}"
  log "[clone] Target boot UUID=${boot_uuid}, root UUID=${root_uuid}"
  printf '%s\n' "${boot_uuid}" >"${ARTIFACT_DIR}/boot.uuid"
  printf '%s\n' "${root_uuid}" >"${ARTIFACT_DIR}/root.uuid"
}

main() {
  require_command curl
  require_command lsblk
  require_command df
  require_command python3
  install_rpi_clone

  local target="${TARGET:-}" detected
  if [ -z "${target}" ]; then
    if [ ! -x "${DETECT_SCRIPT}" ]; then
      log "[clone] Target detection script missing at ${DETECT_SCRIPT}"
      exit 1
    fi
    if ! detected=$("${DETECT_SCRIPT}"); then
      log "[clone] Failed to detect target disk"
      exit 1
    fi
    target="${detected}"
  fi
  if [[ "${target}" == "/dev/mmcblk0"* ]]; then
    log "[clone] Refusing to operate on boot media ${target}"
    exit 1
  fi
  ensure_not_mounted "${target}"
  check_capacity "${target}"

  if [ "${WIPE:-0}" = "1" ]; then
    wipe_signatures "${target}"
  fi

  log "[clone] Starting rpi-clone to ${target}"
  sudo rpi-clone -f -u "${target}" | tee -a "${LOG_FILE}"
  post_clone_fixups "${target}"
  local clone_bytes
  clone_bytes=$(sudo blockdev --getsize64 "${target}" 2>/dev/null || echo "unknown")
  log "[clone] Clone completed: target=${target}, bytes=${clone_bytes}"
  printf 'target=%s bytes=%s\n' "${target}" "${clone_bytes}" | tee "${ARTIFACT_DIR}/summary.txt"
}

main "$@"
