#!/usr/bin/env bats

setup() {
  export PATH="/bin:/usr/bin:/usr/local/bin:$PATH"
  export SUGARKUBE_FAKE_DEVICE_FILE="$BATS_TEST_TMPDIR/devices.txt"
  cat <<'DEVICES' >"$SUGARKUBE_FAKE_DEVICE_FILE"
/dev/sdz|Test Media|2147483648|usb|1
/dev/sdy|Spare Stick|1073741824|usb|1
DEVICES
}

@test "lists devices from fake catalog" {
  run "$BATS_TEST_DIRNAME/../scripts/flash_pi_media.sh" --list
  [ "$status" -eq 0 ]
  [[ "$output" == *"Device"*"Capacity"* ]]
  [[ "$output" == *"/dev/sdz"* ]]
}

@test "dry run skips flashing" {
  image="$BATS_TEST_TMPDIR/sample.img"
  dd if=/dev/zero of="$image" bs=1 count=1024 >/dev/null 2>&1
  run "$BATS_TEST_DIRNAME/../scripts/flash_pi_media.sh" --dry-run --device /dev/sdz --image "$image"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Dry run complete"* ]]
}

@test "errors when image missing" {
  run "$BATS_TEST_DIRNAME/../scripts/flash_pi_media.sh" --dry-run --device /dev/sdz --image "$BATS_TEST_TMPDIR/missing.img"
  [ "$status" -ne 0 ]
  [[ "$output" == *"not found"* ]]
}
