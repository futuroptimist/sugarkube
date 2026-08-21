---
personas:
  - software
---

# Terraform and Ansible Integration Design (Forward-Looking, Not Yet Implemented)

> **Status and authority:** This is a forward-looking, documentation-only design. It neither
> authorizes nor implements any live infrastructure change. No Terraform or Ansible configuration,
> credentials, state, plan, inventory, workflow, or deployment is introduced by this document.

## 1. Overview and current status

**Central decision:** Terraform and Ansible are complementary across infrastructure layers, but
mutually exclusive at the individual-resource level: every resource has exactly one authoritative
writer.

Terraform is proposed for stateful external resources exposed through provider APIs. It records
desired and observed state and makes proposed changes, completed changes, and drift visible through
`plan` and reviewed `apply` operations. Ansible is proposed for idempotent post-boot configuration of
hosts over SSH: packages, narrowly assigned files and services, and repeatable readiness checks.
Neither tool is a general-purpose replacement for the other.

Today the [app deployment contract](../app_deployment_contract.md) and its Helm/Just commands remain
authoritative for application deployment and Kubernetes resources. Existing Flux ownership also
remains authoritative wherever Flux reconciles a resource. The
[app-agnostic platform design](app-agnostic-platform.md) may improve that application contract, but
does not move its ownership to Terraform or Ansible. Pi image and bootstrap tooling retains its
current responsibilities. Manual or dashboard management is an explicit current owner—not an
ownership vacuum—until a documented handoff is complete.

[GitShelves onboarding PR #2662](https://github.com/futuroptimist/sugarkube/pull/2662) was **open**
when this design was written on 2026-08-21, so onboarding is **in progress**, not merged or deployed.
This design neither duplicates its files nor addresses its review comments. Once it merges,
GitShelves must remain deployed exclusively through the generic app/Helm contract it introduces.

The domain registrar and its transfer lock also stay manual. The lock remains enabled: adopting
selected Cloudflare resources does not require unlocking a domain or transferring its registration.
The [infrastructure placeholder](../../infra/README.md),
[Cloudflare Tunnel runbook](../cloudflare_tunnel.md), and
[observability design](../observability-design.md) describe adjacent current responsibilities.

## 2. Problem statement

- External infrastructure, including selected Cloudflare DNS resources, is still managed manually.
- Node configuration and maintenance are divided among image building, bootstrap scripts, Just
  recipes, and operator procedures.
- Manual changes provide limited plan, drift, idempotence, and ownership evidence.
- Sugarkube needs gradual automation without replacing working Helm deployment, Pi imaging,
  observability, verification, or rollback workflows.

The problem is therefore not a lack of automation everywhere. It is the lack of a safe, auditable
way to adopt carefully selected gaps without creating two writers for the same thing.

## 3. Goals and non-goals

### Goals

- Declarative, reviewable external infrastructure.
- Repeatable and idempotent node baselines.
- Staging-first adoption with clear staging/production isolation.
- Auditable ownership, plans, Ansible check-mode output, verification, and rollback.
- Reusable operational improvements across all hosted applications.

### Non-goals

- No implementation, deployment, or live mutation in this documentation task.
- No production rollout during the pilot and no big-bang rewrite of current automation.
- No Terraform-managed Helm releases, Kubernetes objects, Kubernetes Secrets, or host
  configuration.
- No Ansible-managed Cloudflare/provider resources, Helm releases, or Kubernetes objects.
- No Terraform provisioners, `local-exec`, `remote-exec`, `null_resource`, command-trigger
  resources, or invocation of Ansible, Helm, or Just.
- No automated Terraform apply or destroy in CI during the pilot.
- No premature module framework, Terragrunt, policy engine, or new orchestration platform.

## 4. One-writer ownership model

“Proposed owner” means a future handoff target, not authority granted by this document. Until a row's
handoff completes, its current owner remains the only writer.

| Resource | Current authoritative writer | Proposed authoritative writer | Boundary |
| --- | --- | --- | --- |
| Registrar settings and domain transfer lock | Registrar dashboard/operator | Manual/operator | Keep the lock enabled; provider adoption does not require a transfer. |
| Physical Raspberry Pis, power, disks, and cabling | Operator/hardware procedures | Manual/operator | Neither Terraform nor Ansible models physical custody. |
| Base Pi image and initial bootstrap | Existing image builder and bootstrap scripts | Existing tooling | Ansible begins only after a bootable, reachable host exists. |
| Selected Cloudflare DNS and future provider-managed external resources | Cloudflare dashboard/operator until handoff | Terraform, one state/root per adopted resource | Unadopted resources stay explicitly manual. |
| Shared Cloudflare Tunnel public-hostname configuration | Cloudflare dashboard/operator | Manual initially; possible later whole-configuration Terraform adoption | Never split one remotely managed ingress configuration between writers. |
| Post-boot packages, users, files, sysctl settings, time sync, and systemd services | Image/bootstrap/scripts/operator, per item | Ansible, one specifically handed-off item at a time | The ownership unit is the exact package, user, file, setting, or unit. |
| k3s host configuration and maintenance | Bootstrap scripts, Just recipes, and operator runbooks | Existing tooling during pilot | Ansible may check readiness but does not initially own k3s. |
| Application images and charts | Each application repository and its release workflows | Existing app repositories | Terraform and Ansible consume neither as managed resources. |
| Helm releases and Kubernetes resources | Helm/Just application workflow | Helm/Just | Includes Ingress and application workloads. |
| Flux-owned resources, where applicable | Flux and its Git source | Flux | No imperative tool may compete with reconciliation. |
| Blackbox probes and observability manifests | Existing observability manifests and lifecycle | Existing observability workflow | Follow the [blackbox runbook](../observability-blackbox.md). |
| Secrets | Existing runtime/operator secret procedures and Kubernetes Secret references | Existing secret owners | Secret values enter neither Terraform nor Ansible source. |
| Just recipes and CI | Repository source and reviewed workflows | Existing repository tooling | They validate/orchestrate their existing layer; they are not infrastructure resources. |
| Any dashboard-managed resource awaiting migration | Named dashboard/operator procedure | Manual/dashboard | It remains manual until the handoff protocol completes. |

### Cross-layer hostname contract

A public hostname legitimately appears in DNS, the shared Tunnel ingress, a Helm-managed Kubernetes
Ingress, and blackbox probes. That repetition is a **cross-layer contract**, not permission for
multiple tools to manage the same underlying DNS record, Tunnel configuration, Ingress, or Probe.
Verification must establish that:

1. authoritative DNS resolves to the intended Cloudflare edge;
2. the one complete Tunnel configuration maps the host to the intended Traefik service;
3. the Helm Ingress has the same host and a ready backend;
4. TLS validates for that host;
5. documented public paths return their expected behavior; and
6. the expected blackbox targets are discovered and healthy.

### Handoff protocol

Every ownership transfer follows this order:

1. Inventory the resource and current writer.
2. Capture its configuration and dependencies.
3. Import or adopt it in staging.
4. Require a zero-change Terraform plan or zero-change Ansible check, where applicable.
5. Verify behavior through the owning layer and the cross-layer contract.
6. Retire the previous writer and document that retirement.
7. Only then authorize the new writer to mutate the resource.

A failed or non-zero adoption preview stops the handoff; it is not an instruction to “apply until
clean.”

## 5. Conceptual repository layout

The first implementation PR may finalize an exact layout. A possible shape is:

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

Staging and production use separate Terraform roots **and separate state**, credentials, approvals,
and apply operations. Shared modules should be extracted only after a genuinely repeated pattern
exists; the pilot should not guess at an abstraction. Ansible inventories contain only non-secret
host metadata. This is a sketch, not directories to create in this documentation change.

## 6. Terraform state, authentication, and safety

- Store remote state outside and independently of the k3s cluster, with encryption, locking, version
  history or backups, access controls, and recovery procedures.
- Isolate staging and production state. A staging command must not be able to select production
  merely by changing a variable.
- Supply least-privilege provider credentials at runtime through environment variables or workload
  identity. Do not commit backend credentials or API tokens.
- Treat state and saved plans as sensitive. Never commit state, plan files, `.terraform/`, backend
  credentials, API tokens, secret-bearing variables, or secret-bearing outputs.
- Terraform's `sensitive` marking only redacts some display; **it does not prevent a value from
  entering state**. Tunnel connector tokens, k3s tokens, Kubernetes Secrets, and application
  credentials must never intentionally enter Terraform configuration, plans, or state.
- Credential-free CI may run formatting, `terraform init -backend=false`, validation, and tests. It
  must not run authenticated plans, applies, or destroys during the pilot.
- State locking prohibits concurrent applies. Provider lock files belong in a later implementation
  PR, not in this design task.

## 7. Ansible inventory, authentication, and safety

The current repository identifies the staging nodes as `sugarkube3`, `sugarkube4`, and
`sugarkube5`, including in the [staging ingress HA record](../staging-ingress-ha.md). The initial
staging inventory should cover those names only after an implementation PR revalidates reachability
and identity.

- Use operator SSH agent/configuration, strict host-key checking, and Tailscale connectivity where
  applicable, consistent with the [Tailscale remote-operations design](tailscale-remote-ops.md).
  Provide privilege-escalation credentials at runtime.
- Commit no SSH private keys, authentication phrases, access tokens, vault unlock material, or
  secret variables.
- Prefer native idempotent modules to arbitrary shell commands. Gather facts and run read-only
  preflight checks before any mutation.
- Use `--check --diff`, explicit inventory limits, serial/canary execution, and cluster
  readiness/quorum gates around disruptive work. After an authorized convergence, a second run must
  report `changed=0`.
- Do not initially take over Pi imaging, `just ha3`, `/etc/rancher/k3s/config.yaml`, application
  deployment, or an existing script's responsibility.
- Migrate one exact file, service, or package responsibility at a time, then retire its previous
  writer. A broad role name is not evidence of ownership transfer.
- `no_log` reduces output but is **not** a secret-storage mechanism. Secret values remain in an
  approved runtime secret system and out of inventory, variables committed to Git, logs, and facts.

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

Each stage stays independently invocable during the pilot. Terraform must never invoke Ansible (or
Helm or Just), and a failure in one layer must not trigger automatic mutation in another. If
Terraform later provisions hosts, an external operator workflow may pass sanitized, non-secret
outputs or dynamic inventory to Ansible after validating host identity and readiness.

## 9. GitShelves staging pilot

Because PR #2662 remains open, GitShelves onboarding is in progress and its runbook is not on this
branch. Consult [the PR](https://github.com/futuroptimist/sugarkube/pull/2662), not a broken relative
link. Nothing below claims that GitShelves, its route, or its probes are deployed.

### Phases

- **Phase A—design:** merge this document only. Perform no infrastructure mutation.
- **Phase B—scaffolding:** use separate implementation PRs for credential-free Terraform and
  Ansible scaffolding. Do not add provider lock files until the applicable implementation PR.
- **Phase C—disposable DNS:** use a deliberately disposable Cloudflare TXT record such as
  `tf-lab.gitshelves.com`. Demonstrate reviewed plan and apply, DNS verification, deliberate drift,
  drift review, reconciliation, a no-op plan, and reviewed destroy. The lab is the only resource for
  which destroy is the planned ending.
- **Phase D—staging DNS adoption:** inventory `staging.gitshelves.com`. Import/adopt its existing DNS
  record and demand an **exact zero-change plan before Terraform becomes authoritative**; create it
  only when inspection proves it does not exist. Confirm no dashboard operator, other Terraform
  state, or ExternalDNS controller also owns it, then retire dashboard mutation for that record.
- **Phase E—read-only hosts:** gather facts from `sugarkube3`, `sugarkube4`, and `sugarkube5` and
  preflight architecture, reachability, time synchronization, disk capacity, relevant service state,
  and k3s readiness. This grants Ansible no configuration ownership.
- **Phase F—one baseline item:** separately approve one low-risk, reversible package, file, or
  service responsibility; execute with a canary or `serial: 1`, verify readiness and quorum, and
  require the second convergence run to report `changed=0`.
- **Phase G—application:** only after #2662 merges, deploy GitShelves through the unchanged generic
  Helm/Just workflow. Terraform and Ansible do not perform or trigger this deployment.

Keep the shared Cloudflare Tunnel hostname route manual initially. Remotely managed Tunnel ingress is
represented as the **full configuration for a shared tunnel**. Terraform must not adopt only the
GitShelves route while other routes remain independently owned. Any later Tunnel handoff must first
inventory every staging public hostname and then atomically import the complete staging ingress
configuration into one root and state. Partial ownership risks deleting or overwriting unrelated
routes.

Use the eventual GitShelves runbook plus the [deployment contract](../app_deployment_contract.md),
[Tunnel runbook](../cloudflare_tunnel.md), and
[blackbox procedures](../observability-blackbox.md) to verify the public route, TLS, `/`, `/healthz`,
`/livez`, required STL downloads, Helm rollout state, and blackbox coverage. Durable contract checks
are intentional here; this design does not freeze an image tag, chart version, or probe count while
#2662 is changing the app and observability matrix.

The production hostname, production artifact pin, production Cloudflare resources, and every
production deployment action remain blocked until a separately reviewed promotion. GitShelves
browser-local data must never enter Terraform state, Ansible inventory, Kubernetes storage, or
backups.

## 10. Existing-application operational roadmap

Every opportunity below is conditional on staging inventory/import, an exact zero-change adoption
plan, explicit retirement of the old writer, public verification, and a reversible rollback before
production is considered.

| Application | Terraform opportunity | Ansible opportunity | Preserved existing authority | Verification | Rollback |
| --- | --- | --- | --- | --- | --- |
| DSPACE | Later adopt selected external DNS and edge configuration. | Later make the host-local synthetic runner, its systemd unit/timer, and dependencies reproducible, one responsibility at a time. | Preserve manifest approval, finalized release evidence, provider identity and metrics-secret contracts, and the Helm revision/evidence flow documented in the [DSPACE runbook](../apps/dspace.md) and [synthetic producer guide](../dspace-chat-synthetic-producer.md). | Existing artifact and rollout proof, runtime `/chat`, public paths, provider identity, metrics, and release-integrity gates. | Revert external config; for the app retain its manifest-approved rollback gates rather than substituting generic destroy. |
| token.place | Later adopt selected external DNS and edge configuration. | Initially only the shared cluster-node baseline and controlled node maintenance. | Helm remains authoritative for relay, Valkey, and all other Kubernetes resources under the [token.place runbook](../apps/tokenplace.md). Registration, end-to-end encryption material, runtime credentials, and connector secrets remain outside Terraform state and Ansible variables/logs. | Generic paths plus relay diagnostics, real registration and encrypted end-to-end behavior, rollout, and metrics contracts required by the runbook. | Revert reviewed edge config; retain the documented immutable-tag or intentional Helm revision application rollback. |
| danielsmith.io | Later adopt DNS, redirects, and applicable edge policy. | Supply consistent shared-node prerequisites only. | Preserve Helm ownership of the application, metrics sidecar/configuration, and runtime-data contract in the [danielsmith.io runbook](../apps/danielsmith.md). Do not invent credentials for its currently unauthenticated public metrics-cache source. | Public and health paths, rollout, sidecar logs, and `/runtime/github-metrics.json` schema/content checks. | Revert reviewed edge config and use the runbook's known-good immutable tag or intentional Helm revision flow. |
| jobbot3000 | Adopt only real, inspected staging DNS/edge resources; never put the placeholder `.example.test` production hostname into state. | Supply the common node baseline. | Preserve the [generic Helm lifecycle](../apps/jobbot3000.md). Browser IndexedDB and private job data remain outside Terraform, Ansible, Kubernetes storage, and backups. | Real staging DNS/Tunnel/TLS, public and health paths, rollout, and existing blackbox checks. | Revert reviewed edge config and redeploy the previous immutable application tag; do not “restore” browser-local data from infrastructure. |

These changes improve every app by making external-resource drift reviewable and node prerequisites
repeatable without collapsing app-specific evidence or secret boundaries into a lowest-common-
denominator workflow.

## 11. Drift, failure handling, rollback, and emergency changes

- Review and explain drift before applying; unexpected drift is an investigation, not an automatic
  repair instruction. Terraform state must never be hand-edited during normal operations.
- Lock state for every apply. `destroy` is appropriate for the disposable lab, not the default
  rollback for adopted resources. Normal real-resource rollback reverts reviewed configuration and
  applies that reversion, preserving the resource where possible.
- Ansible uses check/diff previews, handlers, canaries or `serial: 1`, and pre/post cluster readiness
  and quorum checks. A failed readiness check stops the batch.
- Record emergency manual changes promptly, then either codify them in the authoritative writer or
  revert them. Break-glass access does not silently create a second permanent owner.
- Existing Helm rollback, public verification, and app-specific gates remain intact. Infrastructure
  recovery never implies that an application release is healthy.

## 12. Alternatives and decisions

### Rejected

- **Terraform-only management:** provider state is a poor host configuration system.
- **Ansible-only management:** SSH convergence lacks provider-native external-resource state and
  planning.
- **Terraform-managed Kubernetes or Helm releases:** this would compete with Helm/Just or Flux.
- **Ansible-managed provider resources:** this would erase the intended provider-state boundary.
- **Terraform invoking Ansible:** it couples lifecycles and encourages provisioners/command triggers.
- **One command that mutates every layer during the pilot:** independent review and failure domains
  are a safety property.
- **Big-bang migration of current scripts and image tooling:** working, tested ownership is retained
  until one-resource handoffs prove a safer replacement.

### Follow-up decisions

- Remote-state backend selection and recovery testing.
- The exact first Ansible-managed baseline responsibility.
- Inventory privacy and distribution approach.
- The complete shared Cloudflare Tunnel import/adoption shape.
- Whether and how existing k3s host configuration should eventually migrate.
- Production approval, separation-of-duty, and evidence requirements.

## 13. Success criteria

### Acceptance for this documentation task

- The design establishes exactly one authoritative writer per resource and distinguishes current
  behavior from proposed behavior.
- GitShelves is described as onboarding in progress because #2662 is open.
- Terraform, Ansible, Helm/Just, Flux, image/bootstrap tooling, and manual ownership are explicit.
- State, credentials, secrets, shared-Tunnel adoption, drift, handoff, failure, and rollback hazards
  are covered.
- DSPACE, token.place, danielsmith.io, and jobbot3000 each have a concrete, non-disruptive roadmap.
- The diff contains documentation only and no infrastructure implementation or live mutation.

### Future pilot success

- The disposable Terraform lifecycle and deliberate drift exercise complete safely.
- Imported staging DNS produces an exact zero-change plan before adoption, and a post-convergence
  Terraform plan is a no-op.
- Ansible check mode succeeds on every staging node and a second convergence run reports
  `changed=0`.
- GitShelves deploys through the unchanged generic Helm workflow and passes public, health, required
  artifact, rollout, and observability verification.
- No secret or state leaks into Git, logs, plans, or CI artifacts.
- No production or existing-application behavior changes during the pilot.
- Every later app adoption remains isolated, verified, and reversible.
