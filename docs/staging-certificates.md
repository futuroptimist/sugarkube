# Staging certificate operations

These operations are staging-only, one Certificate at a time, and do not change
Ingress TLS or the HTTP Cloudflare Tunnel origin. The declarative inventory in
`scripts/staging_certificate_inventory.json` is derived from the app-owned
staging values. It currently lists the shared token's complete intentional zone
set: `danielsmith.io`, `jobbot3000.tech`, and the already-working `token.place`.
Update that inventory when an app-owned staging TLS configuration changes.

## Shared Cloudflare token contract

The `cert-manager/cloudflare-api-token` token needs **Zone - Zone - Read** and
**Zone - DNS - Edit**, scoped explicitly to all three authoritative zones above.
Do not use “all zones” while this least-privilege list is possible. Secret
existence and key-name validation cannot prove Cloudflare dashboard permissions;
an operator must confirm them or observe successful DNS-01 presentation.

Editing the existing token's permissions or resource scope in place needs no
Kubernetes Secret update. If its value changes, use the hidden interactive
installer (never an argument, environment assignment, rendered value, log, or
temporary file):

```console
just cert-manager-cloudflare-token-secret env=staging
```

A replacement token must retain every shared zone, especially healthy
`token.place`. The installer requires current context `sugar-staging`, disables
tracing, uses hidden input and stdin, and clears the shell variable on exit or
interruption. Never export a prior token from Kubernetes; retrieve it from the
password manager. Cloudflare dashboard/API changes remain manual.

## Ordered repair runbook

ACME retries consume rate limits. Complete Danielsmith before starting Jobbot3000:

1. Confirm `kubectl config current-context` is exactly `sugar-staging`. Capture a
   redacted baseline with `just cert-status namespace=danielsmith
   certificate=danielsmith-staging-tls env=staging`.
2. Manually confirm both required permissions and the explicit three-zone scope.
   Update the Secret only if the token value changed.
3. Run `just cert-wait namespace=danielsmith
   certificate=danielsmith-staging-tls timeout=300 env=staging`. This bounded,
   read-only wait lets owned pending Challenges converge without creating Orders.
4. Only if it times out and the operator approves one rate-limited retry, run
   `just cert-renew namespace=danielsmith certificate=danielsmith-staging-tls
   timeout=300 env=staging`. It observes existing Challenges for the bounded
   interval **before** issuing one explicitly targeted `cmctl renew`. Never delete
   Certificates, Requests, Orders, Challenges, or serving Secrets.
5. Run the bounded wait again. Require `Ready=True`, TLS Secret present, completed
   current Order/Challenge state, and no new sanitized `Found no Zones` reason.
   `ACTIVE` means a pending/processing Challenge owned through the newest owned
   CertificateRequest and Order; older or no-longer-processing failures are
   `STALE` history.
6. Run `just cert-verify namespace=danielsmith
   certificate=danielsmith-staging-tls env=staging`. It reads only `tls.crt` and
   prints SAN, issuer, serial, and dates; it never reads `tls.key`.
7. If topology permits, test Traefik/origin TLS directly with SNI and verify it
   presents that Kubernetes certificate. Separately test public Cloudflare edge
   TLS validity and `https://staging.danielsmith.io/`, `/healthz`, and `/livez`.
   The HTTP tunnel makes origin and edge separate certificate layers; their
   issuers and serials need not match.
8. At a manual checkpoint, repeat steps 1–7 for `jobbot3000/jobbot3000-staging-tls`.
   Never renew both concurrently and never contact production.

On a fresh `Found no Zones`, stop retries and recheck dashboard scope. Recovery
is permission correction followed by the bounded observation sequence. Rollback
means stopping retries and re-entering a prior known-good token from the password
manager with the installer—not deleting ACME resources or exporting a Secret.
These are post-merge live operations; offline tests do not establish issuance.
