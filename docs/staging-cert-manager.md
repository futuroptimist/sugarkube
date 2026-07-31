# Staging cert-manager DNS-01 recovery

This operator runbook diagnoses and recovers Cloudflare DNS-01 certificates without crossing the
staging, application, Flux, or production boundaries. It does **not** change the remotely managed
Cloudflare Tunnel, which currently connects to Traefik over HTTP and is a separate hardening task.
The public Cloudflare edge certificate can keep HTTPS working even when the Kubernetes TLS Secret
is absent, so public success alone does not prove cert-manager health.

## Known state (2026-07-29)

`letsencrypt-production`, the cert-manager token Secret, and
`tokenplace/tokenplace-staging-tls` (revision 1) were Ready. The Helm/Ingress-managed Certificates
`danielsmith/danielsmith-staging-tls` and `jobbot3000/jobbot3000-staging-tls` were
`False/DoesNotExist`; their TLS Secrets were absent and their active Orders and Challenges were
pending with `Found no Zones` / `Zone.read` authorization errors. Treat this as dated evidence and
run the status recipe before acting.

## Least-privilege token contract

Create an operator-managed Cloudflare API token in the correct account with exactly:

- **Zone / Zone / Read**;
- **Zone / DNS / Edit**;
- explicit resource access to `token.place`, `danielsmith.io`, and `jobbot3000.tech`.

Do not use all zones unless a separately documented operational need justifies it. Do not commit
the token, add it to Helm values, print or decode the Secret, or pass it through argv or a visible
environment assignment. The cert-manager Secret must be `cert-manager/cloudflare-api-token` with
key `api-token`, as referenced by both ClusterIssuers.

## Redacted diagnosis

The generic status command reads Certificate, CertificateRequest, Order, Challenge, issuer,
Secret metadata/presence, and relevant Events. It reports readiness/reason, DNS names, revision,
`notBefore`, expiry (`notAfter`), renewal time, active versus terminal Challenges, and redacts
credential-shaped event text. It never requests Secret data.

```bash
just cert-manager-certificate-status namespace=danielsmith certificate=danielsmith-staging-tls env=staging
just cert-manager-certificate-status namespace=jobbot3000 certificate=jobbot3000-staging-tls env=staging
```

Check whether an error belongs to an active Challenge rather than a completed/stale one. Confirm
the issuer name/kind, Secret name and key in the issuer manifest, authoritative zone, account, and
token resource scope. A malformed token or wrong Secret/key can resemble missing permissions.

## Install or rotate the token safely

Select the staging kube context first and verify it yourself. Every cluster-facing command refuses
to run unless `env=staging` is explicit and the current context is exactly `sugar-staging`. Every
subsequent `kubectl` and `cmctl` invocation also pins that context explicitly.

For hidden interactive input (preferred):

```bash
just cert-manager-cloudflare-token-secret env=staging
```

For an operator-owned mode-`0600` file, stream it without command substitution; securely remove
the file according to local policy afterward:

```bash
just cert-manager-cloudflare-token-secret env=staging < /operator/private/cloudflare-token
```

The recipe sends bytes to `kubectl create secret --from-file=api-token=/dev/stdin` and pipes its
client-side manifest directly to `kubectl apply -f -`. It suppresses rendered content and never
puts the credential in argv, shell history, logs, tests, or Git. It rejects pasted `Bearer …`
wrappers, embedded whitespace, and surrounding quote wrappers before running `kubectl`; paste or
stream only the token itself. Confirm only metadata:

```bash
kubectl -n cert-manager get secret cloudflare-api-token -o name
```

Before recovery, run the guarded structural verifier:

```bash
just cert-manager-certificate-verify-authorization namespace=danielsmith certificate=danielsmith-staging-tls env=staging
```

It requires the referenced issuer to be `Ready=True`, its Cloudflare solver to reference
`cert-manager/cloudflare-api-token` key `api-token`, that Secret to exist, and no related active
Challenge to report `Found no Zones`, Cloudflare error 9109 (`Invalid access token`), or Cloudflare
error 10502 (`Too many authentication failures`). Terminal Challenges and historical Events remain
visible in status for diagnosis but do not independently block a healthy current state. The gate
checks only Secret existence and never retrieves, decodes, or prints its value. These structural
checks cannot prove the token's Cloudflare dashboard scope;
only a successfully completed DNS-01 Challenge can do that. Do not call Cloudflare APIs in a way
that risks logging request headers.

Status and structural authorization verification require `kubectl`, but do not require `cmctl`.
Recovery additionally requires [`cmctl`](https://cert-manager.io/docs/reference/cmctl/). Install it
using the official guidance, then confirm that the executable and client are available before the
controlled recovery:

```bash
command -v cmctl
cmctl version --client
```

The recovery command fails before authorization or renewal when `cmctl` is unavailable; it does
not fall back to another renewal mechanism.

## One certificate at a time

Let's Encrypt applies duplicate-certificate and other issuance rate limits. Repeated renewals or
deleting Certificates, Secrets, CertificateRequests, Orders, or Challenges can exhaust them.
Inspect first, make one attempt, and stop on failure. Prefer the ACME staging issuer for rehearsals;
these existing Ingress-managed staging Certificates currently reference the production issuer, so
do not silently change issuer or Helm/Flux ownership here.

1. Capture the redacted status above, then run `cert-manager-certificate-verify-authorization`.
   The Certificate itself need not already be Ready: recovery exists to repair that condition.
   If the active Challenge reports 9109 or 10502, stop manual retries. Correct and reinstall an
   invalid credential through the hidden-input recipe when needed. For authentication throttling,
   wait for Cloudflare throttling to clear before retrying this read-only gate; do not assume a
   fixed cooldown. Treat `Found no Zones` as a zone authorization problem and correct account,
   zone, or token scope before retrying the gate. Recovery will not call `cmctl renew` while any of
   these blockers is active.
2. Run **one** recovery with the matching namespace, Certificate, and DNS name. The command uses
   `cmctl renew`, bounds its wait (default ten minutes), requires `Ready=True`, Secret creation,
   and a revision or expiry change, then uses normal TLS verification for `/`, `/healthz`, and
   `/livez`.

   ```bash
   just cert-manager-certificate-recover namespace=danielsmith certificate=danielsmith-staging-tls host=staging.danielsmith.io env=staging timeout=600
   ```

3. Review the final redacted resource chain. Confirm the new Order and Challenge are valid and no
   active Challenge reports a Cloudflare authentication or zone-authorization blocker. Confirm the
   externally served certificate identity and dates independently if Cloudflare edge termination
   makes them differ from the Kubernetes Secret; never disable TLS verification.
4. Only after the first certificate passes, repeat for Jobbot3000:

   ```bash
   just cert-manager-certificate-recover namespace=jobbot3000 certificate=jobbot3000-staging-tls host=staging.jobbot3000.tech env=staging timeout=600
   ```

## Failure and rollback

On any timeout or failed path, stop; do not loop. Preserve the currently serving TLS Secret where
one exists. Inspect the redacted status and bounded cert-manager controller logs before considering
destructive cleanup. Restore the prior known-good token through the same hidden-input/stdin recipe
if it is available, then re-check metadata and issuer readiness. Token rollback cannot undo a
consumed ACME issuance attempt. Escalate wrong-account or zone-scope changes to the Cloudflare
operator, and leave app Helm releases, Flux resources, production, and Tunnel transport unchanged.
