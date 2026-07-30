#!/usr/bin/env bash
set -Eeuo pipefail
[[ "${1-}" == "staging" ]] || { printf 'ERROR: env=staging is required.\n' >&2; exit 2; }
[[ "$(kubectl config current-context)" == "sugar-staging" ]] || { printf 'ERROR: current context must be sugar-staging.\n' >&2; exit 2; }
token=''
cleanup() { unset token; }
trap cleanup EXIT INT TERM
{ set +x; } 2>/dev/null
IFS= read -r -s -p 'Cloudflare DNS API token: ' token
printf '\n' >&2
[[ -n "$token" ]] || { printf 'ERROR: token must not be empty.\n' >&2; exit 2; }
printf %s "$token" | kubectl --context sugar-staging -n cert-manager create secret generic cloudflare-api-token \
  --from-file=api-token=/dev/stdin --dry-run=client -o yaml | kubectl --context sugar-staging apply -f - >/dev/null
unset token
printf 'Cloudflare DNS API token Secret updated for staging.\n'
