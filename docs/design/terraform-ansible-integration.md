---
personas:
  - software
---

# Terraform and Ansible Integration Design (Forward-Looking, Not Yet Implemented)

> **Status: forward-looking and documentation-only.** This design provides neither authorization nor
> implementation of live infrastructure changes. It adds no Terraform or Ansible configuration and
> authorizes no mutation of GitHub, Cloudflare, DNS, hosts, clusters, applications, or production.

## 1. Overview and current status

Terraform and Ansible solve different parts of the operations problem. Terraform manages stateful
external resources through provider APIs and makes proposed changes, application, and drift visible
through its plan/apply/state model. Ansible manages idempotent post-boot host configuration over SSH.
They complement, rather than replace, the existing platform described by the
[infrastructure helpers overview](../../infra/README.md), [application deployment
contract](../app_deployment_contract.md), and [app-agnostic platform design](app-agnostic-platform.md).

The central decision is:

> **Terraform and Ansible are complementary across infrastructure layers, but mutually exclusive at
> the individual-resource level: every resource has exactly one authoritative writer.**

Today, Helm/Just and any resources already owned by Flux remain authoritative for application
deployment and Kubernetes resources. Image building, bootstrap scripts, observability tooling, and
operator procedures retain their existing responsibilities. Manual or dashboard management is an
explicit current owner, not an ownership vacuum, until a documented handoff completes.

The registrar and its domain-transfer lock remain manually managed, and the transfer lock remains
enabled. Adopting selected Cloudflare resources does not require unlocking or transferring a domain.

At execution time, [GitShelves PR #2662](https://github.com/futuroptimist/sugarkube/pull/2662) is
**open** (checked 2026-08-21), so GitShelves onboarding is **in progress**, not merged or deployed.
This design neither duplicates that onboarding nor addresses its review comments. Because its runbook
is absent from this branch, this document links to the PR rather than inventing a broken local link.

## 2. Problem statement

- External infrastructure, including selected Cloudflare DNS resources, remains manually managed.
- Node configuration and maintenance are divided among image building, bootstrap scripts, Just
  recipes, and operator procedures.
- Manual changes provide limited plan, drift, idempotence, and ownership evidence.
- Sugarkube needs gradual automation without replacing working Helm deployment, Pi imaging,
  observability, verification, or rollback workflows.

## 3. Goals and non-goals

### Goals

- Declarative, reviewable external infrastructure.
- Repeatable and idempotent node baselines.
- Staging-first adoption with clear staging/production isolation.
- Auditable ownership, plans, Ansible check-mode output, verification, and rollback.
- Reusable operational improvements for every hosted application.

### Non-goals

- No implementation, live mutation, or production rollout occurs in this documentation task or pilot.
- No big-bang rewrite of existing automation occurs.
- Terraform does not manage Helm releases, Kubernetes objects or Secrets, or host configuration.
- Ansible does not manage Cloudflare or other provider resources, Helm releases, or Kubernetes
  objects.
- Terraform uses no provisioners, `local-exec`, `remote-exec`, `null_resource`, command-trigger
  resources, or invocation of Ansible, Helm, or Just.
- CI does not automatically run Terraform apply or destroy during the pilot.
- No premature module framework, Terragrunt, policy engine, or new orchestration platform is added.

## 4. One-writer ownership model

“Current owner” is authoritative unless and until the handoff protocol below completes. A proposed
future owner is not permission to mutate a resource.

| Resource | Current authoritative writer | Possible future writer and boundary |
| --- | --- | --- |
| Registrar settings and domain-transfer lock | Registrar dashboard/operator | Manual only; lock stays enabled. |
| Physical Raspberry Pis, power, disks, and wiring | Hardware operator | Manual only. |
| Base Pi image and initial bootstrap | Existing image builder and bootstrap scripts/Just recipes | Unchanged; Ansible starts only after boot. |
| Selected Cloudflare DNS and future provider-managed external infrastructure | Cloudflare dashboard/operator | One environment-specific Terraform root, but only after resource-by-resource handoff. |
| Shared Cloudflare Tunnel public-hostname configuration | Cloudflare dashboard/operator | Manual initially; possible later Terraform ownership must atomically cover the complete shared ingress configuration. |
| Post-boot packages, users, files, `sysctl` settings, time synchronization, and systemd services | Existing scripts and operator procedures, responsibility by responsibility | Ansible may adopt one exact responsibility at a time; never both writers. |
| k3s host configuration and maintenance | Existing bootstrap/Just/operator workflows | Preserved during the pilot; any later Ansible handoff is a separate decision. |
| Application images and charts | Application repositories and their publishing workflows | Unchanged. |
| Helm releases and Kubernetes resources | Existing Helm/Just workflow | Unchanged; never Terraform or Ansible. |
| Flux-owned resources, where applicable | Flux and its Git source | Flux remains the sole reconciler. |
| Blackbox probes and observability manifests | Existing observability manifests and Helm/Just or Flux workflow, as currently assigned | Unchanged; follow the [observability design](../observability-design.md) and [blackbox runbook](../observability-blackbox.md). |
| Secrets, including Kubernetes and application secrets | Existing out-of-band operator/secret workflows and Kubernetes where applicable | Never intentionally placed in Terraform state or Ansible inventory/logs. |
| Just recipes and CI | Repository maintainers and existing workflows | They remain orchestration and verification surfaces, not Terraform/Ansible resources. |
| Any dashboard-managed resource awaiting migration | Dashboard/operator | Manual is its explicit owner until handoff completes. |

The same hostname may appear in DNS, remotely managed Tunnel ingress, Helm Ingress, and blackbox
probes. That repetition is a **cross-layer contract**, not permission for several tools to manage the
same underlying resource. Verification must resolve DNS to the intended edge/tunnel target, confirm
the complete Tunnel ingress selects the hostname and intended origin, confirm the Kubernetes Ingress
and service route the same host, exercise TLS and the declared public paths, and confirm the expected
blackbox target is discovered and healthy. Each layer still has only its table-assigned writer.

### Handoff protocol

1. Inventory the individual resource and name its current writer.
2. Capture its exact configuration, dependencies, and cross-layer consumers without exposing secrets.
3. Import or adopt it in staging.
4. Require an exact zero-change Terraform plan or zero-change Ansible check, where applicable.
5. Verify behavior through the current runbook and cross-layer contract.
6. Retire the previous writer and document that retirement.
7. Only then authorize the new writer to mutate the resource.

Failure at any step leaves or restores the previous writer; it does not produce shared ownership.

## 5. Conceptual repository layout

No part of this layout is created by this design:

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

Staging and production use separate Terraform roots and separate state, so a staging command cannot
implicitly select production. Shared modules should be extracted only after a genuinely repeated
pattern exists, rather than designed speculatively. Inventories contain only non-secret host
metadata. The first implementation PR may finalize the exact layout.

## 6. Terraform state, authentication, and safety

- Use remote state independent of the k3s cluster, with encryption, locking, version history or
  backups, and narrowly scoped access controls.
- Keep staging and production in separate roots and remote state. State locking prohibits concurrent
  applies.
- Supply least-privilege provider credentials at runtime through environment variables or workload
  identity. Do not commit backend credentials or API tokens.
- Treat state and saved plans as sensitive. Never commit state, plan files, `.terraform/`, backend
  credentials, API tokens, secret-bearing input variables, or secret-bearing outputs.
- Terraform's `sensitive` marking only redacts some display; it **does not prevent the value from
  entering state**. Tunnel connector tokens, k3s tokens, Kubernetes Secrets, and application
  credentials must never intentionally enter Terraform state.
- Credential-free CI may run formatting, `terraform init -backend=false`, validation, and tests. It
  must not run authenticated plans or applies during the pilot.
- Provider lock files belong in a later implementation PR, not this documentation task.

Plans must identify the root, environment, state identity, provider version, and reviewed change.
Operators must stop on unexplained drift rather than normalizing it with an apply.

## 7. Ansible inventory, authentication, and safety

The repository currently identifies `sugarkube3`, `sugarkube4`, and `sugarkube5` as staging nodes in
its observability and ingress-availability documentation. The initial staging inventory may contain
those names only after reachability and environment identity are revalidated at implementation time.

- Use the operator's SSH agent/configuration, strict host-key checking, Tailscale connectivity where
  applicable, and privilege-escalation credentials supplied only at runtime. The
  [Tailscale remote-operations design](tailscale-remote-ops.md) remains the access-plane reference.
- Commit no SSH private keys, authentication secrets, tokens, or secret variables. `no_log` reduces output; it is
  not a secret-storage mechanism.
- Prefer native idempotent modules to arbitrary shell commands.
- Begin with fact gathering and read-only preflight checks before any mutation.
- Require `--check --diff`, explicit inventory limits, serial/canary execution, and readiness/quorum
  checks around disruptive work. Use `serial: 1` when only one cluster node may change at once.
- After an authorized convergence, require a second run to report `changed=0`.
- Do not initially take over Pi imaging, `just ha3`, `/etc/rancher/k3s/config.yaml`, application
  deployment, or existing scripts.
- Migrate one exact file, service, or package responsibility at a time, then retire its previous
  writer before expanding scope.

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
dynamic inventory to Ansible. A failure stops the flow at that layer; it does not authorize a lower
layer to repair or assume ownership of the failed resource.

## 9. GitShelves pilot after PR #2662

The pilot is conditional on the open onboarding PR merging. Once it merges, GitShelves remains
deployed exclusively through the generic app/Helm contract it introduces; Terraform and Ansible do
not reproduce that lifecycle.

### Phases

- **A — Design:** merge only this documentation. Perform no infrastructure action.
- **B — Scaffolding:** add credential-free Terraform and Ansible scaffolding in separate,
  independently reviewed implementation PRs.
- **C — Disposable Terraform lifecycle:** manage a disposable Cloudflare TXT record such as
  `tf-lab.gitshelves.com` through plan, reviewed manual apply, DNS verification, deliberate drift,
  reviewed reconciliation, and destroy. Destroy is allowed here because the resource is explicitly
  disposable.
- **D — Staging DNS adoption:** inventory `staging.gitshelves.com`. Import/adopt its existing record
  and require an exact zero-change plan before Terraform becomes authoritative; create it only if
  inspection proves it does not exist. Confirm that no dashboard operator, other Terraform state, or
  ExternalDNS controller also owns it. Keep the shared Tunnel hostname route manual.
- **E — Host preflight:** run Ansible facts and read-only checks against staging nodes for
  architecture, reachability, time synchronization, disk capacity, service state, and k3s readiness.
- **F — One baseline responsibility:** adopt one low-risk, reversible responsibility with serial
  execution, health gates, and rollback. Require the second convergence run to report `changed=0`.
- **G — Application deployment:** deploy GitShelves only through the existing generic Helm/Just
  workflow. Follow the merged runbook and existing [deployment contract](../app_deployment_contract.md)
  to verify the public route, TLS, `/`, `/healthz`, `/livez`, required STL downloads, rollout state,
  and blackbox coverage.

Remotely managed Cloudflare Tunnel ingress is represented as the full configuration for a shared
tunnel. Terraform must not adopt only the GitShelves route while other routes remain independently
owned. Any later Tunnel adoption must inventory and atomically import the **complete staging ingress
configuration** into one root/state, with a zero-change plan and coordinated retirement of dashboard
ownership. See the current [Cloudflare Tunnel runbook](../cloudflare_tunnel.md) for connector and
public-hostname behavior.

The production hostname, production artifact pin, production Cloudflare resources, and every
production deployment action stay blocked pending a separate reviewed promotion. GitShelves
browser-local data must never enter Terraform state, Ansible inventory, Kubernetes storage, or
backups. This forward-looking design intentionally fixes no image tag, chart version, or probe count
while PR #2662 is changing the application and observability matrix.

## 10. Existing-application operational roadmap

Every row requires staging-first inventory/import, a zero-change adoption plan, explicit retirement
of the old writer, public verification, and reversible rollback before production consideration.

| Application | Terraform opportunities | Ansible opportunities | Preserved existing authority | Verification | Rollback |
| --- | --- | --- | --- | --- | --- |
| [DSPACE](../apps/dspace.md) | Later adopt selected external DNS and edge configuration. | Later reproduce the host-local synthetic runner, its systemd unit/timer, and dependencies, one responsibility at a time, following the [synthetic producer runbook](../dspace-chat-synthetic-producer.md). | Preserve manifest approval, finalized release evidence, Helm revision flow, provider identity, metrics-Secret contracts, and all release/rollback gates. | Retain artifact/digest and runtime identity checks, public/direct health, the bounded `/chat` journey, rollout, metrics, and blackbox checks. | Revert external configuration through its writer; preserve the guarded finalized-evidence Helm rollback flow rather than inventing a shortcut. |
| [token.place](../apps/tokenplace.md) | Later adopt selected external DNS and edge configuration. | Initially only the common cluster-node baseline and controlled node maintenance. | Helm remains authoritative for relay, Valkey, and all other Kubernetes resources. Registration, end-to-end encryption material, runtime credentials, and connector secrets stay outside Terraform state and Ansible variables/logs. | Preserve public health/CORS checks, real compute-node registration and end-to-end encrypted request/response evidence, rollout, metrics, and blackbox checks. | Revert provider configuration through its owner and retain the documented Helm revision rollback and post-rollback verification. |
| [danielsmith.io](../apps/danielsmith.md) | Later adopt DNS, redirects, and applicable edge policy. | Supply consistent shared-node prerequisites only. | Helm owns the application, metrics sidecar/configuration, and existing runtime-data contracts. Do not invent credentials for components that currently require none. | Preserve public paths, TLS, rollout/image identity, runtime cache/metrics behavior, and blackbox verification. | Revert edge configuration through its owner and use the documented prior immutable tag/Helm lifecycle with runtime verification. |
| [jobbot3000](../apps/jobbot3000.md) | Adopt only real, verified staging DNS/edge resources; never turn a placeholder `.example.test` production hostname into Terraform state. | Supply the common node baseline only. | Preserve the generic Helm lifecycle. Browser IndexedDB and private job data stay outside Terraform, Ansible, Kubernetes storage, and backups. | Preserve TLS and public `/`, `/healthz`, and `/livez` checks, rollout/image status, and blackbox coverage. | Revert real edge configuration through its owner and redeploy the previous known-good immutable tag using the documented generic lifecycle. |

These are opportunities, not transfers of ownership. An application may remain manually managed at
the edge indefinitely without blocking improvements to the shared node baseline.

## 11. Drift, failures, rollback, and emergency changes

- Review and explain drift before applying; do not use an apply to erase unexplained evidence.
- Never hand-edit Terraform state during normal operations. Locking must reject concurrent applies.
- `destroy` is valid for the disposable lab, not the default rollback for adopted resources.
  Real-resource rollback normally reverts reviewed configuration and applies that reversion.
- Ansible uses check/diff, handlers, canaries or `serial: 1`, and pre/post cluster readiness checks.
  Stop when readiness or quorum fails; do not continue to the next host.
- Record emergency manual changes promptly and then either codify them in the authoritative writer or
  revert them. Break-glass action does not silently establish a second permanent owner.
- Existing Helm rollback, artifact evidence, public verification, rollout checks, and app-specific
  procedures remain intact.

Restoring a Terraform state version is an exceptional recovery action requiring backend-specific
review, not a substitute for configuration rollback. Similarly, Ansible rollback must be designed for
the adopted responsibility (for example, restore the captured file and restart only through its
handler), tested in staging, and independently invocable.

## 12. Alternatives and decisions

### Rejected alternatives

- **Terraform-only management:** inappropriate for post-boot convergence and would encourage
  provisioners or Kubernetes ownership.
- **Ansible-only management:** lacks the provider-resource state, plan, import, and drift model needed
  for external infrastructure.
- **Terraform-managed Kubernetes objects or Helm releases:** duplicates current Helm/Just or Flux
  authority.
- **Ansible-managed provider resources:** creates a competing external-resource writer.
- **Terraform invoking Ansible:** couples state evaluation to host mutation and breaks independent
  failure and rollback boundaries.
- **One command that automatically mutates every layer during the pilot:** removes review gates and
  expands blast radius.
- **Big-bang migration of scripts and image tooling:** risks working bootstrap and recovery paths.

### Follow-up decisions

- Select the remote-state backend and document its encryption, locking, backup, and recovery model.
- Select the exact first Ansible-managed baseline responsibility.
- Decide how non-secret inventory is privately distributed when public host metadata is insufficient.
- Define the complete Cloudflare Tunnel configuration import/adoption shape.
- Decide whether and how existing k3s host configuration should eventually migrate.
- Define production approval, separation-of-duty, and evidence requirements.

Each decision belongs in a separately reviewed implementation or operations proposal; none is implied
by the conceptual layout.

## 13. Success criteria

### Acceptance for this documentation task

This task succeeds when:

- one authoritative writer per resource is explicit and current versus proposed behavior is clear;
- GitShelves is represented as onboarding in progress according to PR #2662's open status;
- Terraform, Ansible, Helm/Just, Flux, image/bootstrap tooling, and manual boundaries are explicit;
- state, credentials, secrets, shared-Tunnel adoption, drift, handoff, and rollback hazards are covered;
- every requested application has a concrete, non-disruptive roadmap; and
- the diff contains documentation only and neither implements nor authorizes infrastructure mutation.

### Success for a future pilot

The later pilot succeeds only when:

- the disposable Terraform lifecycle and deliberate drift exercise complete safely;
- imported staging DNS produces an exact zero-change plan before adoption;
- Terraform produces a no-op plan after convergence;
- Ansible check mode succeeds across all staging nodes and a second convergence reports `changed=0`;
- GitShelves deploys through the unchanged generic Helm workflow and passes public, health, artifact,
  rollout, and observability verification;
- no secret or state enters Git, logs, or CI artifacts;
- no production or existing-application behavior changes during the pilot; and
- every later application adoption is isolated, verified, and reversible.

Passing the documentation criteria does not imply that any future-pilot criterion has run. Pilot
evidence must cite the reviewed plan/check output and the existing application and
[observability](../observability-design.md) procedures without committing sensitive artifacts.
