#!/usr/bin/env bash
# Secret-safe Healthchecks.io delivery helper. The URL is read only from a
# systemd credential and is supplied to curl through stdin, never argv.
set -euo pipefail

validate() {
  local value="$1"
  [ -n "$value" ] &&
    [[ "$value" =~ ^https://hc-ping\.com/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$ ]]
}

if [ "${1:-}" = --validate-stdin ]; then
  IFS= read -r url || true
  validate "${url:-}" || { unset url; exit 1; }
  [ -z "$(cat)" ] || { unset url; exit 1; }
  unset url
  exit 0
fi

credential="${CREDENTIALS_DIRECTORY:-}/healthchecks-url"
if [ -z "${CREDENTIALS_DIRECTORY:-}" ] || [ ! -f "$credential" ]; then
  printf 'ERROR: heartbeat credential is unavailable.\n' >&2
  exit 1
fi

url="$(cat -- "$credential")" || {
  printf 'ERROR: heartbeat credential could not be read.\n' >&2
  exit 1
}
if [ "$(wc -l <"$credential")" -gt 1 ] || ! validate "$url"; then
  unset url
  printf 'ERROR: heartbeat credential is invalid; expected one HTTPS Healthchecks UUID ping URL.\n' >&2
  exit 1
fi

# curl diagnostics are intentionally discarded: some failures repeat the URL.
# The replacement diagnostic is actionable without disclosing the credential.
if ! printf 'url = "%s"\n' "$url" | curl --config - --silent --fail \
  --output /dev/null --connect-timeout 5 --max-time 10 --retry 2 \
  --retry-delay 1 --retry-max-time 25 2>/dev/null; then
  unset url
  printf 'ERROR: heartbeat delivery failed after bounded HTTPS retries.\n' >&2
  exit 1
fi
unset url
printf 'Heartbeat delivered successfully.\n'
