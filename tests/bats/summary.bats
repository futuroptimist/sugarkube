#!/usr/bin/env bats

@test "summary emits output without color when non-tty" {
  export IN_BATS_TEST=1
  run bash -c '
    set -euo pipefail
    source "'"${BATS_CWD}/scripts/lib/summary.sh"'"
    summary::init
    summary::section "Smoke"
    summary::step OK "First step"
    summary::step FAIL "Second step" "details"
    summary::emit
  '

  [ "$status" -eq 0 ]
  [ -n "$output" ]
  [[ "$output" =~ Summary: ]]
  [[ "$output" =~ First\ step ]]
  [[ "$output" =~ Second\ step ]]
  [[ "$output" != *$'\033'* ]]
}

@test "summary avoids ANSI escapes when TERM is dumb" {
  export IN_BATS_TEST=1
  run env TERM=dumb bash -c '
    set -euo pipefail
    source "'"${BATS_CWD}/scripts/lib/summary.sh"'"
    summary::init
    summary::section "TTY"
    summary::step WARN "Term test"
    summary::emit
  '

  [ "$status" -eq 0 ]
  [ -n "$output" ]
  [[ "$output" != *$'\033'* ]]
}
