# Main Preview: a stable URL for healthy builds

**Status: proposed.** This change adds documentation and inert validation
fixtures only. Nothing watches these files or deploys from them.

## Purpose and scope

Open a durable URL from a phone to try recently merged work without moving a
staging release candidate or running commands on Sugarkube.

| Environment | What it tracks | What it proves |
| --- | --- | --- |
| Local development | A developer's checkout | Fast feedback |
| Main Preview | Newest eligible, healthy commit on protected main | Integrated behavior with preview data and services |
| Staging | An explicitly pinned release candidate | Release qualification and production-like behavior |
| Production | An explicitly promoted release | Live service for users |

Build and retain a traceable artifact for each new main SHA. For normal
one-merge-at-a-time pushes, build the event SHA. If multiple main commits
arrive in one push, enumerate the newly added first-parent SHAs rather than
claiming the push tip covers them all. Older builds need not become the live
preview; the stable URL is not a permanent URL per commit. Set retention
explicitly and protect the active and previous good artifacts from expiry.

## Use one policy with two deployment paths

1. **Portfolio first:** use a separate static hosting project, with a proposed
   host of `preview.danielsmith.io`. GitHub Actions uploads the tested static
   bundle; no Sugarkube credentials or capacity are needed. Exercise the 3D
   scene on mobile and deep links such as `/studio`. Use a checked-in fixture
   or disable the GitHub metrics enhancement rather than borrowing the live
   sidecar or its origin. This is not a test of Helm, ingress, or the sidecar.
   See the [portfolio runbook](apps/danielsmith.md) and
   [Cloudflare Pages CI deployment guide](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/).
2. **Container apps:** use protected Git desired state reconciled from inside
   a dedicated nonproduction cluster or an explicitly qualified preview slice.
   [Flux](https://fluxcd.io/flux/concepts/) is a candidate, not installed by
   this change. GitHub Actions publishes and checks artifacts and proposes or
   writes only preview-scoped desired state. Runners neither reach the home
   Kubernetes API nor receive a kubeconfig. Only the preview reconciler can
   apply that configuration. Use a distinct release, namespace, host, and
   service identity per app. A deployed release never reads these examples.

For DSPACE, start with the normal server image and mock inference. Do not use
a semantic release tag, a staging approval receipt, or production app
credentials; this path does not satisfy any release QA checkbox. For
token.place, first test the relay with synthetic requests. Live integration
requires a separately enrolled preview compute node, distinct keys and queues,
request limits, and no production resource fallback. Only when that split is
verified should DSPACE preview point at token.place preview.

## Candidate and promotion

The [example receipt](examples/main-preview/candidate.example.json) describes
one container build; the [schema](examples/main-preview/candidate.schema.json)
checks its shape. These fixtures neither authorize a deploy nor prove those
digests exist. The static pilot uses a tested bundle identity instead and
does not need a Helm chart. A later controller must independently verify:

1. **Source and artifacts.** Accept only a configured repository and its
   protected main ref. Verify the exact source SHA, producer workflow and
   successful check set, not just a self-reported status. Require registry
   identity and digest, provenance tying the image to the commit, a compatible
   pinned chart digest, and a tested image for the target architecture
   (ARM64 if this lands on the Pis). Never select mutable tags. A missing,
   canceled, skipped required check, incompatible artifact, or stale receipt
   is ineligible. A chart need not be republished per source commit if its
   unchanged digest is explicitly validated with the new image.
2. **Runtime checks.** Deploy the immutable candidate away from the stable
   URL. Check readiness, intended revision, app-specific behavior and
   representative assets through a restricted candidate endpoint. Verify the
   endpoint served the candidate SHA, not a previous response or another
   environment. Keep the last good stable target if anything fails.
3. **Promotion.** Serialize routing updates per app; immediately before
   changing the target, re-read protected main, the eligibility record and
   the current preview pointer. Only advance to the newest eligible
   descendant, with an atomic compare-and-set against the pointer. A delayed
   older run must not overwrite a newer healthy target. Do not infer ordering
   from completion time or compare SHA strings. An older healthy SHA may
   advance the view while a newer SHA is pending only if it is newer than
   the served SHA and still on protected main. If history was rewritten or a
   newer build won the race, stop and re-evaluate rather than force a switch.
4. **Verification and recovery.** Verify HTTPS, identity, and a basic smoke
   test on the stable URL after switching. Record source SHA, artifact
   identity, workflow and probe evidence. Expose the live SHA in a footer or
   build-info endpoint. If the final probe fails, restore the tested previous
   target only if the pointer still refers to this failed promotion, and
   quarantine the failed candidate until explicitly requalified. A manual
   rollback pins a known-good artifact and pauses automatic advancement until
   the operator resumes it. If there is no known-good target, leave the stable
   URL unavailable rather than serve an unchecked build.

The static pilot must also prove it can test a candidate without first
overwriting the durable host, and retain a known-good deployment for rollback.
Do not enable automation until that provider-specific switch is verified.

## Isolation before activation

- Use a preview-only deploy identity and desired-state path. Enforce a
  main-only [GitHub deployment environment](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments)
  and least privilege for the publish job. Fork or PR jobs never get
  deployment credentials. Do not reuse an account-wide deployment credential
  if it can modify the production service.
- Prefer a separate cluster for backend access to real network services.
  On a shared nonproduction cluster, a namespace alone is not an isolation
  boundary. Require enforced default-deny network policy with explicit
  ingress and egress exceptions, restricted workloads, namespace-scoped
  permissions and resource quotas. Verify that preview cannot reach prod
  services, cluster administration or private LAN destinations from the
  workload. Keep any shared uplink an infrastructure dependency only.
- Use preview-only data, secrets, storage, hostnames, TLS routes, cookie
  settings and metrics labels. Start owner-only for backend previews;
  protect direct provider and candidate URLs as well as the custom domain.
  Never grant preview workflows rights to change staging or production DNS.
- Any activation, credential setup or deployment is separate from this PR.
  There is no change to dev, staging, production, DNS, workflows, or cluster
  configuration here. Do not add preview as an alias for the existing
  Sugarkube staging or production app recipes.

## First rollout checks

- Preview serves a known main SHA and succeeds on mobile with no local
  computer or production credentials.
- Failed CI and a failed candidate smoke both leave the stable SHA unchanged.
- Overlapping builds finishing out of order do not regress the stable SHA.
- Rollback restores the last known-good SHA; an in-flight job does not undo it.
- Backend preview cannot read or write production state, use production
  inference, or alter staging and production deployments.
