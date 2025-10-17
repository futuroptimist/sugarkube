#!/usr/bin/env bats

setup() {
  cd "${BATS_TEST_DIRNAME}/.."
  export TEST_BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "${TEST_BIN}"
  export PATH="${TEST_BIN}:$PATH"
  export BOOT_ORDER_CALL_LOG="${BATS_TEST_TMPDIR}/boot_order_calls.log"
  : >"${BOOT_ORDER_CALL_LOG}"

  cat >"${TEST_BIN}/boot_order_stub.sh" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "$@" >>"${BOOT_ORDER_CALL_LOG}"
if [[ -n "${PCIE_PROBE:-}" ]]; then
  echo "PCIE_PROBE=${PCIE_PROBE}" >>"${BOOT_ORDER_CALL_LOG}"
fi
STUB
  chmod +x "${TEST_BIN}/boot_order_stub.sh"
  export BOOT_ORDER_CMD="${TEST_BIN}/boot_order_stub.sh"
}

@test "apply_boot_order_preset maps sd-nvme-usb" {
  run scripts/apply_boot_order_preset.sh sd-nvme-usb
  [ "$status" -eq 0 ]
  [[ "$output" == *"Target preset 'sd-nvme-usb' => BOOT_ORDER=0xF461"* ]]

  mapfile -t calls <"${BOOT_ORDER_CALL_LOG}"
  [ "${#calls[@]}" -eq 1 ]
  [[ "${calls[0]}" == "ensure_order 0xF461" ]]
}

@test "apply_boot_order_preset maps nvme-first and forwards PCIE_PROBE" {
  run PCIE_PROBE=1 scripts/apply_boot_order_preset.sh nvme-first
  [ "$status" -eq 0 ]
  [[ "$output" == *"Target preset 'nvme-first' => BOOT_ORDER=0xF416"* ]]

  mapfile -t calls <"${BOOT_ORDER_CALL_LOG}"
  [ "${#calls[@]}" -eq 2 ]
  [[ "${calls[0]}" == "ensure_order 0xF416" ]]
  [[ "${calls[1]}" == "PCIE_PROBE=1" ]]
}

@test "apply_boot_order_preset rejects unknown preset" {
  run scripts/apply_boot_order_preset.sh unsupported
  [ "$status" -ne 0 ]
  [[ "$output" == *"Unknown boot-order preset"* ]]
}
