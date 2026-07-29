#!/usr/bin/env bash
set -Eeuo pipefail

credential="${CREDENTIALS_DIRECTORY:?systemd credential directory is unavailable}/ping-url"

fail() {
  printf 'healthchecks heartbeat: %s\n' "$1" >&2
  exit 1
}

[[ -r "${credential}" ]] || fail "credential is missing or unreadable"
IFS= read -r url <"${credential}" || fail "credential is empty"
[[ -n "${url}" ]] || fail "credential is empty"
[[ "$(wc -l <"${credential}")" -eq 1 ]] || fail "credential must contain exactly one line"
[[ "${url}" =~ ^https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]] ||
  fail "credential is not an accepted Healthchecks.io ping URL"

# Read curl configuration through its standard input so the credential never
# becomes an argument. Suppress curl's potentially URL-bearing diagnostics.
if ! printf 'url = "%s"\n' "${url}" | /usr/bin/curl \
  --config - --silent --fail --output /dev/null \
  --connect-timeout 3 --max-time 10 --retry 2 --retry-delay 1 \
  --retry-max-time 25 2>/dev/null; then
  fail "delivery failed (details redacted)"
fi

printf 'healthchecks heartbeat: delivered\n'
