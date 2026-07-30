#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_CONTEXT=sugar-staging
TIMEOUT="${SUGARKUBE_CERT_MANAGER_TIMEOUT:-300s}"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
need() { command -v "$1" >/dev/null 2>&1 || die "required command '$1' was not found"; }
normalize_env() { [[ "${1#env=}" == staging ]] || die 'this lifecycle is staging-only; use env=staging'; }
guard() { normalize_env "$1"; [[ "$(kubectl config current-context 2>/dev/null || true)" == "$EXPECTED_CONTEXT" ]] || die "refusing mutation: current context must be exactly ${EXPECTED_CONTEXT}"; }
inventory() {
  [[ -n "${SUGARKUBE_STAGING_CERTIFICATES:-}" ]] || die 'set SUGARKUBE_STAGING_CERTIFICATES to newline-separated namespace/certificate/hostname entries'
  printf '%s\n' "$SUGARKUBE_STAGING_CERTIFICATES" | awk 'NF' | while IFS= read -r item; do
    [[ "$item" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?/[a-z0-9]([-a-z0-9]*[a-z0-9])?/([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]] || die "invalid certificate inventory entry: ${item}"
    printf '%s\n' "$item"
  done
}
status() {
  normalize_env "$1"; need kubectl; need python3
  local tmp; tmp="$(mktemp -d -t sugarkube-cert-status.XXXXXX)"; trap 'rm -rf "${tmp:-}"' EXIT
  for pair in 'certificates certificates' 'requests certificaterequests' 'orders orders.acme.cert-manager.io' 'challenges challenges.acme.cert-manager.io' 'issuers clusterissuers' 'events events'; do
    read -r key kind <<<"$pair"; kubectl get "$kind" -A -o json >"$tmp/$key.json" || die "unable to read ${kind} (output suppressed)"
  done
  python3 - "$tmp" "$(inventory)" <<'PY' >"$tmp/input.json"
import json,pathlib,subprocess,sys
p=pathlib.Path(sys.argv[1]); inv=sys.argv[2].splitlines()
resources={x.stem:json.loads(x.read_text()) for x in p.glob('*.json')}
secrets={}
for entry in inv:
    ns,cert,_=entry.split('/',2)
    found=[x for x in resources['certificates'].get('items',[]) if x.get('metadata',{}).get('namespace')==ns and x.get('metadata',{}).get('name')==cert]
    name=found[0].get('spec',{}).get('secretName') if found else None
    if name:
        check=subprocess.run(['kubectl','-n',ns,'get','secret',name,'-o','name'],text=True,capture_output=True)
        secrets.setdefault(ns,{})[name]=check.returncode==0
print(json.dumps({'inventory':inv,'resources':resources,'secrets':secrets}))
PY
  python3 "$ROOT/scripts/staging_cert_manager.py" <"$tmp/input.json"
}
install_token() {
  guard "$1"; need kubectl
  local credential=''
  if [[ -t 0 ]]; then read -r -s -p 'Cloudflare credential (input hidden): ' credential; printf '\n' >&2; else IFS= read -r credential || true; fi
  [[ -n "$credential" ]] || die 'Cloudflare credential input was empty'
  trap 'unset credential' EXIT
  printf '%s' "$credential" | kubectl -n cert-manager create secret generic cloudflare-api-token --from-file=api-token=/dev/stdin --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  unset credential
  printf 'Installed cert-manager/cloudflare-api-token from hidden input/stdin; value not displayed.\n'
}
verify_authorization() {
  guard "$1"
  local issuer
  issuer="$(kubectl get clusterissuer letsencrypt-production -o json)" || die 'unable to inspect letsencrypt-production'
  ISSUER="$issuer" python3 - <<'PY'
import json,os
d=json.loads(os.environ['ISSUER']); conditions=d.get('status',{}).get('conditions',[])
assert any(x.get('type')=='Ready' and x.get('status')=='True' for x in conditions), 'issuer is not Ready'
ref=d['spec']['acme']['solvers'][0]['dns01']['cloudflare']['apiTokenSecretRef']
assert ref=={'name':'cloudflare-api-token','key':'api-token'}, 'unexpected Cloudflare Secret reference'
PY
  kubectl -n cert-manager get secret cloudflare-api-token -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("type")=="Opaque"; assert set(d.get("data",{}))=={"api-token"}' || die 'Secret must be Opaque with exactly the api-token key'
  status "$1"
}
recover() {
  guard "$1"; need cmctl; need curl; need openssl
  local target="${2:-}" ns cert host before after
  [[ -n "$target" ]] || die 'pass one namespace/certificate/hostname inventory entry'
  inventory | grep -Fxq -- "$target" || die 'certificate is not in SUGARKUBE_STAGING_CERTIFICATES'
  IFS=/ read -r ns cert host <<<"$target"
  before="$(kubectl -n "$ns" get certificate "$cert" -o json)" || die 'certificate does not exist; do not force renewal until status is understood'
  cmctl renew -n "$ns" "$cert"
  kubectl -n "$ns" wait --for=condition=Ready "certificate/$cert" --timeout="$TIMEOUT" || die 'bounded Ready wait failed; stop retries and inspect status'
  kubectl -n "$ns" get secret "$(python3 -c 'import json,sys; print(json.load(sys.stdin)["spec"]["secretName"])' <<<"$before")" -o name >/dev/null
  after="$(kubectl -n "$ns" get certificate "$cert" -o json)"
  BEFORE="$before" AFTER="$after" python3 - <<'PY'
import json,os
b=json.loads(os.environ['BEFORE']).get('status',{}); a=json.loads(os.environ['AFTER']).get('status',{})
assert any(x.get('type')=='Ready' and x.get('status')=='True' for x in a.get('conditions',[])), 'certificate is not Ready'
assert a.get('revision') != b.get('revision') or a.get('notAfter') != b.get('notAfter'), 'revision and expiry did not change; stop rather than retrying'
PY
  for path in / /healthz /livez; do curl --fail --silent --show-error --max-time 15 --output /dev/null "https://${host}${path}"; done
  openssl s_client -connect "${host}:443" -servername "$host" -verify_hostname "$host" -verify_return_error </dev/null 2>/dev/null | openssl x509 -noout -dates >/dev/null
  status "$1"
}
case "${1:-}" in
  status) status "${2:-}";;
  install-token) install_token "${2:-}";;
  verify-authorization) verify_authorization "${2:-}";;
  recover) recover "${2:-}" "${3:-}";;
  *) die 'usage: staging_cert_manager.sh status|install-token|verify-authorization|recover staging [namespace/certificate/hostname]';;
esac
