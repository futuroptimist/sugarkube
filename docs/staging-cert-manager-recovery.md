# Staging cert-manager Cloudflare recovery

## Scope, boundaries, and observed state

This operator runbook is only for the `sugar-staging` context. The recipes fail closed for every
other environment or context. They do not manage production, Flux, application releases,
Cloudflare dashboard settings, or the remotely managed Cloudflare Tunnel. In particular, the
tunnel's current HTTP connection to Traefik is a separate hardening issue and must not be changed
during this recovery.

The live observation on 2026-07-29 was:

| Certificate | State | Detail |
| --- | --- | --- |
| `tokenplace/tokenplace-staging-tls` | `Ready=True`, revision 1 | Serving Secret exists. |
| `danielsmith/danielsmith-staging-tls` | `Ready=False`, `DoesNotExist` | Order and Challenge pending; serving Secret missing. |
| `jobbot3000/jobbot3000-staging-tls` | `Ready=False`, `DoesNotExist` | Order and Challenge pending; serving Secret missing. |

Both failing Challenges reported `Found no Zones` and advised checking `Zone.read` rights. The
`letsencrypt-production` ClusterIssuer was Ready and its shared
`cert-manager/cloudflare-api-token` Secret existed. All three Certificates are created by their
Helm-managed Ingresses. Public HTTPS was still available through Cloudflare edge certificates;
that does not prove origin certificate issuance works.

## Least-privilege token contract

Create or rotate an API token in the correct Cloudflare account with exactly these permissions:

* **Zone / Zone / Read**;
* **Zone / DNS / Edit**.

Resource access must explicitly include the authoritative zones `token.place`, `danielsmith.io`,
and `jobbot3000.tech`. Do not use an all-zones grant unless a separately documented operational
reason requires it. The repository cannot verify dashboard policy directly; an authorized operator
must review it without copying the credential into an issue, log, test, or file.

## Configure the inventory and inspect first

Set the non-secret, app-owned inventory. Shared implementation contains no application branches:

```bash
export SUGARKUBE_STAGING_CERTIFICATES=$'tokenplace/tokenplace-staging-tls/staging.token.place\ndanielsmith/danielsmith-staging-tls/staging.danielsmith.io\njobbot3000/jobbot3000-staging-tls/staging.jobbot3000.tech'
just staging-cert-status env=staging
```

The read-only report includes each Certificate's Ready condition, issuer, DNS name, Secret
presence, revision, validity and renewal times, plus related CertificateRequests, Orders,
Challenges, and events. Messages containing credential-related terms are replaced with
`[redacted]`; Secret values are never printed or decoded. Active pending resources are labeled
separately from stale or completed ones.

## Install or rotate the operator-managed token

First select the exact context and re-check the dashboard contract above:

```bash
kubectl config use-context sugar-staging
just staging-cert-token-install env=staging
```

The recipe reads hidden input when attached to a terminal. For a non-interactive operator session,
pipe the token from an appropriately protected credential-vault or file command to the recipe's
standard input. Do not type it into the command line, export it, enable shell tracing, redirect the
rendered Secret, or save it in Git. The implementation uses
`--from-file=api-token=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -`; the token is never
an argument and rendered YAML travels only through the pipe.

Then perform read-only structural authorization checks:

```bash
just staging-cert-authorization-verify env=staging
```

This proves the production issuer is Ready, references exactly Secret `cloudflare-api-token` key
`api-token`, the Opaque Secret has exactly that key, and the configured certificate inventory is
healthy. It cannot prove Cloudflare resource authorization until a DNS-01 Challenge succeeds.

## One-certificate recovery and external verification

Let's Encrypt enforces duplicate-certificate and other issuance rate limits. Repeated renewal,
deletion, or recreation attempts can exhaust them. Do not delete a Certificate, serving Secret,
CertificateRequest, Order, or Challenge as a first response. Wait for an attempt to finish and
inspect its state. Recover exactly one failing certificate in an authorized maintenance window:

```bash
just staging-cert-recover env=staging certificate=danielsmith/danielsmith-staging-tls/staging.danielsmith.io
```

The guarded recipe runs one `cmctl renew`, waits at most five minutes for `Ready=True`, requires the
serving Secret, and requires revision or expiry to change. It then performs TLS-verified requests
to `/`, `/healthz`, and `/livez`, and uses OpenSSL hostname and chain verification against the
externally served endpoint. TLS verification is never disabled. Finally it prints the redacted
resource report so the new Request, Order, Challenge, revision, expiry, renewal time, and events
can be recorded. Inspect it and confirm the new Challenge is complete without `Found no Zones`.

Only after the first certificate and all external paths succeed, repeat once for the second:

```bash
just staging-cert-recover env=staging certificate=jobbot3000/jobbot3000-staging-tls/staging.jobbot3000.tech
```

If a certificate is already healthy and no controlled renewal is necessary, do not force one merely
to exercise the recipe. Record its Ready, revision, and expiry state instead.

## Failure handling and rollback

On any bounded-wait or verification failure, stop. Do not loop the recipe. Run the read-only status
recipe and inspect active resources and controller logs with an authorized, redaction-aware process.
Confirm the correct Cloudflare account, both permissions, all three resource zones, issuer
Secret/name/key, and the token's formatting before considering cleanup.

Rollback is credential rotation, not Kubernetes object deletion:

1. Restore the prior known-good token through `just staging-cert-token-install env=staging`, if it
   remains authorized and is available from the approved credential vault.
2. Stop all renewal attempts to protect Let's Encrypt rate-limit budget.
3. Retain every current serving TLS Secret where possible.
4. Inspect controller logs and active Requests, Orders, and Challenges before any destructive
   cleanup; escalate rather than guessing.
5. Re-run status and external TLS checks. Rotation does not change Flux or production state.

Cloudflare edge success can mask a missing origin Secret, and the tunnel currently uses HTTP to
Traefik. Therefore external HTTPS is necessary but not sufficient evidence; retain the Kubernetes
Ready/Secret/revision/expiry evidence too. Dashboard authorization and both controlled renewals
remain deliberate manual staging operations and are never run in CI.
