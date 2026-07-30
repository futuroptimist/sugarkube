# Staging certificate operations

This staging-only runbook repairs DNS-01 authorization without changing Ingress TLS or
Cloudflare Tunnel transport. The declarative inventory is
`clusters/staging/certificates.json`; it is derived from the three app-owned staging
values files. Its complete current shared-zone set is `danielsmith.io`,
`jobbot3000.tech`, and `token.place`.

## Shared-token contract

The token referenced by `cert-manager/cloudflare-api-token` needs **Zone - Zone -
Read** and **Zone - DNS - Edit**, with resource access to each explicit authoritative
zone above. Do not select all zones. Preserve `token.place`: it is a known working
user of the same credential. Secret existence and key-name validation cannot prove
Cloudflare dashboard permissions; an operator must confirm them, or DNS-01 must
successfully present a challenge.

Editing permission or resource scope on the existing Cloudflare token does **not**
require a Kubernetes Secret update. If a replacement token is created, grant all
three zones first, retrieve it from the credential vault, and run:

```console
just cert-manager-cloudflare-token-secret env=staging
```

The guarded prompt requires the exact `sugar-staging` context, uses hidden
`read -r -s`, disables tracing, rejects empty input, sends the value only over stdin
to `kubectl create secret --from-file=api-token=/dev/stdin ... | kubectl apply -f -`,
and unsets it on success, failure, or interruption. Confirmation reveals no value,
length, digest, prefix, or suffix. It does not mutate Cloudflare.

## One certificate at a time

ACME attempts are rate limited. Never delete a Certificate, CertificateRequest,
Order, Challenge, or serving Secret as routine repair, and never retry both failing
certificates concurrently.

1. Confirm `kubectl config current-context` is `sugar-staging`, then capture a
   redacted baseline with `just staging-cert-status env=staging`. The report orders
   inventory deterministically, links resources by owner references, calls only the
   newest Request chain active, bounds and sanitizes reasons, checks issuer Secret
   name/key without printing data, and checks TLS Secret presence by name only.
2. In Cloudflare, manually confirm both permissions and the complete explicit zone
   inventory. The observed `Found no Zones` is consistent with insufficient token
   scope, but is not conclusive without this checkpoint.
3. Update the Secret only if the token value changed, using the hidden installer.
4. Start with Danielsmith. Run
   `just staging-cert-wait env=staging certificate=danielsmith-staging-tls timeout=300`.
   This bounded read-only loop allows existing pending Challenges to retry and does
   not create another Order.
5. Only if that times out and an operator approves one targeted attempt, run
   `just staging-cert-renew env=staging certificate=danielsmith-staging-tls timeout=300`.
   It observes the existing chain first, then runs `cmctl renew` for exactly that
   namespace/name. Re-run the bounded wait; do not use an unbounded loop.
6. Require `Ready=True`, a present Secret and revision, completed Order/Challenge
   state, and no new active `Found no Zones`. Run
   `just staging-cert-verify env=staging certificate=danielsmith-staging-tls`; it
   reads only `tls.crt` and prints SAN, issuer, serial, and dates. It never requests
   `tls.key`.
7. If the topology exposes direct Traefik TLS, separately test the origin with
   `openssl s_client -connect <origin-address>:443 -servername staging.danielsmith.io`
   and confirm it presents the Kubernetes certificate. Do not put credentials in the
   command.
8. Independently verify the public Cloudflare edge certificate with
   `openssl s_client -connect staging.danielsmith.io:443 -servername staging.danielsmith.io`,
   then request `/`, `/healthz`, and `/livez` with `curl --fail --show-error`.
   Cloudflare edge TLS and Kubernetes/origin TLS are separate layers under the
   current HTTP tunnel; their issuers and serials are not expected to match.
9. Only after every Danielsmith checkpoint passes, repeat steps 4–8 for
   `jobbot3000-staging-tls` and `staging.jobbot3000.tech`.

If errors persist, stop retries and retain the resources for diagnosis. Recovery is
to correct scope or enter a prior known-good token from the credential vault—not to
export it from Kubernetes. Rollback means stop attempts and re-enter that prior token
through the installer. This repository performs no live operation; issuance remains
a post-merge operator task.
