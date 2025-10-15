#!/usr/bin/env bash
# clone_to_nvme.sh - Clone the running SD card to an attached NVMe/USB SSD and fix Bookworm boot UUIDs.
# Usage: sudo scripts/clone_to_nvme.sh [TARGET=/dev/nvme0n1]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/clone-to-nvme"
mkdir -p "${ARTIFACT_DIR}"
LOG_FILE="${ARTIFACT_DIR}/clone.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

sudo_prefix=()
if [[ $(id -u) -ne 0 ]]; then
  sudo_prefix=(sudo)
fi

ensure_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return 0
  fi
  echo "[clone] Installing geerlingguy/rpi-clone" >&2
  if ! curl -fsSL https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install | "${sudo_prefix[@]}" bash; then
    echo "[clone] Failed to install rpi-clone" >&2
    exit 1
  fi
}

resolve_target() {
  if [[ -n "${TARGET:-}" ]]; then
    local override="${TARGET}"
    if [[ "${override}" != /dev/* ]]; then
      override="/dev/${override}"
    fi
    printf '%s\n' "${override}"
    return 0
  fi
  "${SCRIPT_DIR}/detect_target_disk.sh"
}

validate_target() {
  local target="$1"
  if [[ ! -b "${target}" ]]; then
    echo "[clone] Target ${target} is not a block device" >&2
    exit 1
  fi
  if [[ "${target}" == /dev/mmcblk0* ]]; then
    echo "[clone] Refusing to operate on the boot SD card (${target})." >&2
    exit 1
  fi

  local mounted
  mounted=$(lsblk -nrpo NAME,MOUNTPOINT "${target}" | awk 'NR>1 && $2!="" {print $1 ":" $2}')
  if [[ -n "${mounted}" ]]; then
    echo "[clone] Target has mounted partitions:\n${mounted}" >&2
    exit 1
  fi
}

maybe_wipe() {
  local target="$1"
  if [[ "${WIPE:-0}" == "1" ]]; then
    echo "[clone] Wiping filesystem signatures from ${target}" >&2
    "${sudo_prefix[@]}" wipefs --all --force "${target}"
  fi
}

get_clone_mount() {
  if mountpoint -q /mnt/clone; then
    echo "/mnt/clone"
  else
    echo "[clone] Expected /mnt/clone to be mounted by rpi-clone" >&2
    exit 1
  fi
}

extract_uuid() {
  local device="$1" key="$2"
  blkid -s "${key}" -o value "${device}" 2>/dev/null || true
}

update_cmdline_root() {
  local cmdline_path="$1" new_value="$2" key="$3"
  if [[ ! -f "${cmdline_path}" ]]; then
    echo "[clone] cmdline.txt missing at ${cmdline_path}" >&2
    exit 1
  fi
  python3 - "$cmdline_path" "$key" "$new_value" <<'PY'
import pathlib, sys
cmdline = pathlib.Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
text = cmdline.read_text(encoding="utf-8").strip()
parts = text.split()
found = False
for idx, token in enumerate(parts):
    if token.startswith("root="):
        parts[idx] = f"root={key}={value}"
        found = True
        break
if not found:
    parts.append(f"root={key}={value}")
cmdline.write_text(" ".join(parts) + "\n", encoding="utf-8")
PY
}

update_fstab_entries() {
  local fstab_path="$1" root_device="$2" boot_device="$3" root_key="$4" boot_key="$5"
  if [[ ! -f "${fstab_path}" ]]; then
    echo "[clone] fstab missing at ${fstab_path}" >&2
    exit 1
  fi
  python3 - "$fstab_path" "$root_device" "$boot_device" "$root_key" "$boot_key" <<'PY'
import pathlib, sys
fstab = pathlib.Path(sys.argv[1])
root_value, boot_value = sys.argv[2], sys.argv[3]
root_key, boot_key = sys.argv[4], sys.argv[5]
lines = []
for line in fstab.read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.strip().startswith("#"):
        lines.append(line)
        continue
    parts = line.split()
    if len(parts) < 2:
        lines.append(line)
        continue
    mount = parts[1]
    if mount == "/":
        parts[0] = f"{root_key}={root_value}"
    elif mount in {"/boot/firmware", "/boot"}:
        parts[0] = f"{boot_key}={boot_value}"
    lines.append("\t".join(parts))
fstab.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

main() {
  local extra_args=("$@")
  ensure_rpi_clone
  local target
  target="$(resolve_target)"
  target="${target//$'\n'/}"
  if [[ -z "${target}" ]]; then
    echo "[clone] No target disk detected" >&2
    exit 1
  fi
  validate_target "${target}"
  maybe_wipe "${target}"

  echo "[clone] Starting unattended clone to ${target}" >&2
  "${sudo_prefix[@]}" rpi-clone -f -u "${target}" "${extra_args[@]}"

  local clone_mount
  clone_mount="$(get_clone_mount)"

  local root_source boot_source root_key boot_key
  root_source="$(findmnt -n -o SOURCE --target "${clone_mount}")"
  boot_source="$(findmnt -n -o SOURCE --target "${clone_mount}/boot" 2>/dev/null || true)"
  if [[ -z "${boot_source}" ]]; then
    boot_source="$(findmnt -n -o SOURCE --target "${clone_mount}/boot/firmware" 2>/dev/null || true)"
  fi

  if [[ -z "${root_source}" ]]; then
    echo "[clone] Unable to determine cloned root partition." >&2
    exit 1
  fi
  if [[ -z "${boot_source}" ]]; then
    echo "[clone] Unable to determine cloned boot partition." >&2
    exit 1
  fi

  root_key="PARTUUID"
  boot_key="PARTUUID"
  local root_uuid boot_uuid
  root_uuid="$(extract_uuid "${root_source}" "PARTUUID")"
  boot_uuid="$(extract_uuid "${boot_source}" "PARTUUID")"
  if [[ -z "${root_uuid}" ]]; then
    root_uuid="$(extract_uuid "${root_source}" "UUID")"
    root_key="UUID"
  fi
  if [[ -z "${boot_uuid}" ]]; then
    boot_uuid="$(extract_uuid "${boot_source}" "UUID")"
    boot_key="UUID"
  fi

  local firmware_dir="${clone_mount}/boot/firmware"
  if [[ ! -d "${firmware_dir}" ]]; then
    firmware_dir="${clone_mount}/boot"
  fi

  update_cmdline_root "${firmware_dir}/cmdline.txt" "${root_uuid}" "${root_key}"
  update_fstab_entries "${clone_mount}/etc/fstab" "${root_uuid}" "${boot_uuid}" "${root_key}" "${boot_key}"

  local bytes_cloned
  bytes_cloned=$("${sudo_prefix[@]}" blockdev --getsize64 "${target}")
  printf '[clone] Completed clone to %s (root %s=%s, boot %s=%s, bytes=%s)\n' \
    "${target}" "${root_key}" "${root_uuid}" "${boot_key}" "${boot_uuid}" "${bytes_cloned}"
}

main "$@"
