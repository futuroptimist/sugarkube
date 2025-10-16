#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")"/.. && pwd)"
script="${root}/scripts/verify_just_in_logs.sh"
"${script}" "${root}/tests/fixtures/logs-aggregate"
"${script}" "${root}/tests/fixtures/logs-stage"
if "${script}" "${root}/tests/fixtures/logs-missing"; then
  echo "expected failure when marker is missing" >&2
  exit 1
fi
