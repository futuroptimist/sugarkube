#!/usr/bin/env bash
set -Eeuo pipefail
set +x
token=''
cleanup() { unset token; }
trap cleanup EXIT INT TERM

if [[ ${1-} != staging || $(kubectl config current-context) != sugar-staging ]]; then
  printf 'ERROR: requires env=staging and current context sugar-staging.\n' >&2
  exit 2
fi
printf 'Cloudflare API token: ' >&2
IFS= read -r -s token
printf '\n' >&2
if [[ -z $token ]]; then
  printf 'ERROR: token must not be empty.\n' >&2
  exit 2
fi
if ! printf '%s' "$token" | kubectl --context sugar-staging -n cert-manager create secret generic cloudflare-api-token \
  --from-file=api-token=/dev/stdin --dry-run=client -o yaml | kubectl --context sugar-staging apply -f - >/dev/null; then
  printf 'ERROR: Secret update failed.\n' >&2
  exit 1
fi
unset token
printf 'Updated cert-manager/cloudflare-api-token.\n'
