#!/usr/bin/env bats

setup() {
  export TEST_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "${TEST_BIN}"
  export PATH="${TEST_BIN}:$PATH"

  export RPI_CLONE_CALL_LOG="$BATS_TEST_TMPDIR/rpi_clone_calls.log"
  cat >"${TEST_BIN}/rpi-clone" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "$*" >>"${RPI_CLONE_CALL_LOG}"
if [[ "$*" == *"-U"* ]]; then
  exit 0
fi
printf 'Unattended -u option not allowed when initializing\n' >&2
exit 1
STUB
  chmod +x "${TEST_BIN}/rpi-clone"

  export REAL_LSBLK="$(command -v lsblk)"
  export REAL_FINDMNT="$(command -v findmnt)"
  export REAL_BLKID="$(command -v blkid)"

  cat >"${TEST_BIN}/lsblk" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "-nb" && "${2:-}" == "-o" && "${3:-}" == "SIZE" ]]; then
  if [[ "${4:-}" == "/dev/testdisk" ]]; then
    echo "100000000000"
    exit 0
  fi
fi
if [[ "${1:-}" == "-nr" && "${2:-}" == "-o" && "${3:-}" == "NAME,MOUNTPOINT" && "${4:-}" == "/dev/testdisk" ]]; then
  exit 0
fi
if [[ "${1:-}" == "-nr" && "${2:-}" == "-o" && "${3:-}" == "PATH" && "${4:-}" == "/dev/testdisk" ]]; then
  printf "/dev/testdisk\n/dev/testdiskp1\n/dev/testdiskp2\n"
  exit 0
fi
exec "${REAL_LSBLK}" "$@"
STUB
  chmod +x "${TEST_BIN}/lsblk"

  export FINDMNT_STATE="$BATS_TEST_TMPDIR/findmnt_state"
  touch "${FINDMNT_STATE}"
  cat >"${TEST_BIN}/findmnt" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
state="${FINDMNT_STATE}"
lookup() {
  local mp="$1"
  if [[ -f "$state" ]]; then
    awk -F'|' -v target="$mp" '$1==target {print $2; exit}' "$state"
  fi
}
if [[ "$1" == "-rn" && "$2" == "-o" && "$3" == "TARGET" ]]; then
  mp="$4"
  if [[ -n "$(lookup "$mp")" ]]; then
    echo "$mp"
    exit 0
  fi
  exit 1
fi
if [[ "$1" == "-rn" && "$2" == "-o" && "$3" == "SOURCE" ]]; then
  mp="$4"
  src="$(lookup "$mp")"
  if [[ -n "$src" ]]; then
    echo "$src"
    exit 0
  fi
  exit 1
fi
if [[ "$1" == "-no" && "$2" == "SOURCE" ]]; then
  mp="$3"
  src="$(lookup "$mp")"
  if [[ -n "$src" ]]; then
    echo "$src"
    exit 0
  fi
  exit 1
fi
exec "${REAL_FINDMNT}" "$@"
STUB
  chmod +x "${TEST_BIN}/findmnt"

  cat >"${TEST_BIN}/mount" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
state="${FINDMNT_STATE}"

while (($# > 0)); do
  case "$1" in
    -o)
      shift 2
      ;;
    -t)
      shift 2
      ;;
    --*)
      shift
      ;;
    -*)
      shift
      ;;
    *)
      break
      ;;
  esac
done

if (($# < 2)); then
  echo "mount stub received insufficient arguments" >&2
  exit 1
fi

device="$1"
mount_point="$2"

mkdir -p "$mount_point"
if [[ -f "$state" ]]; then
  grep -v "^${mount_point}|" "$state" >"${state}.tmp" || true
else
  : >"${state}.tmp"
fi
printf '%s|%s\n' "$mount_point" "$device" >>"${state}.tmp"
mv "${state}.tmp" "$state"
exit 0
STUB
  chmod +x "${TEST_BIN}/mount"

  cat >"${TEST_BIN}/blkid" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == "-s" && "$2" == "UUID" && "$3" == "-o" && "$4" == "value" ]]; then
  case "$5" in
    /dev/testdiskp2) echo "root-uuid" ; exit 0 ;;
    /dev/testdiskp1) echo "boot-uuid" ; exit 0 ;;
  esac
fi
if [[ "$1" == "-s" && "$2" == "PARTUUID" && "$3" == "-o" && "$4" == "value" ]]; then
  case "$5" in
    /dev/testdiskp2) echo "root-partuuid" ; exit 0 ;;
    /dev/testdiskp1) echo "boot-partuuid" ; exit 0 ;;
  esac
fi
exec "${REAL_BLKID}" "$@"
STUB
  chmod +x "${TEST_BIN}/blkid"

  cat >"${TEST_BIN}/wipefs" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
exit 0
STUB
  chmod +x "${TEST_BIN}/wipefs"

  export ALLOW_NON_ROOT=1
  export ALLOW_FAKE_BLOCK=1
  export CLONE_MOUNT="$BATS_TEST_TMPDIR/clone"
  mkdir -p "$CLONE_MOUNT/boot/firmware" "$CLONE_MOUNT/etc"

  cat >"$CLONE_MOUNT/boot/firmware/cmdline.txt" <<'CFG'
console=serial0,115200 console=tty1 root=PARTUUID=old-root rw
overlayroot=tmpfs:swap=1
CFG
  cat >"$CLONE_MOUNT/etc/fstab" <<'CFG'
PARTUUID=old-root / ext4 defaults,noatime 0 1
UUID=old-boot /boot/firmware vfat defaults 0 2
CFG
}

@test "clone script falls back to -U and normalizes files" {
  run scripts/clone_to_nvme.sh --target /dev/testdisk
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ Clone complete"* ]]

  mapfile -t calls <"${RPI_CLONE_CALL_LOG}"
  [ "${#calls[@]}" -eq 2 ]
  [[ "${calls[0]}" =~ "-f -u" ]]
  [[ "${calls[1]}" =~ "-f -U" ]]

  root_entry=$(awk '{for (i = 1; i <= NF; i++) if ($i ~ /^root=/) {print $i; exit}}' "$CLONE_MOUNT/boot/firmware/cmdline.txt" || true)
  [[ "$root_entry" == "root=PARTUUID=root-partuuid" ]]

  grep -Eq '^PARTUUID=root-partuuid[[:space:]]+/[[:space:]]' "$CLONE_MOUNT/etc/fstab"
  grep -Eq '^UUID=boot-uuid[[:space:]]+/boot/firmware' "$CLONE_MOUNT/etc/fstab"
}
