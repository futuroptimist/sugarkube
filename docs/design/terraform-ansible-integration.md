---
personas:
  - software
---

# Terraform and Ansible Integration Design (Forward-Looking, Not Yet Implemented)

> **Status and authority:** This is a forward-looking, documentation-only design. It implements no
> infrastructure, authorizes no live infrastructure change, and authorizes no production rollout.
> Every proposed mutation requires a later, separately reviewed implementation and operator approval.

## Overview and current status

> **Phase B status:** The credential-free Terraform and Ansible validation foundations now exist.
> Live Ansible preflight, node convergence, Terraform state/backend selection, DNS resources,
> Cloudflare adoption, and every production implementation remain unimplemented and unauthorized.

Terraform and Ansible address different layers. Terraform manages stateful external resources through
provider APIs and makes proposed changes, applies, and drift visible. Ansible manages idempotent
post-boot host configuration over SSH. They complement the existing platform rather than replacing it.

The central decision is:

> **Terraform and Ansible are complementary across infrastructure layers, but mutually exclusive at
> the individual-resource level: every resource has exactly one authoritative writer.**

Today, the [app deployment contract](../app_deployment_contract.md) and its Helm/Just workflows remain
authoritative for application deployment and Kubernetes resources. Existing Flux ownership also
remains authoritative wherever it applies. The [observability design](../observability-design.md)
distinguishes the live guarded Helm lifecycle from inactive or future Flux manifests; this proposal
does not combine those writers. Image building, bootstrap scripts, operator procedures, and the
[Cloudflare Tunnel runbook](../cloudflare_tunnel.md) retain their current responsibilities. A resource
managed in a provider dashboard or by a person is explicitly **manual/dashboard-owned** until it
completes the handoff protocol below; “manual” does not mean “unowned.”

GitShelves onboarding in [PR #2662](https://github.com/futuroptimist/sugarkube/pull/2662) was **open and
in progress when this design was written on 2026-08-21**. It is not represented here as merged or
deployed. This document neither duplicates that onboarding nor addresses its review comments. After
that PR merges, GitShelves must remain deployed exclusively through the generic app/Helm contract it
introduces.

The registrar and its domain-transfer lock remain manually owned, with the transfer lock enabled.
Adopting selected Cloudflare resources in Terraform requires neither unlocking the domain nor
transferring its registration.

## Problem statement

- Selected external infrastructure, including Cloudflare DNS resources, remains manually managed.
- Node configuration and maintenance are divided among Pi image building, initial bootstrap scripts,
  Just recipes, and operator procedures.
- Manual changes provide limited plan, drift, idempotence, and ownership evidence.
- Sugarkube needs gradual automation without replacing working Helm deployment, Pi imaging,
  observability, verification, or rollback workflows.

## Goals

- Make selected external infrastructure declarative and reviewable.
- Make carefully selected node baselines repeatable and idempotent.
- Adopt in staging first, with clear isolation between staging and production.
- Preserve auditable ownership, plans, Ansible check-mode output, verification evidence, and rollback.
- Reuse operational improvements safely across every hosted application.

## Non-goals

- No implementation, credential use, deployment, or live mutation occurs in this documentation task.
- No production rollout occurs during the pilot, and current automation is not rewritten wholesale.
- Terraform does not manage Helm releases, Kubernetes objects or Secrets, or host configuration.
- Ansible does not manage Cloudflare or other provider resources, Helm releases, or Kubernetes objects.
- Terraform provisioners, `local-exec`, `remote-exec`, `null_resource`, command-trigger resources, and
  invocation of Ansible, Helm, or Just are prohibited.
- CI does not automatically run Terraform apply or destroy during the pilot.
- No premature module framework, Terragrunt, policy engine, or new orchestration platform is proposed.

## One-writer ownership model

“Proposed future owner” does not become authoritative merely because it appears in this table. The
current owner remains authoritative until a documented handoff is complete.

| Resource or concern | Current authoritative writer | Permitted future writer and boundary |
| --- | --- | --- |
| Registrar settings and domain transfer lock | Registrar dashboard/operator | Manual only; lock stays enabled. |
| Physical Raspberry Pis, disks, wiring, and power | Hardware operator | Manual only. |
| Base Pi image and initial bootstrap | Existing image builder and bootstrap scripts | Remain authoritative; not initial Ansible scope. |
| Selected Cloudflare DNS and future provider-managed external resources | Manual/dashboard or an identified existing controller | One isolated Terraform root/state, but only after handoff. |
| Shared Cloudflare Tunnel public-hostname configuration | Cloudflare dashboard/operator | Manual initially; a later complete, atomic Terraform adoption is possible. |
| Post-boot packages, users, files, sysctl settings, time synchronization, and systemd services | Image/bootstrap/scripts/operator, responsibility by responsibility | Ansible may adopt one exact responsibility at a time; never a category-wide implicit takeover. |
| k3s host configuration and maintenance | Existing bootstrap, Just recipes, and operator runbooks | Existing tools remain authoritative; any later Ansible handoff is a separate decision. |
| Application images and charts | Application repositories and release workflows | Unchanged. |
| Helm releases and Helm-owned Kubernetes resources | Existing Helm/Just application workflow | Unchanged; never Terraform or Ansible. |
| Flux-owned Kubernetes resources, where applicable | Flux | Unchanged until an explicit migration retires Flux for the exact resource. |
| Blackbox probes and observability manifests | Existing guarded Helm/Just or applicable Flux lifecycle documented by observability runbooks | Unchanged; never Terraform or Ansible. |
| Secrets | Existing runtime secret-installation/operator mechanisms and Kubernetes secret owner | Neither Terraform nor Ansible becomes a general secret store. |
| Just recipes and CI | Repository source and GitHub Actions | Unchanged; they validate and orchestrate existing workflows, not Terraform resource ownership. |
| Any manual/dashboard resource awaiting migration | Named operator/dashboard | Manual remains the owner until handoff completes. |

The same hostname appearing in DNS, remotely managed Tunnel ingress, a Helm Ingress, and blackbox
probes is a **cross-layer contract**, not permission for several tools to write one underlying
resource. Verification must show that DNS resolves to the intended edge, the complete Tunnel ingress
routes the hostname to the intended Traefik service, the Helm-owned Ingress selects the intended
service, TLS is valid, expected public paths respond, and the corresponding blackbox targets are
healthy. A mismatch blocks promotion; it does not justify one layer overwriting another.

### Handoff protocol

For each exact resource or host responsibility:

1. Inventory the resource and name its current writer.
2. Capture its current configuration, dependencies, environment, and rollback evidence.
3. Import or adopt it in staging.
4. Require an exact zero-change Terraform plan, or a zero-change Ansible check where applicable.
5. Verify behavior using the current runbook.
6. Retire the previous writer for that exact resource.
7. Only then authorize the new writer to mutate it.

If the previous writer cannot be retired, the handoff stops. Ownership is not shared temporarily “for
convenience.”

## Conceptual repository layout

No paths below are created by this design. A first implementation PR may finalize the exact layout:

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

Staging and production use separate Terraform roots and separate state, not workspaces that obscure
the boundary. Shared modules are extracted only after a genuinely repeated pattern exists. Ansible
inventories contain non-secret host metadata only and keep staging and production visibly separate.

## Terraform state, authentication, and safety

- Remote state must be independent of the k3s cluster so a cluster outage cannot remove the recovery
  control plane. It requires encryption, locking, version history or backups, access controls, and
  separate staging and production state.
- Provider credentials must be least privilege and supplied at runtime through the environment or
  workload identity. State and plans are sensitive artifacts with restricted retention and access.
- Never commit state, saved plan files, `.terraform/`, backend credentials, API tokens,
  secret-bearing variables, or secret-bearing outputs.
- Terraform's `sensitive` marking only redacts normal display; it **does not prevent a value from
  entering state**. Tunnel connector tokens, k3s tokens, Kubernetes Secrets, and application
  credentials must never intentionally enter Terraform configuration, plans, or state.
- Credential-free CI may run formatting, `terraform init -backend=false`, validation, and tests. It
  may not run authenticated plans, applies, or destroys during the pilot.
- Provider lock files belong in a later implementation PR, not this documentation task.
- State locking prohibits concurrent applies. Normal operations never hand-edit state.

## Ansible inventory, authentication, and safety

Repository evidence identifies `sugarkube3`, `sugarkube4`, and `sugarkube5` as the current staging
nodes. The initial staging inventory covers those three names only, after the implementation PR
revalidates them against live operator inventory.

- Use SSH agent/configuration, strict host-key checking with out-of-band fingerprint validation,
  Tailscale connectivity where applicable, and runtime privilege-escalation credentials. Follow the
  [Tailscale remote-operations design](tailscale-remote-ops.md); never commit SSH keys, login
  passphrases, tokens, or secret variables.
- Prefer native idempotent modules to arbitrary shell commands. Gather facts and run read-only
  preflight checks before any mutation.
- Use `--check --diff`, explicit inventory limits, serial/canary execution, and readiness/quorum
  checks before and after disruptive work. A second convergence run must report `changed=0`.
- Initially do not take over Pi imaging, `just ha3`, `/etc/rancher/k3s/config.yaml`, application
  deployment, or any existing script.
- Migrate one exact file, service, or package responsibility at a time, then retire its previous
  writer. A role name does not grant ownership of every related host setting.
- `no_log` reduces output but is **not** secret storage. Secrets remain in an approved runtime
  mechanism and must not enter inventory, variable files, cached facts, or logs.

## Tool workflow and handoffs

```text
Terraform: external provider resources
        ↓ verified cross-layer contract
Ansible: shared host baseline and node readiness
        ↓ verified node/cluster health
Existing Helm/Just or Flux workflow: application deployment
        ↓
Existing public endpoint, artifact, rollout, and observability verification
```

Each stage remains independently invocable during the pilot. Terraform never invokes Ansible. If
Terraform later provisions hosts, an external operator workflow may pass only sanitized outputs or a
sanitized dynamic inventory to Ansible; it must not turn Terraform into a command orchestrator.

## GitShelves staging pilot

Because PR #2662 is open, GitShelves onboarding is **in progress**, not deployed or merged. The pilot
waits for that PR to merge, and then preserves its generic Helm/Just deployment contract.

### Phases

- **A — design:** merge only this documentation. Make no live change.
- **B — scaffolding:** add credential-free Terraform and Ansible scaffolding in separate, reviewable
  implementation PRs.
- **C — disposable DNS lab:** manage a disposable Cloudflare TXT record such as
  `tf-lab.gitshelves.com`. Exercise plan, reviewed manual apply, DNS verification, deliberate drift,
  explained reconciliation, no-op plan, and reviewed destroy. CI does not apply or destroy it.
- **D — adopt staging DNS:** inventory `staging.gitshelves.com`. Import its existing DNS record and
  require an exact zero-change plan before Terraform becomes authoritative. Create the record only if
  inspection proves it does not exist. Confirm that no dashboard operator, other Terraform state, or
  ExternalDNS controller also owns it, then explicitly retire its former writer.
- **E — host preflight:** use Ansible against the three staging nodes for facts and read-only checks of
  architecture, reachability, time synchronization, disk capacity, relevant service state, and k3s
  readiness.
- **F — bounded convergence:** adopt one low-risk, reversible node-baseline responsibility with
  canary/serial execution, health gates, rollback, and a second run reporting `changed=0`.
- **G — application deployment:** deploy GitShelves only through the existing generic Helm/Just
  workflow. Verify the public route and TLS; `/`, `/healthz`, and `/livez`; required STL downloads;
  Helm/Kubernetes rollout state; and blackbox coverage using the app contract and current repository
  procedures introduced by PR #2662.

The shared Cloudflare Tunnel hostname route stays manual initially. Remotely managed ingress is the
**full configuration of a shared tunnel**, not an independently safe resource per route. Terraform
must not adopt only GitShelves while other routes remain independently owned. A later adoption must
inventory the entire staging ingress configuration and atomically import it into one root/state, with
every route and fallback represented and its prior writer retired.

The production hostname, production artifact pin, production Cloudflare resources, and every
production deployment action remain blocked pending separately reviewed promotion. Browser-local
GitShelves data must never enter Terraform state, Ansible inventory, Kubernetes storage, or backups.
This durable design intentionally pins no image tag, chart version, or probe count while PR #2662 is
changing the application and observability matrix.

## Existing-application operational roadmap

Every row requires staging-first inventory/import, an exact zero-change adoption plan, explicit
retirement of the old writer, public verification, and a reversible rollback before production is
considered.

| App | Terraform opportunity | Ansible opportunity | Preserved existing authority | Verification | Rollback |
| --- | --- | --- | --- | --- | --- |
| [DSPACE](../apps/dspace.md) | Later adopt selected external DNS and edge configuration. | Later make the host-local synthetic runner, dependencies, and systemd service/timer reproducible, one responsibility at a time. | App artifacts; approved manifest and finalized release evidence; Helm revision flow; provider identity and metrics-secret contracts; current `/chat` and rollback gates. | Current artifact, rollout, public-path, runtime `/chat`, provider, metrics, and observability procedures. | Revert edge configuration; for the app, retain manifest-approved recovery and its fail-closed gates rather than inventing a generic rollback. |
| [token.place](../apps/tokenplace.md) | Later adopt selected external DNS and edge configuration. | Initially only shared cluster-node baseline and controlled node maintenance. | Helm owns relay, Valkey, and other Kubernetes resources. Registration, E2EE material, runtime credentials, and connector secrets stay outside Terraform state and Ansible variables/logs. | Current public health/diagnostics, relay-compute journey, rollout, encryption/privacy, and observability checks. | Revert edge configuration or use the documented Helm revision procedure for an app-caused regression. |
| [danielsmith.io](../apps/danielsmith.md) | Later adopt DNS, redirects, and applicable edge policy. | Supply consistent shared-node prerequisites only. | Helm owns the app, metrics sidecar/configuration, and runtime-data contracts. The current public GitHub metrics cache needs no invented credential. | Existing public health paths, rollout, and manual runtime-cache checks. | Revert edge configuration or use the documented Helm revision rollback, then repeat runtime checks. |
| [jobbot3000](../apps/jobbot3000.md) | Adopt only real, verified staging DNS/edge resources; never put the placeholder `.example.test` production hostname into state. | Supply the common node baseline only. | Preserve the generic Helm lifecycle. Browser IndexedDB and private job data remain outside Terraform, Ansible, Kubernetes storage, and backups. | Existing public health/content, rollout, TLS, and observability procedures. | Revert edge configuration or use the generic documented Helm rollback; browser data is not a cluster rollback target. |

These opportunities automate shared operations without weakening app-specific contracts. In
particular, DSPACE keeps its manifest approval, finalized evidence, provider identity, metrics-secret,
runtime `/chat`, and rollback requirements; token.place preserves relay-blind end-to-end encryption;
danielsmith.io keeps its existing runtime cache contract without fictitious secrets; and jobbot3000
keeps private state in the browser.

## Drift, failure handling, rollback, and emergency changes

- Review and explain drift before applying. A plan is evidence for review, not authorization by
  itself. Never hand-edit Terraform state during normal operation.
- Destroy is expected for the disposable lab only; it is not the default rollback for adopted
  resources. Real-resource rollback normally reverts reviewed configuration and applies that
  reversion. State locking prevents concurrent applies.
- Ansible uses check/diff, handlers, a canary or `serial: 1`, and pre/post cluster readiness and quorum
  checks. Stop before later hosts when health deteriorates.
- Record an emergency manual change promptly, then either codify it in the authoritative writer or
  revert it. A break-glass action never silently creates a second permanent owner.
- Existing Helm rollback and each app's public, artifact, rollout, and observability verification
  remain intact. Infrastructure rollback must not conceal an app failure, or vice versa.

## Alternatives rejected and decisions deferred

### Rejected

- **Terraform-only management:** provider state is a poor host-configuration mechanism.
- **Ansible-only management:** SSH convergence lacks provider-native state/import/plan semantics.
- **Terraform-managed Kubernetes objects or Helm releases:** this would compete with Helm/Just or
  Flux and violate the deployment contract.
- **Ansible-managed provider resources:** this discards Terraform's state and adoption model.
- **Terraform invoking Ansible:** this couples failure domains and encourages provisioners.
- **One command that mutates every layer during the pilot:** stages must remain independently
  reviewable and invocable.
- **Big-bang migration of scripts and image tooling:** working owners remain until exact handoffs.

### Follow-up decisions

- Select the remote-state backend and its locking, recovery, retention, and access model.
- Select the exact first Ansible-managed baseline responsibility.
- Decide private inventory distribution without placing secrets or sensitive topology in Git.
- Define and test the complete shared Cloudflare Tunnel import/adoption shape.
- Decide whether and how any existing k3s host configuration eventually migrates.
- Define production approval roles and required plan, verification, and rollback evidence.

## Success criteria

### This documentation task

- The design establishes one authoritative writer per resource and makes current versus proposed
  behavior unambiguous.
- GitShelves is described according to PR #2662's open status.
- Terraform, Ansible, Helm/Just, Flux, image/bootstrap tooling, and manual ownership are explicit.
- State, credential, secret, Tunnel, drift, handoff, failure, and rollback hazards are covered.
- Every requested app has a concrete, non-disruptive operational roadmap.
- The diff contains documentation only and no infrastructure implementation or live mutation.

### Future pilot

- The disposable Terraform lifecycle and deliberate-drift exercise complete safely.
- Imported staging DNS produces an exact zero-change plan before adoption, and Terraform produces a
  no-op plan after convergence.
- Ansible check mode succeeds on all staging nodes, and a second convergence reports `changed=0`.
- GitShelves deploys through the unchanged generic Helm workflow and passes public, health, artifact,
  rollout, and observability verification.
- No secret or state leaks into Git, logs, plans, state snapshots, or CI artifacts.
- No production or existing-application behavior changes during the pilot.
- Each later application adoption is isolated, verified, and reversible.

## Related documentation

- [`infra/README.md`](../../infra/README.md) reserves the future automation area.
- The [app deployment contract](../app_deployment_contract.md) defines Helm/Just artifact, deployment,
  verification, and rollback ownership.
- The [app-agnostic platform design](app-agnostic-platform.md) describes the generic application
  contract that GitShelves will use after its onboarding PR merges.
- The [Cloudflare Tunnel runbook](../cloudflare_tunnel.md) describes the current remotely managed,
  token-based shared Tunnel and public-hostname procedure.
- The [observability design](../observability-design.md) and
  [blackbox runbook](../observability-blackbox.md) define monitoring ownership and public verification.
- App-specific authority and evidence live in the [DSPACE](../apps/dspace.md),
  [token.place](../apps/tokenplace.md), [danielsmith.io](../apps/danielsmith.md), and
  [jobbot3000](../apps/jobbot3000.md) runbooks.
- Until it merges, GitShelves details belong to
  [PR #2662](https://github.com/futuroptimist/sugarkube/pull/2662), not a broken local runbook link.
