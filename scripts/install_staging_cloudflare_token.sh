#!/usr/bin/env bash
set -Eeuo pipefail

cleanup() { unset token; }
trap cleanup EXIT INT TERM
set +x

[[ "${1-}" == "staging" ]] || { printf 'ERROR: environment must be staging.\n' >&2; exit 2; }
[[ "$(kubectl config current-context)" == "sugar-staging" ]] || { printf 'ERROR: current context must be sugar-staging.\n' >&2; exit 2; }
printf 'Cloudflare API token (hidden): ' >&2
IFS= read -r -s token
printf '\n' >&2
[[ -n "$token" ]] || { printf 'ERROR: token must not be empty.\n' >&2; exit 2; }
printf '%s' "$token" | kubectl --context sugar-staging create secret generic cloudflare-api-token \
  --namespace cert-manager --from-file=api-token=/dev/stdin --dry-run=client -o yaml \
  | kubectl --context sugar-staging apply -f - >/dev/null
unset token
printf 'Cloudflare credential Secret applied in staging.\n'
