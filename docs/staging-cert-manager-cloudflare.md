# Staging cert-manager Cloudflare DNS-01 recovery

This app-agnostic runbook repairs the operator-managed Cloudflare token used by cert-manager in the
non-Flux staging cluster. It does not change app Helm releases, production, Cloudflare dashboard or
Tunnel configuration. The remotely managed Tunnel currently reaches Traefik over HTTP; that is a
separate hardening issue and **must not be changed as part of certificate recovery**.

## Recorded state (2026-07-29)

Operator-observed staging evidence showed `letsencrypt-production` Ready and the
`cert-manager/cloudflare-api-token` Secret present. `tokenplace/tokenplace-staging-tls` was Ready at
revision 1. `danielsmith/danielsmith-staging-tls` and
`jobbot3000/jobbot3000-staging-tls` were `False/DoesNotExist`; both had pending Orders and
Challenges reporting `Found no Zones` and no TLS Secret. All three Certificates are generated from
Helm-managed Ingress resources. Public HTTPS still worked through Cloudflare edge certificates;
that does not prove origin certificate issuance works.

## Least-privilege token contract

Create or edit the API token in Cloudflare's operator-only dashboard. It needs exactly:

* **Zone / Zone / Read**;
* **Zone / DNS / Edit**;
* resource access explicitly including `token.place`, `danielsmith.io`, and `jobbot3000.tech`.

Confirm the zones belong to the intended Cloudflare account. Do not use all-zone access unless an
operator separately documents why. Do not put the token in Git, Helm values, an environment
assignment, a command argument, shell history, tickets, logs, or captured command output.

## Redacted diagnosis

Select the exact staging context, then run the read-only inventory:

```bash
kubectl config use-context sugar-staging
just staging-certificates-status
```

The report covers Certificate readiness/reason, issuer, TLS Secret **presence**, revision,
`notBefore`, expiry (`notAfter`), renewal time, DNS names, owned CertificateRequests, Orders,
Challenges, relevant events, and issuer readiness. It never requests Secret data. Challenge/event
messages are defensively redacted. Review active resources before treating an old event as current.

## Install or rotate the operator-managed token

Both workflows are staging- and exact-context-guarded. Preferred interactive input is hidden:

```bash
SUGARKUBE_ENV=staging just cert-manager-cloudflare-token-secret
```

For automation, place the token alone in a permission-restricted temporary file, pass its path (not
its contents), then securely remove it according to the workstation's storage policy:

```bash
umask 077
read -r -s -p 'Cloudflare API token (hidden): ' TOKEN_INPUT
printf '\n'
test -n "${TOKEN_INPUT}"
TOKEN_FILE="$(mktemp)"
printf '%s' "${TOKEN_INPUT}" >"${TOKEN_FILE}"
unset TOKEN_INPUT
SUGARKUBE_ENV=staging just cert-manager-cloudflare-token-secret file="${TOKEN_FILE}"
rm -f "${TOKEN_FILE}"
```

The implementation streams the value to `kubectl create secret --from-file=api-"token"=/dev/stdin`,
then streams the rendered manifest directly to `kubectl apply -f -`. It never places the token in
argv or renders it to a repository file. Disable shell tracing and terminal recording before use.

Verify the non-secret authorization prerequisites:

```bash
SUGARKUBE_ENV=staging just staging-certificates-verify-authorization
just staging-certificates-status
```

This proves the expected Secret exists, the Ready issuer references its name/key, and current
Challenges no longer expose an authorization failure; it cannot inspect Cloudflare dashboard scope.

## One-certificate-at-a-time recovery

Let's Encrypt applies duplicate-certificate and other issuance rate limits. Repeated renewals or
deleting Certificates, CertificateRequests, Orders, Challenges, or serving Secrets can exhaust
limits and worsen an outage. Capture status, correct authorization, then attempt **one** affected
Certificate. The recipe has a bounded wait (10 minutes by default), requires revision or expiry to
change, and uses strict TLS verification for `/`, `/healthz`, and `/livez`.

```bash
just staging-certificates-status
SUGARKUBE_ENV=staging just staging-certificate-renew \
  certificate=danielsmith/danielsmith-staging-tls \
  hostname=staging.danielsmith.io timeout=10m
just staging-certificates-status
```

Confirm its new CertificateRequest, Order, and Challenge completed; the TLS Secret exists; Ready is
True; and revision/expiry advanced. Only after all checks pass, repeat once for
`jobbot3000/jobbot3000-staging-tls` and `staging.jobbot3000.tech`. If renewal is unnecessary, do not
force it merely to make the revision change. Compare the externally served certificate separately
with `openssl s_client -connect HOST:443 -servername HOST` while remembering Cloudflare may serve
its edge certificate rather than the Kubernetes Secret.

## Failure handling and rollback

Stop after a bounded failure; do not loop. Preserve the existing serving Secret. Inspect the
redacted status and cert-manager controller logs locally, taking care not to publish unreviewed
logs. Check wrong account, omitted zone resources, missing permissions, issuer Secret name/key,
malformed input, and app-specific DNS/Ingress configuration before destructive cleanup.

If rotation caused the failure, reinstall the prior known-good token through the same hidden/file
workflow (if it is still authorized), stop further renewal attempts, and re-run authorization and
status checks. If no known-good token exists, leave current serving Secrets intact and escalate to
the Cloudflare/cert-manager operators. Rollback never changes Helm/Flux ownership, production, or
the Tunnel transport.
