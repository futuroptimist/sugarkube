#!/usr/bin/env bats

setup() {
  SUMMARY_LIB_PATH="${BATS_CWD}/scripts/lib/summary.sh"
}

@test "summary emit produces output" {
  run bash -c 'source "$1"; summary::init; summary::section "Demo"; summary::step OK "Sample"; summary::emit' "summary" "${SUMMARY_LIB_PATH}"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
  [[ "$output" =~ Sample ]]
}

@test "summary emit is plain text for non-tty outputs" {
  run bash -c 'source "$1"; summary::init; summary::section "TTY"; summary::step OK "Color"; summary::emit' "summary" "${SUMMARY_LIB_PATH}"
  [ "$status" -eq 0 ]
  [[ "$output" != *$'\033'* ]]

  TERM=dumb run bash -c 'source "$1"; summary::init; summary::section "TTY"; summary::step OK "Color"; summary::emit' "summary" "${SUMMARY_LIB_PATH}"
  [ "$status" -eq 0 ]
  [[ "$output" != *$'\033'* ]]
}
