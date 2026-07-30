#!/usr/bin/env bash
set -Eeuo pipefail
command_name="${1-}" env_name="${2-}" certificate="${3-}" timeout="${4:-300}"
[[ "$env_name" == staging ]] || { printf 'ERROR: env=staging is required.\n' >&2; exit 2; }
[[ "$(kubectl config current-context)" == sugar-staging ]] || { printf 'ERROR: current context must be sugar-staging.\n' >&2; exit 2; }
inventory="$(dirname "$0")/../clusters/staging/certificates.json"
target() {
  python3 - "$inventory" "$certificate" <<'PY'
import json,sys
items=json.load(open(sys.argv[1], encoding="utf-8"))["certificates"]
matches=[x for x in items if x["name"] == sys.argv[2]]
if len(matches) != 1: raise SystemExit("certificate must name exactly one inventoried certificate")
print(matches[0]["namespace"], matches[0]["name"])
PY
}
status() { python3 "$(dirname "$0")/staging_certificates.py" status --env staging; }
observe() {
  local deadline=$((SECONDS + timeout)) ready
  while (( SECONDS < deadline )); do
    status
    ready="$(kubectl --context sugar-staging -n "$namespace" get certificate "$name" -o 'jsonpath={.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
    [[ "$ready" == True ]] && return 0
    sleep 15
  done
  return 1
}
case "$command_name" in
  status) status ;;
  wait|renew)
    [[ "$timeout" =~ ^[0-9]+$ ]] && (( timeout >= 1 && timeout <= 900 )) || { printf 'ERROR: timeout must be 1..900 seconds.\n' >&2; exit 2; }
    read -r namespace name < <(target)
    # Give the current Request/Order/Challenge chain a bounded chance to converge.
    observe && exit 0
    [[ "$command_name" == wait ]] && { printf 'Timed out while observing existing Challenges; no renewal requested.\n' >&2; exit 1; }
    printf 'Existing Challenges did not converge in %ss; requesting one targeted renewal.\n' "$timeout" >&2
    cmctl renew --context sugar-staging -n "$namespace" "$name"
    observe || { printf 'Timed out waiting for the targeted certificate after renewal.\n' >&2; exit 1; }
    ;;
  verify)
    read -r namespace name < <(target)
    ready="$(kubectl --context sugar-staging -n "$namespace" get certificate "$name" -o 'jsonpath={.status.conditions[?(@.type=="Ready")].status}')"
    [[ "$ready" == True ]] || { printf 'ERROR: certificate is not Ready=True.\n' >&2; exit 1; }
    # Request only the public certificate field; never request or handle the private key.
    kubectl --context sugar-staging -n "$namespace" get secret "$name" -o 'go-template={{index .data "tls.crt"}}' \
      | base64 --decode | openssl x509 -noout -subject -issuer -serial -dates -ext subjectAltName
    ;;
  *) printf 'Usage: %s status|wait|renew|verify staging [certificate] [timeout]\n' "$0" >&2; exit 2 ;;
esac
