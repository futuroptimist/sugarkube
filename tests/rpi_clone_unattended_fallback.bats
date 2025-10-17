#!/usr/bin/env bats

setup() {
  TEST_TMPDIR="$(mktemp -d)"
  BIN_DIR="$TEST_TMPDIR/bin"
  mkdir -p "$BIN_DIR"
  export PATH="$BIN_DIR:$PATH"

  export SKIP_ROOT_CHECK=1
  export WIPE=0

  FAKE_DEVICE="$(mktemp -u /dev/fakeclone.XXXX)"
  mknod "$FAKE_DEVICE" b 7 0
  mknod "${FAKE_DEVICE}p1" b 7 1
  mknod "${FAKE_DEVICE}p2" b 7 2
  export FAKE_DEVICE
  FAKE_NAME="$(basename "$FAKE_DEVICE")"
  export FAKE_NAME

  export CLONE_MOUNT="$TEST_TMPDIR/mnt"
  mkdir -p "$CLONE_MOUNT/boot/firmware" "$CLONE_MOUNT/etc"
  cat <<'CMDLINE' >"$CLONE_MOUNT/boot/firmware/cmdline.txt"
console=serial0,115200 root=LABEL=ROOTFS quiet splash
CMDLINE
  cat <<'FSTAB' >"$CLONE_MOUNT/etc/fstab"
UUID=old-root / ext4 defaults 0 1
UUID=old-boot /boot/firmware vfat defaults 0 2
FSTAB

  export TARGET="$FAKE_DEVICE"

  RPI_CLONE_CALLS="$TEST_TMPDIR/rpi_clone_calls.log"
  export RPI_CLONE_CALLS
  cat <<'STUB' >"$BIN_DIR/rpi-clone"
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$RPI_CLONE_CALLS"
for arg in "$@"; do
  if [[ "$arg" == "-u" ]]; then
    echo "Unattended -u option not allowed when initializing" >&2
    exit 1
  fi
done
echo "bytes written: 123456789" >&2
exit 0
STUB
  chmod +x "$BIN_DIR/rpi-clone"

  REAL_LSBLK="$(command -v lsblk)"
  export REAL_LSBLK
  cat <<'STUB' >"$BIN_DIR/lsblk"
#!/usr/bin/env bash
if [[ "$1" == "-nb" && "$2" == "-o" && "$3" == "SIZE" && "$4" == "$FAKE_DEVICE" ]]; then
  echo 21474836480
elif [[ "$1" == "-nr" && "$2" == "-o" && "$3" == "NAME,MOUNTPOINT" && "$4" == "$FAKE_DEVICE" ]]; then
  printf '%s %s\n' "${FAKE_NAME}p1" ""
  printf '%s %s\n' "${FAKE_NAME}p2" ""
elif [[ "$1" == "-nr" && "$2" == "-o" && "$3" == "NAME,TYPE" && "$4" == "$FAKE_DEVICE" ]]; then
  printf '%s %s\n' "${FAKE_NAME}" "disk"
  printf '%s %s\n' "${FAKE_NAME}p1" "part"
  printf '%s %s\n' "${FAKE_NAME}p2" "part"
else
  exec "$REAL_LSBLK" "$@"
fi
STUB
  chmod +x "$BIN_DIR/lsblk"

  REAL_FINDMNT="$(command -v findmnt)"
  export REAL_FINDMNT
  cat <<'STUB' >"$BIN_DIR/findmnt"
#!/usr/bin/env bash
if [[ "$1" == "-no" && "$2" == "SOURCE" ]]; then
  case "$3" in
    "$CLONE_MOUNT")
      echo "/dev/${FAKE_NAME}p2"
      exit 0
      ;;
    "$CLONE_MOUNT/boot/firmware")
      echo "/dev/${FAKE_NAME}p1"
      exit 0
      ;;
  esac
fi
exec "$REAL_FINDMNT" "$@"
STUB
  chmod +x "$BIN_DIR/findmnt"

  REAL_MOUNTPOINT="$(command -v mountpoint)"
  export REAL_MOUNTPOINT
  cat <<'STUB' >"$BIN_DIR/mountpoint"
#!/usr/bin/env bash
if [[ "$1" == "-q" ]]; then
  if [[ "$2" == "$CLONE_MOUNT" || "$2" == "$CLONE_MOUNT/boot/firmware" ]]; then
    exit 0
  fi
fi
exec "$REAL_MOUNTPOINT" "$@"
STUB
  chmod +x "$BIN_DIR/mountpoint"

  REAL_BLKID="$(command -v blkid)"
  export REAL_BLKID
  cat <<'STUB' >"$BIN_DIR/blkid"
#!/usr/bin/env bash
if [[ "$1" == "-s" && "$2" == "UUID" && "$3" == "-o" && "$4" == "value" ]]; then
  case "$5" in
    "/dev/${FAKE_NAME}p2") echo "root-uuid"; exit 0 ;;
    "/dev/${FAKE_NAME}p1") echo "boot-uuid"; exit 0 ;;
  esac
elif [[ "$1" == "-s" && "$2" == "PARTUUID" && "$3" == "-o" && "$4" == "value" ]]; then
  case "$5" in
    "/dev/${FAKE_NAME}p2") echo "root-partuuid"; exit 0 ;;
    "/dev/${FAKE_NAME}p1") echo "boot-partuuid"; exit 0 ;;
  esac
fi
exec "$REAL_BLKID" "$@"
STUB
  chmod +x "$BIN_DIR/blkid"

  cat <<'STUB' >"$BIN_DIR/wipefs"
#!/usr/bin/env bash
exit 0
STUB
  chmod +x "$BIN_DIR/wipefs"
}

teardown() {
  rm -rf "$TEST_TMPDIR"
  rm -f "$FAKE_DEVICE" "${FAKE_DEVICE}p1" "${FAKE_DEVICE}p2" 2>/dev/null || true
}

@test "clone_to_nvme retries with -U when unattended init fails" {
  run bash "$BATS_TEST_DIRNAME/../scripts/clone_to_nvme.sh"
  [ "$status" -eq 0 ]
  clone_calls="$(cat "$RPI_CLONE_CALLS")"
  [[ "$clone_calls" == *"-f -u"* ]]
  [[ "$clone_calls" == *"-f -U"* ]]
  run tail -n1 "$RPI_CLONE_CALLS"
  [ "$status" -eq 0 ]
  [ "$output" = "-f -U $FAKE_DEVICE" ]
}
