# Staging certificate operations

This runbook repairs staging DNS-01 authorization without changing Ingress TLS or
Cloudflare Tunnel transport. All commands are staging-only and require the current
context to be exactly `sugar-staging`. They do not prove that live issuance has
succeeded until the live checks below pass.

## Shared Cloudflare credential contract

The declarative source of truth is
`clusters/staging/certificates.json`. Its current authoritative-zone inventory is
the complete set found in the staging app values that intentionally use the shared
cert-manager issuer: `danielsmith.io`, `jobbot3000.tech`, and `token.place`.
The shared token needs **Zone - Zone - Read** and **Zone - DNS - Edit**, scoped to
each of those three explicit zones—not all zones. Preserve the already-working
`token.place` access while repairing the other two.

A present Kubernetes Secret and a Ready ClusterIssuer validate only the configured
Secret name/key. Kubernetes cannot prove Cloudflare dashboard permissions or
resource scope. An operator must confirm them in Cloudflare, or successful DNS-01
presentation must demonstrate them. `Found no Zones` strongly suggests a scope or
permission problem, but is not conclusive by itself.

Editing the existing Cloudflare token's permissions or resource scope in place
does **not** require a Kubernetes Secret update. If a replacement token is created,
use `just cert-token-install env=staging`. The guarded prompt is hidden, disables
shell tracing, rejects empty input, sends the value through stdin, and never puts
it in argv, an environment assignment, a rendered value, a temporary file, Git,
or output. Do not paste credentials into another recipe or log.

## Ordered, one-certificate repair

ACME attempts are rate limited. Complete Danielsmith before starting Jobbot3000;
reverse this only when a newly captured live baseline documents why.

1. Capture a redacted baseline: `just cert-status env=staging`. Manually confirm
   the permissions and all three zones above. Change the Secret only when the
   token value changed.
2. Let the existing Danielsmith Challenge retry rather than creating another
   Order: `just cert-wait certificate=danielsmith/danielsmith-staging-tls
   timeout=300 env=staging`. The bounded output correlates resources through owner
   references. A Challenge attached to a nonterminal current Order is **active**;
   terminal or superseded history is **stale**.
3. If that bounded wait expires and an operator confirms a targeted retry is
   necessary, run exactly once: `just cert-renew
   certificate=danielsmith/danielsmith-staging-tls timeout=300 env=staging`.
   This recipe itself observes the existing Challenge for that bounded interval
   and skips renewal if it converges. Never delete a
   Certificate, CertificateRequest, Order, Challenge, or serving Secret as the
   normal repair. Never renew both applications concurrently.
4. Run the bounded wait again. Require `Ready=True`, `secretPresent=true`, no
   active pending/failed Order or Challenge, and no new `Found no Zones`. Then run
   `just cert-verify certificate=danielsmith/danielsmith-staging-tls env=staging`.
   It reads only `tls.crt` and prints SAN, issuer, serial, and validity dates; it
   never reads `tls.key`. Confirm the revision advanced when renewal occurred.
5. If direct Traefik/origin TLS is reachable in the current topology, test it with
   the hostname/SNI and confirm it presents the Kubernetes certificate. Separately
   inspect public `https://staging.danielsmith.io`: Cloudflare edge TLS must be
   valid, but its issuer and serial are **not expected to match** the Kubernetes
   certificate because the tunnel currently reaches Traefik over HTTP. Verify
   `/`, `/healthz`, and `/livez` independently.
6. Only after every Danielsmith check passes, repeat steps 1–5 for
   `jobbot3000/jobbot3000-staging-tls` and `staging.jobbot3000.tech`.

## Stop, recovery, and rollback

Stop after a timeout, a new authorization error, or any unexpected resource. Do
not loop or delete ACME resources; capture another redacted status and diagnose.
Rollback means stopping retries and re-entering a prior known-good token from the
password manager with the guarded installer. Never export a credential from
Kubernetes. Confirm that the restored token still includes `token.place` before
resuming one certificate at a time.
