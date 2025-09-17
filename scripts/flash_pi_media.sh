#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="[flash-pi]"

log() {
  printf '%s %s\n' "$LOG_PREFIX" "$*"
}

err() {
  printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2
}

die() {
  err "$1"
  exit "${2:-1}"
}

usage() {
  cat <<'USAGE'
Flash a sugarkube image to removable media with verification.

Usage: flash_pi_media.sh [options]

Options:
  --image PATH     Image to flash (.img or .img.xz). Defaults to most recent
                   file in ~/sugarkube/images.
  --device PATH    Block device to write (e.g. /dev/sdb or /dev/disk2).
  --list           Print detected removable devices and exit.
  --dry-run        Print planned actions without writing to the device.
  --no-eject       Skip automatic eject/power-off after flashing.
  --yes            Skip interactive confirmation prompts.
  -h, --help       Show this help message.

Environment:
  SUGARKUBE_IMAGE_DIR      Overrides the default image search directory.
  SUGARKUBE_FAKE_DEVICE_FILE  When set, read device metadata from this file
                              instead of probing the system (used for tests).
USAGE
}

IMAGE_DIR="${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}"
IMAGE_PATH=""
DEVICE_PATH=""
LIST_ONLY=0
DRY_RUN=0
AUTO_CONFIRM=0
SKIP_EJECT=0
declare -a DEVICES=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image)
      [ "$#" -ge 2 ] || die "--image requires a path"
      IMAGE_PATH="$2"
      shift 2
      ;;
    --device)
      [ "$#" -ge 2 ] || die "--device requires a path"
      DEVICE_PATH="$2"
      shift 2
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --no-eject)
      SKIP_EJECT=1
      shift
      ;;
    --yes)
      AUTO_CONFIRM=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

PLATFORM="$(uname -s 2>/dev/null || echo unknown)"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing required command: $1"
  fi
}

available_sha_tool() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "shasum"
  else
    return 1
  fi
}

sha_stream_to_file() {
  local out_file="$1"
  local tool
  tool="$(available_sha_tool)"
  case "$tool" in
    sha256sum)
      sha256sum | awk '{print $1}' >"$out_file"
      ;;
    shasum)
      shasum -a 256 | awk '{print $1}' >"$out_file"
      ;;
    *)
      die "No SHA-256 utility available"
      ;;
  esac
}

numfmt_bytes() {
  local bytes="$1"
  if command -v numfmt >/dev/null 2>&1; then
    numfmt --to=iec --suffix=B "$bytes"
  else
    awk -v b="$bytes" 'BEGIN { split("B KB MB GB TB", u); i=1; while (b>=1024 && i<5){b/=1024;i++} printf "%.1f %s\n", b, u[i] }'
  fi
}

load_fake_devices() {
  local file="${SUGARKUBE_FAKE_DEVICE_FILE:-}"
  if [ -n "$file" ] && [ -f "$file" ]; then
    while IFS='|' read -r path model size transport removable; do
      [ -n "$path" ] || continue
      DEVICES+=("$path|${model:-Test Device}|${size:-0}|${transport:-usb}|${removable:-1}")
    done <"$file"
  fi
}

detect_linux_devices() {
  if ! command -v lsblk >/dev/null 2>&1; then
    return
  fi
  while IFS= read -r line; do
    eval "$line"
    [ "${TYPE:-}" = "disk" ] || continue
    local removable="${RM:-0}"
    if [ "$removable" != "1" ] && [ "${TRAN:-}" != "usb" ]; then
      continue
    fi
    DEVICES+=("${NAME}|${MODEL:-Unknown}|${SIZE:-0}|${TRAN:-usb}|${removable}")
  done < <(lsblk -bdnpo NAME,SIZE,MODEL,TYPE,RM,TRAN -P 2>/dev/null)
}

detect_macos_devices() {
  if ! command -v diskutil >/dev/null 2>&1; then
    return
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 is required to inspect macOS disks"
    return
  fi
  while IFS='|' read -r path model size transport removable; do
    [ -n "$path" ] || continue
    DEVICES+=("$path|$model|$size|$transport|$removable")
  done < <(python3 - <<'PY'
import plistlib
import subprocess

result = subprocess.run(
    ["diskutil", "list", "-plist", "external", "physical"],
    check=False,
    capture_output=True,
)
if result.returncode != 0:
    raise SystemExit(0)
plist = plistlib.loads(result.stdout or b"<plist></plist>")
devs = []
for disk in plist.get("AllDisksAndPartitions", []):
    ident = disk.get("DeviceIdentifier")
    if not ident:
        continue
    info = subprocess.run(
        ["diskutil", "info", "-plist", ident],
        check=False,
        capture_output=True,
    )
    if info.returncode != 0:
        continue
    detail = plistlib.loads(info.stdout or b"<plist></plist>")
    size = int(detail.get("TotalSize", 0))
    model = detail.get("MediaName") or detail.get("DeviceModel") or "External Disk"
    path = f"/dev/{ident}"
    print(f"{path}|{model}|{size}|external|1")
PY
  )
}

list_devices() {
  DEVICES=()
  load_fake_devices
  if [ "${#DEVICES[@]}" -eq 0 ]; then
    case "$PLATFORM" in
      Linux)
        detect_linux_devices
        ;;
      Darwin)
        detect_macos_devices
        ;;
      *)
        err "Unsupported platform for device detection"
        ;;
    esac
  fi
  if [ "${#DEVICES[@]}" -eq 0 ]; then
    err "No removable devices detected"
    return 1
  fi
  printf '%-3s %-18s %-12s %-20s %-8s\n' "#" "Device" "Capacity" "Model" "Bus"
  local idx=1
  for entry in "${DEVICES[@]}"; do
    IFS='|' read -r path model size transport removable <<<"$entry"
    local human
    human="$(numfmt_bytes "$size")"
    printf '%-3s %-18s %-12s %-20s %-8s\n' "$idx" "$path" "$human" "${model:0:20}" "${transport:-usb}"
    idx=$((idx + 1))
  done
}

select_device() {
  list_devices >/dev/null || die "No candidate devices found"
  if [ -n "$DEVICE_PATH" ]; then
    return
  fi
  printf '\nAvailable devices:\n'
  list_devices || die "No removable devices detected"
  printf '\n'
  while :; do
    read -r -p "Select device number: " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#DEVICES[@]}" ]; then
      DEVICE_PATH="$(printf '%s' "${DEVICES[$((choice - 1))]}" | cut -d'|' -f1)"
      break
    fi
    printf 'Invalid selection.\n'
  done
}

latest_image() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$dir" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).expanduser()
if not root.exists():
    raise SystemExit

def candidates():
    for entry in root.iterdir():
        if entry.suffix == ".img" or entry.name.endswith(".img.xz"):
            yield entry

try:
    latest = max(candidates(), key=lambda p: p.stat().st_mtime)
except ValueError:
    raise SystemExit
print(latest)
PY
  else
    ls -t "$dir"/*.img "$dir"/*.img.xz 2>/dev/null | head -n1 || true
  fi
}

require_image() {
  if [ -n "$IMAGE_PATH" ]; then
    [ -f "$IMAGE_PATH" ] || die "Image $IMAGE_PATH not found"
    return
  fi
  local candidate
  candidate="$(latest_image "$IMAGE_DIR")"
  [ -n "$candidate" ] || die "No image files found in $IMAGE_DIR"
  IMAGE_PATH="$candidate"
}

validate_device_size() {
  local size_bytes="$1"
  local required_bytes="$2"
  if [ "$size_bytes" -lt "$required_bytes" ]; then
    die "Device too small: $(numfmt_bytes "$size_bytes") < $(numfmt_bytes "$required_bytes")"
  fi
}

confirm_or_abort() {
  if [ "$DRY_RUN" -eq 1 ] || [ "$AUTO_CONFIRM" -eq 1 ]; then
    return
  fi
  printf '\nAbout to erase ALL data on %s.\n' "$DEVICE_PATH"
  read -r -p "Type the device path to continue: " response
  if [ "$response" != "$DEVICE_PATH" ]; then
    die "Confirmation mismatch; aborting"
  fi
}

require_root() {
  if [ "$DRY_RUN" -eq 1 ]; then
    return
  fi
  if [ "$(id -u)" -ne 0 ]; then
    die "Re-run as root or with sudo"
  fi
}

write_image() {
  local image="$1"
  local device="$2"
  local sha_file="$3"
  local size_file="$4"
  local dd_cmd
  local block_size=$((4 * 1024 * 1024))
  local decompress_cmd
  if [[ "$image" == *.xz ]]; then
    if command -v xz >/dev/null 2>&1; then
      decompress_cmd=(xz --decompress --stdout "$image")
    elif command -v unxz >/dev/null 2>&1; then
      decompress_cmd=(unxz -c "$image")
    else
      die "Install xz-utils to handle compressed images"
    fi
  else
    decompress_cmd=(cat "$image")
  fi
  case "$PLATFORM" in
    Darwin)
      dd_cmd=(dd of="$device" bs=4m conv=sync)
      ;;
    *)
      dd_cmd=(dd of="$device" bs="$block_size" conv=fsync status=progress)
      ;;
  esac
  log "Streaming image into $device"
  "${decompress_cmd[@]}" \
    | tee >( "${dd_cmd[@]}" ) \
    | tee >( sha_stream_to_file "$sha_file" ) \
    | wc -c >"$size_file"
}

read_back_sha() {
  local device="$1"
  local size_bytes="$2"
  local out_file="$3"
  local block_size=$((4 * 1024 * 1024))
  local blocks=$(( (size_bytes + block_size - 1) / block_size ))
  local dd_cmd
  case "$PLATFORM" in
    Darwin)
      dd_cmd=(dd if="$device" bs=4m count="$blocks")
      ;;
    *)
      dd_cmd=(dd if="$device" bs="$block_size" count="$blocks" iflag=fullblock status=progress)
      ;;
  esac
  log "Verifying data on $device"
  "${dd_cmd[@]}" 2>/dev/null | head -c "$size_bytes" | sha_stream_to_file "$out_file"
}

eject_device() {
  local device="$1"
  if [ "$SKIP_EJECT" -eq 1 ]; then
    return
  fi
  case "$PLATFORM" in
    Linux)
      if command -v udisksctl >/dev/null 2>&1; then
        udisksctl unmount -b "$device" >/dev/null 2>&1 || true
        udisksctl power-off -b "$device" >/dev/null 2>&1 || true
      elif command -v eject >/dev/null 2>&1; then
        eject "$device" >/dev/null 2>&1 || true
      fi
      ;;
    Darwin)
      diskutil eject "$device" >/dev/null 2>&1 || true
      ;;
  esac
}

main() {
  if [ "$LIST_ONLY" -eq 1 ]; then
    list_devices
    exit $?
  fi

  require_image
  select_device

  local selected_entry
  for entry in "${DEVICES[@]}"; do
    if [ "${entry%%|*}" = "$DEVICE_PATH" ]; then
      selected_entry="$entry"
      break
    fi
  done
  if [ -z "$selected_entry" ]; then
    die "Device $DEVICE_PATH is not removable or was not detected"
  fi

  IFS='|' read -r _ model size_bytes transport removable <<<"$selected_entry"

  if [ -z "$size_bytes" ]; then
    die "Failed to determine device size for $DEVICE_PATH"
  fi

  require_cmd dd
  require_cmd tee
  if ! available_sha_tool >/dev/null 2>&1; then
    die "Install sha256sum (coreutils) or shasum"
  fi

  local tmp_sha tmp_size tmp_verify
  tmp_sha="$(mktemp)"
  tmp_size="$(mktemp)"
  tmp_verify="$(mktemp)"
  trap 'rm -f "$tmp_sha" "$tmp_size" "$tmp_verify"' EXIT

  log "Using image $IMAGE_PATH"
  log "Target device $DEVICE_PATH ($(numfmt_bytes "$size_bytes") ${model:+- $model})"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run complete"
    exit 0
  fi

  require_root
  confirm_or_abort

  write_image "$IMAGE_PATH" "$DEVICE_PATH" "$tmp_sha" "$tmp_size"
  sync
  local bytes
  bytes="$(awk '{print $1}' "$tmp_size")"
  [ -n "$bytes" ] || die "Failed to capture write size"
  validate_device_size "$size_bytes" "$bytes"
  read_back_sha "$DEVICE_PATH" "$bytes" "$tmp_verify"

  local expected actual
  expected="$(cat "$tmp_sha")"
  actual="$(cat "$tmp_verify")"
  if [ "$expected" != "$actual" ]; then
    die "SHA-256 mismatch after flashing"
  fi
  log "Verification successful ($expected)"
  eject_device "$DEVICE_PATH"
  log "Flashing complete"
}

main "$@"
