#!/usr/bin/env bats

run_summary_script() {
  local term_value="$1"
  shift
  local script="${BATS_CWD}/scripts/lib/summary.sh"
  TERM="${term_value}" bash -c "\
set -euo pipefail\n\
. '${script}'\n\
summary::init\n\
summary::section 'Demo'\n\
summary::step OK 'Alpha'\n\
summary::kv 'Alpha' 'note=1'\n\
summary::step FAIL 'Beta'\n\
summary::emit\n"
}

@test "summary emit produces non-empty output" {
  run run_summary_script "xterm"
  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -gt 0 ]
  [[ "${output}" =~ Summary ]]
  [[ "${output}" =~ Alpha ]]
  [[ "${output}" =~ Beta ]]
  [[ "${output}" =~ ✅ ]]
}

@test "summary output omits ANSI escapes when TERM=dumb" {
  run run_summary_script "dumb"
  [ "$status" -eq 0 ]
  [[ ! "${output}" =~ $'\u001b' ]]
}
