#!/usr/bin/env bash
set -Eeuo pipefail
set +x
cleanup() { unset token; }
trap cleanup EXIT INT TERM
if [ "$(kubectl config current-context)" != "sugar-staging" ]; then
  printf 'ERROR: current context must be exactly sugar-staging.\n' >&2
  exit 1
fi
printf 'Cloudflare DNS API token (hidden): ' >&2
IFS= read -r -s token
printf '\n' >&2
if [ -z "${token}" ]; then
  printf 'ERROR: token must not be empty.\n' >&2
  exit 1
fi
printf '%s' "${token}" | kubectl --context sugar-staging -n cert-manager create secret generic cloudflare-api-token \
  --from-file=api-token=/dev/stdin --dry-run=client -o yaml | \
  kubectl --context sugar-staging apply -f - >/dev/null
cleanup
printf 'Cloudflare token Secret applied in staging.\n'
