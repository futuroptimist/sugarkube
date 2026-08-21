---
personas:
  - software
---

# Terraform and Ansible Integration Design (Forward-Looking, Not Yet Implemented)

> **Status: forward-looking and documentation-only.** This design provides neither authorization nor
> implementation for live infrastructure changes. Every apply, host mutation, deployment, and
> production action described below requires a later, separately reviewed change and explicit
> operator authorization.

## 1. Overview and current status

Terraform and Ansible solve different problems. Terraform manages stateful external resources through
provider APIs and makes proposed changes, applies, and drift visible. Ansible manages idempotent
post-boot host configuration over SSH. They complement, rather than replace, the existing layers.

> **Central decision:** Terraform and Ansible are complementary across infrastructure layers, but
> mutually exclusive at the individual-resource level: every resource has exactly one authoritative
> writer.

Today, the [app deployment contract](../app_deployment_contract.md) and Helm/Just workflows remain
authoritative for application deployment and Kubernetes resources. Any resources already owned by
Flux remain Flux-owned. Image building and initial bootstrap remain governed by the existing Pi
tooling. A human using a provider dashboard is also an explicit current owner, not an ownership gap;
automation may replace that owner only through the handoff protocol below.

The registrar and domain transfer lock remain manually managed, with the transfer lock enabled.
Adopting selected Cloudflare resources into Terraform requires neither unlocking nor transferring a
domain. The repository currently only reserves space for future automation in
[`infra/README.md`](../../infra/README.md); no Terraform or Ansible implementation exists here.

At the time this design was written, [GitShelves onboarding PR #2662](https://github.com/futuroptimist/sugarkube/pull/2662)
was **open and onboarding was in progress**, not merged or deployed. Its runbook is therefore linked
through the PR rather than through a nonexistent path on this branch. This design does not duplicate
that work or address its review comments. After it merges, GitShelves must remain deployed exclusively
through the generic app/Helm contract it introduces.

## 2. Problem statement

- External infrastructure, including selected Cloudflare DNS resources, remains manually managed.
- Node configuration and maintenance responsibilities are split among image building, bootstrap
  scripts, Just recipes, and operator procedures.
- Manual changes provide limited plan, drift, idempotence, and ownership evidence.
- Sugarkube needs gradual automation without replacing working Helm deployment, Pi imaging,
  [observability](../observability-design.md), verification, or rollback workflows.

## 3. Goals and non-goals

### Goals

- Declarative, reviewable external infrastructure and repeatable, idempotent node baselines.
- Staging-first adoption with clear isolation between staging and production.
- Auditable ownership, plans, check-mode output, verification evidence, and rollback.
- Reusable operational improvements across all hosted applications.

### Non-goals

- No implementation, live mutation, or production rollout occurs in this documentation task or pilot.
- No big-bang rewrite of current scripts, image tooling, or automation.
- Terraform does not manage Helm releases, Kubernetes objects or Secrets, or host configuration.
- Ansible does not manage Cloudflare or other provider resources, Helm releases, or Kubernetes objects.
- Terraform uses no provisioners, `local-exec`, `remote-exec`, `null_resource`, command-trigger
  resources, or invocation of Ansible, Helm, or Just.
- CI performs no automated Terraform apply or destroy during the pilot.
- No premature module framework, Terragrunt, policy engine, or new orchestration platform is added.

## 4. One-writer ownership model

“Proposed owner” means a possible owner after the complete handoff; it is not authorization to change
the current owner.

| Resource or responsibility | Current authoritative writer | Proposed owner / boundary |
| --- | --- | --- |
| Registrar settings and domain transfer lock | Registrar dashboard operator | Remains manual and locked |
| Physical Raspberry Pis, power, and storage media | Hardware operator | Remains manual |
| Base Pi image and initial bootstrap | Existing image builder, first-boot tooling, and operator workflow | Remains existing tooling; not initially Ansible |
| Selected Cloudflare DNS and future provider-managed external resources | Cloudflare dashboard operator until each handoff | Terraform, one imported resource at a time |
| Shared Cloudflare Tunnel public-hostname configuration | Dashboard/operator procedure described by the [Tunnel runbook](../cloudflare_tunnel.md) | Remains manual initially; one Terraform root may later own the complete configuration |
| Post-boot packages, users, files, sysctl settings, time synchronization, and systemd services | Existing scripts/image/bootstrap or manual operator, item by item | Ansible only after an exact responsibility is handed off |
| k3s host configuration and maintenance | Existing bootstrap, `just ha3`, scripts, and operator runbooks | Unchanged during pilot; future ownership is undecided |
| Application images and charts | Each application repository and publishing workflow | Unchanged |
| Helm releases and Kubernetes resources | Existing Helm/Just lifecycle | Unchanged; Terraform and Ansible excluded |
| Flux-owned resources, where applicable | Flux and its active Git source | Remains Flux; no parallel Helm/Just, Terraform, or Ansible writer |
| Blackbox probes and observability manifests | Existing staging Helm/Just and manifest lifecycle; Flux only where explicitly active | Preserved per [blackbox runbook](../observability-blackbox.md); no Terraform or Ansible ownership |
| Secrets | Existing runtime secret installation/provider mechanisms and authorized operators | Never Terraform state or committed Ansible data; Kubernetes Secrets stay in the existing lifecycle |
| Just recipes and CI | Repository maintainers and current workflows | Orchestrate or verify their existing scopes only; never become a second resource writer |
| Any manual/dashboard-managed resource awaiting migration | Named dashboard/operator procedure | Remains manual until a documented handoff completes |

A hostname repeated in DNS, shared Tunnel ingress, Helm Ingress, and blackbox probes is a
**cross-layer contract**, not permission for multiple tools to manage the same underlying resource.
Verification must establish that DNS resolves as intended, the complete Tunnel ingress selects the
intended Traefik service, the Helm-owned Ingress has the same host and service contract, TLS is valid,
the declared public paths succeed, and the corresponding probe targets are healthy. A mismatch stops
the rollout; it does not justify one layer editing another layer's object.

### Handoff protocol

1. Inventory the exact resource and its current writer.
2. Capture its configuration, identity, dependencies, and rollback evidence.
3. Import or adopt it in staging.
4. Require an exact zero-change Terraform plan or zero-change Ansible check, where applicable.
5. Verify behavior through the current runbook.
6. Retire and document the previous writer.
7. Only then authorize the new writer to mutate that resource.

Until step 6 is evidenced, the previous owner remains authoritative and the candidate automation is
read-only.

## 5. Conceptual repository layout

This possible layout is illustrative; **none of it is created by this design**:

```text
infra/
  terraform/
    README.md
    cloudflare/
      staging/
      production/
    modules/
  ansible/
    ansible.cfg
    inventories/
      staging/
      production/
    playbooks/
    roles/
      sugarkube_node_baseline/
```

Staging and production use separate Terraform roots and separate state, rather than workspaces sharing
a root. A shared module should be extracted only after a genuinely repeated pattern exists.
Inventories contain only non-secret host metadata. The first implementation PR may finalize a
different exact layout while preserving these boundaries.

## 6. Terraform state, authentication, and safety

- Remote state must be independent of the k3s cluster so cluster loss cannot remove the recovery
  control plane. It requires encryption, locking, version history or backups, access controls, and
  separate staging and production state.
- Provider credentials must be least-privilege and supplied at runtime through environment variables
  or workload identity. State and saved plans are sensitive artifacts.
- Never commit state, plan files, `.terraform/`, backend credentials, API tokens, secret-bearing
  variables, or secret-bearing outputs.
- Terraform's `sensitive` marking only redacts some display. **It does not prevent a value from
  entering state.** Tunnel connector tokens, k3s tokens, Kubernetes Secrets, and application
  credentials must never intentionally enter Terraform state.
- Credential-free CI may run formatting, `terraform init -backend=false`, validation, and tests. It
  must not run authenticated plans or applies during the pilot.
- Provider lock files belong in a later implementation PR, not this documentation task.

## 7. Ansible inventory, authentication, and safety

The current staging node inventory is [`sugarkube3`, `sugarkube4`, and
`sugarkube5`](../../clusters/staging/nodes.txt). An initial Ansible inventory may cover those names
only after runtime reachability and identity validation.

- Use SSH agent/configuration, strict host-key checking, Tailscale connectivity where applicable as
  designed in [Tailscale remote operations](tailscale-remote-ops.md), and runtime privilege-escalation
  credentials. Store no SSH keys, pass&#x77;ords, tokens, or secret variables in Git.
- Prefer native idempotent modules over arbitrary shell commands. Gather facts and run read-only
  preflight checks before any mutation.
- Use `--check --diff`, explicit inventory limits, serial/canary execution, and readiness/quorum
  checks around disruptive changes. A second convergence run must report `changed=0`.
- Do not initially take over Pi imaging, `just ha3`, `/etc/rancher/k3s/config.yaml`, application
  deployment, or existing scripts.
- Migrate one exact file, service, or package responsibility at a time, and retire its former writer
  afterward. `no_log` reduces output; it is not a secret-storage mechanism.

## 8. Tool workflow and handoffs

```text
Terraform: external provider resources
        ↓ verified cross-layer contract
Ansible: shared host baseline and node readiness
        ↓ verified node/cluster health
Existing Helm/Just or Flux workflow: application deployment
        ↓
Existing public endpoint, artifact, rollout, and observability verification
```

These stages remain independently invocable during the pilot. Terraform must never invoke Ansible.
If Terraform later provisions hosts, an external operator workflow may pass only sanitized outputs or
dynamic inventory to Ansible; that workflow must not collapse their ownership or credentials.

## 9. GitShelves pilot

Because PR #2662 is open, GitShelves onboarding is **in progress** and no deployment or merge is
claimed. The phases are gates, not a single run:

1. **Phase A — design:** merge this documentation only.
2. **Phase B — scaffolding:** add credential-free Terraform and Ansible scaffolding in separate
   implementation PRs.
3. **Phase C — disposable DNS lab:** manage a disposable Cloudflare TXT record such as
   `tf-lab.gitshelves.com` through plan, reviewed apply, DNS verification, deliberate drift,
   reconciliation, a final no-op plan, and destroy. No production resource participates.
4. **Phase D — staging DNS adoption:** inventory `staging.gitshelves.com`. Import its existing DNS
   record and require an exact zero-change plan before Terraform becomes authoritative; create it only
   if inspection proves it does not exist. Confirm that no dashboard operator, other Terraform state,
   or ExternalDNS controller also owns it, then explicitly retire the prior writer.
5. **Phase E — host preflight:** run facts and read-only checks against the staging nodes for
   architecture, reachability, time synchronization, disk capacity, service state, and k3s readiness.
6. **Phase F — one baseline responsibility:** adopt one low-risk, reversible responsibility with
   serial execution, pre/post readiness checks, rollback proof, and a second run showing `changed=0`.
7. **Phase G — application deployment:** only after PR #2662 merges, deploy GitShelves through its
   unchanged generic Helm/Just workflow. Verify the public route and TLS; `/`, `/healthz`, `/livez`,
   required STL downloads, rollout state, and blackbox coverage using the contract and procedures
   introduced by that PR.

The shared Cloudflare Tunnel hostname route stays manual initially. Remotely managed ingress is the
**full configuration for a shared tunnel**: Terraform must not adopt only the GitShelves route while
other routes have independent owners. A later adoption must inventory and atomically import the
complete staging ingress configuration into one root and state, verify every existing hostname, and
retire its previous writer together.

The production hostname, production artifact pin, production Cloudflare resources, and every
production deployment action remain blocked until a separately reviewed promotion. GitShelves
browser-local data must never enter Terraform state, Ansible inventory, Kubernetes storage, or
backups. This design deliberately pins no changing image tag, chart version, or probe count.

## 10. Existing-application operational roadmap

Every row begins with staging inventory/import, an exact zero-change adoption plan, explicit
retirement of the old writer, public verification, and a reversible rollback before production is
considered.

| Application | Terraform opportunity | Ansible opportunity | Preserved existing authority | Verification | Rollback |
| --- | --- | --- | --- | --- | --- |
| [DSPACE](../apps/dspace.md) | Later adopt selected external DNS and edge configuration. | Later make the host-local synthetic runner, its systemd service/timer, and dependencies reproducible, one responsibility at a time. | Preserve manifest approval and finalized release evidence, Helm revision flow, provider identity, metrics-secret contracts, and current release/rollback gates. | Preserve runtime `/chat`, public-path, rollout, metrics, and release-integrity verification in the runbook and [synthetic producer design](../dspace-chat-synthetic-producer.md). | Revert provider configuration through its owner; use the exact retained synthetic revision and existing fail-closed Helm/manifest rollback gates. |
| [token.place](../apps/tokenplace.md) | Later adopt selected external DNS and edge configuration. | Initially only the shared cluster-node baseline and controlled node maintenance. | Helm remains authoritative for relay, Valkey, and all other Kubernetes resources. Registration, end-to-end encryption material, runtime credentials, and connector secrets stay outside Terraform state and Ansible variables/logs. | Run generic public/rollout checks plus the runbook's relay, registration, privacy, and end-to-end checks. | Revert provider configuration or node responsibility independently; retain the documented Helm/tag rollback. |
| [danielsmith.io](../apps/danielsmith.md) | Later adopt DNS, redirects, and applicable edge policy. | Supply consistent shared-node prerequisites. | Preserve Helm ownership of the app, metrics sidecar/configuration, and existing runtime-data contracts; do not invent credentials for components that require none. | Run the documented public paths, TLS, rollout, image, and metrics checks. | Revert edge configuration or node baseline independently; redeploy the prior known-good Helm artifact. |
| [jobbot3000](../apps/jobbot3000.md) | Adopt only real, verified staging DNS/edge resources; never put a placeholder `.example.test` production hostname into state. | Supply only the common node baseline. | Preserve the generic Helm lifecycle. Browser IndexedDB and private job data remain outside Terraform, Ansible, Kubernetes storage, and backups. | Run generic public-path, TLS, rollout, artifact, and blackbox checks. | Revert edge or baseline changes independently and redeploy the prior known-good immutable artifact through the generic workflow. |

## 11. Drift, failure handling, rollback, and emergencies

- Review and explain drift before applying; an unexpected plan is an investigation, not an approval.
- Never hand-edit Terraform state during normal operations. State locking prohibits concurrent applies.
- `destroy` is appropriate for the disposable lab, not the default rollback for adopted resources.
  Normal real-resource rollback reverts reviewed configuration and applies that reversion.
- Ansible uses check/diff, handlers, canaries or `serial: 1`, and pre/post cluster readiness checks.
  Stop on quorum or readiness degradation.
- Record emergency manual changes immediately, then either codify them in the authoritative writer or
  revert them. Break glass does not silently establish a second permanent owner.
- Existing Helm rollback and application-specific verification procedures remain intact and are not
  coupled to provider or host rollback.

## 12. Alternatives and remaining decisions

### Rejected alternatives

- Terraform-only or Ansible-only infrastructure management: neither tool safely owns both API
  resources and post-boot hosts.
- Terraform-managed Kubernetes objects or Helm releases, and Ansible-managed provider resources: both
  violate the established layer boundary.
- Terraform invoking Ansible: it couples state convergence to host orchestration and encourages
  provisioner-like behavior.
- One command that automatically mutates every layer during the pilot: independent review and failure
  isolation are required.
- A big-bang migration of existing scripts and image tooling: working owners remain in place until
  responsibility-level handoffs prove parity.

### Follow-up decisions

- Remote-state backend selection.
- The exact first Ansible-managed baseline responsibility.
- Inventory privacy and distribution approach.
- The complete shared Cloudflare Tunnel import/adoption shape.
- Whether and how existing k3s host configuration should eventually migrate.
- Production approval and evidence requirements.

## 13. Success criteria

### Acceptance for this documentation task

- The design establishes one authoritative writer per resource and makes current versus proposed
  behavior unambiguous.
- GitShelves reflects PR #2662's actual open status.
- Terraform, Ansible, Helm/Just, Flux, image/bootstrap tooling, and manual ownership boundaries are
  explicit.
- State, credential, secret, Tunnel, drift, handoff, and rollback hazards are covered.
- Each requested application has a concrete, non-disruptive roadmap.
- The diff contains documentation only and no infrastructure implementation or live mutation.

### Future pilot success

- The disposable Terraform lifecycle and drift exercise complete safely.
- Imported staging DNS produces an exact zero-change plan before adoption, and Terraform produces a
  no-op plan after convergence.
- Ansible check mode succeeds across all staging nodes and a second convergence run reports
  `changed=0`.
- GitShelves deploys through the unchanged generic Helm workflow and passes public, health, required
  artifact, rollout, and observability verification.
- No secret or state leaks into Git, logs, or CI artifacts.
- No production or existing-application behavior changes during the pilot.
- Every later application adoption is isolated, verified, and reversible.

## Related documentation

- [`infra/README.md`](../../infra/README.md) — reserved home for future infrastructure helpers.
- [Application deployment contract](../app_deployment_contract.md) — existing artifact and generic
  Helm/Just lifecycle authority.
- [App-agnostic platform design](app-agnostic-platform.md) — forward-looking application contract.
- [Cloudflare Tunnel runbook](../cloudflare_tunnel.md) — current hostname-route and verification
  procedures.
- [Observability design](../observability-design.md) and [blackbox runbook](../observability-blackbox.md)
  — existing monitoring ownership and verification.
- [DSPACE](../apps/dspace.md), [token.place](../apps/tokenplace.md),
  [danielsmith.io](../apps/danielsmith.md), and [jobbot3000](../apps/jobbot3000.md) runbooks — preserved
  application-specific deployment, evidence, and rollback contracts.
