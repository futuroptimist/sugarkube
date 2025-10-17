#!/usr/bin/env bats

setup() {
  TMP_DIR=$(mktemp -d)
  STUB_BIN="${TMP_DIR}/bin"
  STATE_DIR="${TMP_DIR}/state"
  mkdir -p "${STUB_BIN}" "${STATE_DIR}"
  ORIG_PATH="${PATH}"
  PATH="${STUB_BIN}:${PATH}"
  export CLONE_TEST_STATE_DIR="${STATE_DIR}"
  TARGET_DEVICE_UNDER_TEST="/dev/fakebats"
  export TARGET_DEVICE_UNDER_TEST

  cat <<'STUB' > "${STUB_BIN}/rpi-clone"
#!/usr/bin/env bash
set -Eeuo pipefail
state_dir="${CLONE_TEST_STATE_DIR}"
count_file="${state_dir}/rpi_clone_count"
log_file="${state_dir}/rpi_clone_calls"
count=0
if [[ -f "${count_file}" ]]; then
  read -r count < "${count_file}"
fi
count=$((count + 1))
printf '%s\n' "${count} $*" >> "${log_file}"
printf '%s\n' "${count}" > "${count_file}"
if (( count == 1 )); then
  echo "Unattended -u option not allowed when initializing" >&2
  exit 1
fi
printf 'Clone attempt %d succeeded\n' "${count}"
exit 0
STUB
  chmod +x "${STUB_BIN}/rpi-clone"

  cat <<'STUB' > "${STUB_BIN}/df"
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == "-B1" && "$2" == "--output=used" ]]; then
  case "$3" in
    /)
      printf 'used\n104857600\n'
      exit 0
      ;;
    /mnt/clone)
      printf 'used\n52428800\n'
      exit 0
      ;;
  esac
fi
echo "df stub received unexpected args: $*" >&2
exit 1
STUB
  chmod +x "${STUB_BIN}/df"

  cat <<'STUB' > "${STUB_BIN}/lsblk"
#!/usr/bin/env bash
set -Eeuo pipefail
args=("$@")
last_index=$(( ${#args[@]} - 1 ))
last="${args[${last_index}]}"
if [[ "$1" == "-nb" && "$2" == "-o" && "$3" == "SIZE" && "${last}" == "${TARGET_DEVICE_UNDER_TEST}" ]]; then
  printf '2000000000\n'
  exit 0
fi
if [[ "$1" == "-nr" && "$2" == "-o" && "$3" == "NAME,MOUNTPOINT" && "${last}" == "${TARGET_DEVICE_UNDER_TEST}" ]]; then
  printf 'fake\n'
  printf 'fakep1 \n'
  printf 'fakep2 \n'
  exit 0
fi
if [[ "$1" == "-nr" && "$2" == "-o" && "$3" == "NAME" && "$4" == "-p" && "${last}" == "${TARGET_DEVICE_UNDER_TEST}" ]]; then
  printf '/dev/fake\n/dev/fakep1\n/dev/fakep2\n'
  exit 0
fi
echo "lsblk stub received unexpected args: $*" >&2
exit 1
STUB
  chmod +x "${STUB_BIN}/lsblk"

  cat <<'STUB' > "${STUB_BIN}/mount"
#!/usr/bin/env bash
set -Eeuo pipefail
state="${CLONE_TEST_STATE_DIR}/mounts"
touch "${state}"
if [[ "$#" -lt 2 ]]; then
  echo "mount stub requires device and mountpoint" >&2
  exit 1
fi
device="$1"
mountpoint="$2"
mkdir -p "${mountpoint}"
tmp="${state}.tmp"
grep -v "^${mountpoint} " "${state}" > "${tmp}" || true
printf '%s %s\n' "${mountpoint}" "${device}" >> "${tmp}"
mv "${tmp}" "${state}"
exit 0
STUB
  chmod +x "${STUB_BIN}/mount"

  cat <<'STUB' > "${STUB_BIN}/mountpoint"
#!/usr/bin/env bash
set -Eeuo pipefail
state="${CLONE_TEST_STATE_DIR}/mounts"
if [[ "$1" == "-q" ]]; then
  shift
fi
if [[ -f "${state}" ]] && grep -q "^$1 " "${state}"; then
  exit 0
fi
exit 1
STUB
  chmod +x "${STUB_BIN}/mountpoint"

  cat <<'STUB' > "${STUB_BIN}/findmnt"
#!/usr/bin/env bash
set -Eeuo pipefail
state="${CLONE_TEST_STATE_DIR}/mounts"
if [[ "$1" == "-no" && "$2" == "SOURCE" ]]; then
  mountpoint="$3"
  if [[ -f "${state}" ]]; then
    match=$(grep -m1 "^${mountpoint} " "${state}" || true)
    if [[ -n "${match}" ]]; then
      printf '%s\n' "${match#* }"
      exit 0
    fi
  fi
  exit 1
fi
echo "findmnt stub received unexpected args: $*" >&2
exit 1
STUB
  chmod +x "${STUB_BIN}/findmnt"

  cat <<'STUB' > "${STUB_BIN}/blkid"
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == "-s" && "$2" == "UUID" && "$3" == "-o" && "$4" == "value" ]]; then
  case "$5" in
    /dev/fakep2)
      printf 'root-uuid\n'
      exit 0
      ;;
    /dev/fakep1)
      printf 'boot-uuid\n'
      exit 0
      ;;
  esac
fi
if [[ "$1" == "-s" && "$2" == "PARTUUID" && "$3" == "-o" && "$4" == "value" ]]; then
  case "$5" in
    /dev/fakep2)
      printf 'root-partuuid\n'
      exit 0
      ;;
    /dev/fakep1)
      printf 'boot-partuuid\n'
      exit 0
      ;;
  esac
fi
echo "blkid stub received unexpected args: $*" >&2
exit 1
STUB
  chmod +x "${STUB_BIN}/blkid"

  for cmd in wipefs curl sync; do
    cat <<'STUB' > "${STUB_BIN}/${cmd}"
#!/usr/bin/env bash
exit 0
STUB
    chmod +x "${STUB_BIN}/${cmd}"
  done

  if [[ -e "${TARGET_DEVICE_UNDER_TEST}" ]]; then
    rm -f "${TARGET_DEVICE_UNDER_TEST}"
  fi
  mknod "${TARGET_DEVICE_UNDER_TEST}" b 240 1

  CLONE_DIR="/mnt/clone"
  if [[ -d "${CLONE_DIR}" ]]; then
    CLONE_DIR_PREEXIST=1
  else
    CLONE_DIR_PREEXIST=0
    mkdir -p "${CLONE_DIR}"
  fi
  mkdir -p "${CLONE_DIR}/boot/firmware"
  mkdir -p "${CLONE_DIR}/etc"
  cat <<'EOF' > "${CLONE_DIR}/boot/firmware/cmdline.txt"
console=tty1 root=/dev/mmcblk0p2 rootfstype=ext4 fsck.repair=yes rootwait
EOF
  cat <<'EOF' > "${CLONE_DIR}/etc/fstab"
UUID=old-root / ext4 defaults 0 1
UUID=old-boot /boot/firmware vfat defaults 0 2
EOF
  : > "${STATE_DIR}/mounts"
}

teardown() {
  PATH="${ORIG_PATH}"
  rm -rf "${TMP_DIR}"
  if [[ ${CLONE_DIR_PREEXIST} -eq 0 ]]; then
    rm -rf /mnt/clone
  else
    rm -f /mnt/clone/boot/firmware/*
  fi
  rm -f "${TARGET_DEVICE_UNDER_TEST}"
}

@test "clone_to_nvme retries with -U when unattended init is rejected" {
  run env TARGET="${TARGET_DEVICE_UNDER_TEST}" WIPE=0 bash "${BATS_TEST_DIRNAME}/../scripts/clone_to_nvme.sh"
  [ "$status" -eq 0 ]
  calls="$(cat "${STATE_DIR}/rpi_clone_calls")"
  [[ "${calls}" == $'1 -f -u /dev/fakebats\n2 -f -U /dev/fakebats' ]]
  grep -q '^/mnt/clone /dev/fakep2$' "${STATE_DIR}/mounts"
  grep -q '^/mnt/clone/boot/firmware /dev/fakep1$' "${STATE_DIR}/mounts"
}

