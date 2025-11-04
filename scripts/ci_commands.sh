#!/usr/bin/env bash
set -euo pipefail

# Mirror CI locally by running the same suites our workflows expect.
# The groups map to the Summary table used in PR templates:
# - BATS covers shell tests executed in ci.yml (Run Bash tests under kcov).
# - E2E/Playwright aggregates pytest along with image-builder E2E scripts
#   that run in .github/workflows/pi-image.yml.
# - QEMU smoke validates the QEMU harness via its pytest suite.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BATS_STATUS="⚠️ not run"
E2E_STATUS="⚠️ not run"
QEMU_STATUS="⚠️ not run"

print_summary() {
  printf '\nSummary:\n'
  printf 'BATS: %s\n' "$BATS_STATUS"
  printf 'E2E/Playwright: %s\n' "$E2E_STATUS"
  printf 'QEMU smoke: %s\n' "$QEMU_STATUS"
}

run_command() {
  local description="$1"
  shift
  printf '\n→ %s\n' "$description"
  printf '+ %s\n' "$*"
  "$@"
}

run_bats() {
  if ! command -v bats >/dev/null 2>&1; then
    echo "bats is required. Install it with 'sudo apt-get install bats' or brew." >&2
    return 1
  fi
  run_command "Run BATS suite" bats --recursive tests/bats
}

run_pytest_suite() {
  mapfile -t pytest_targets < <(find tests -name 'test_*.py' ! -name 'test_qemu_pi_smoke_test.py' -print | LC_ALL=C sort)
  if [ "${#pytest_targets[@]}" -eq 0 ]; then
    echo "No pytest targets discovered." >&2
    return 1
  fi
  run_command "Run pytest suite" pytest -q "${pytest_targets[@]}"
}

run_image_e2e_scripts() {
  local -a scripts=(
    tests/create_build_metadata_e2e.sh
    tests/compute_pi_gen_cache_key_e2e.sh
    tests/fix_pi_image_permissions_e2e.sh
    tests/render_pi_imager_preset_e2e.sh
    tests/artifact_detection_test.sh
    tests/verify_just_in_logs_test.sh
    tests/no_libraspberrypi_bin_test.sh
    tests/workflow_verify_step_guard_test.sh
  )

  local script
  for script in "${scripts[@]}"; do
    if [ ! -x "$script" ]; then
      echo "E2E script $script is missing or not executable." >&2
      return 1
    fi
    run_command "Run $script" "$script"
  done
}

run_qemu_pytest() {
  run_command "Run QEMU smoke pytest" pytest -q tests/test_qemu_pi_smoke_test.py
}

main() {
  if run_bats; then
    BATS_STATUS="✅ pass"
  else
    BATS_STATUS="❌ fail"
    print_summary
    exit 1
  fi

  if run_pytest_suite && run_image_e2e_scripts; then
    E2E_STATUS="✅ pass"
  else
    E2E_STATUS="❌ fail"
    QEMU_STATUS="⚠️ not executed (blocked by E2E failure)"
    print_summary
    exit 1
  fi

  if run_qemu_pytest; then
    QEMU_STATUS="✅ pass"
  else
    QEMU_STATUS="❌ fail"
    print_summary
    exit 1
  fi

  print_summary
}

main "$@"
