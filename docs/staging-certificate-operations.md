# Staging certificate operations

These operations are staging-only, app-agnostic, bounded, and intentionally do not
change Ingress TLS or Cloudflare Tunnel transport. The declarative inventory in
`clusters/staging/certificates.json` is derived from the staging values owned by each
application. Its complete shared-token zone set is currently `danielsmith.io`,
`jobbot3000.tech`, and `token.place`.

## Shared-token contract

The token referenced by `cert-manager/cloudflare-api-token` needs **Zone - Zone -
Read** and **Zone - DNS - Edit**, with resource access explicitly limited to every
zone in that inventory. Do not select all zones. A present Secret and Ready issuer
cannot prove dashboard permissions; an operator must confirm them in Cloudflare or
observe successful DNS-01 presentation.

Editing the existing token's permissions or resource scope in place requires no
Kubernetes Secret update. If the value is replaced, preserve all three zones,
especially the working `token.place`, then run `just
cert-manager-cloudflare-token-secret env=staging`. The prompt is hidden; the value
travels only over stdin, is never placed in argv, a file, rendered values, output,
or logs, and is unset on exit or interruption. Never export the old value from
Kubernetes.

## One certificate at a time

ACME retries and manual renewals can consume rate limits. Perform these checkpoints,
starting with Danielsmith and proceeding to Jobbot3000 only after it passes:

1. Capture a redacted baseline with `just staging-certificate-status env=staging`.
   It correlates the newest CertificateRequest, its Orders, and their Challenges by
   owner UID. Challenges on that chain are **active**; older owned chains are
   **stale**. Reasons are length-bounded and scrubbed of URLs, query strings,
   authorization values, token-like values, and key material.
2. In Cloudflare, manually confirm both permissions and the exact three-zone list.
   Update the Secret only if the token value changed.
3. Give existing Challenges five minutes to converge without creating another
   Order: `just staging-certificate-wait namespace=danielsmith
   certificate=danielsmith-staging-tls timeout=300 env=staging`.
4. Only if that bounded wait fails and a retry is justified, run `just
   staging-certificate-renew namespace=danielsmith
   certificate=danielsmith-staging-tls timeout=300 env=staging`. This observes the
   existing chain first, then invokes `cmctl renew` for that exact Certificate and
   waits for bounded, redacted status. Never delete a Certificate,
   CertificateRequest, Order, Challenge, or serving Secret as normal recovery.
5. Require `Ready=True`, the expected Secret present, completed Order/Challenge
   state, and no new `Found no Zones`. Inspect only the public certificate:

   ```bash
   kubectl --context sugar-staging -n danielsmith get secret danielsmith-staging-tls \
     -o jsonpath='{.data.tls\.crt}' | base64 -d | \
     openssl x509 -noout -subject -issuer -serial -dates -ext subjectAltName
   ```

   Never select, decode, print, compare, or export `tls.key`.
6. If the topology exposes direct Traefik TLS, connect to that origin with the
   hostname/SNI and validate it presents this Kubernetes certificate. Separately
   validate the public Cloudflare edge certificate and routes:

   ```bash
   openssl s_client -connect staging.danielsmith.io:443 -servername staging.danielsmith.io </dev/null 2>/dev/null | openssl x509 -noout -issuer -serial -dates -ext subjectAltName
   curl -fsS https://staging.danielsmith.io/
   curl -fsS https://staging.danielsmith.io/healthz
   curl -fsS https://staging.danielsmith.io/livez
   ```

   The HTTP tunnel makes Kubernetes/origin TLS and Cloudflare edge TLS independent
   layers. Their issuers and serials need not match.
7. Repeat steps 1–6 for `jobbot3000/jobbot3000-staging-tls` and
   `staging.jobbot3000.tech`; do not renew them concurrently.

If failures continue, stop retries and re-check the authoritative-zone selection.
Rollback means stopping issuance attempts and re-entering a prior known-good token
from the password manager with the interactive installer. It never means extracting
credentials from the cluster. These are post-merge live operations; offline tests do
not establish that issuance succeeded.
