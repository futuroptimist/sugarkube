# Terraform validation and disposable lab

This directory implements the Terraform side of the phased
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Terraform may own selected external provider resources only after an explicit handoff. Helm, Just,
Flux, Ansible, and existing operator procedures retain their current responsibilities, and every
individual resource has exactly one authoritative writer.

## Milestone status

- **Phase B — complete:** the credential-free validation foundation pins Terraform 1.15.9 and
  Cloudflare provider 5.23.0, locks provider checksums, and validates without credentials or a backend.
- **Phase C repository support — implemented:** the staging root declares one disposable,
  mock-tested TXT-record contract and includes a guarded [operator runbook](cloudflare/staging/README.md).
- **Phase C live lifecycle — unexecuted and unauthorized:** no HCP Terraform or Cloudflare login,
  initialization, live plan, creation, drift exercise, reconciliation, or destruction is authorized
  until this work merges and receives separate operator approval.
- **Phase D — not started:** the existing `staging.gitshelves.com` record remains outside Terraform.

```text
infra/terraform/
├── .terraform-version
├── README.md
└── cloudflare/
    └── staging/
        ├── .terraform.lock.hcl
        ├── README.md
        ├── main.tf
        ├── outputs.tf
        ├── providers.tf
        ├── tests/
        │   └── tf_lab.tftest.hcl
        ├── variables.tf
        └── versions.tf
```

Staging and production use separate roots and state, never workspaces that blur the environment
boundary. No production root or workspace exists.

## Credential-free validation

Run from the repository root with external credentials absent:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

The native tests mock the Cloudflare provider. CI has read-only repository permissions, receives no
repository secrets, disables backend initialization, and never performs a live plan or mutation.

## State, authentication, and sensitive artifacts

Phase C selects HCP Terraform with local execution mode for pilot state. Organization and workspace
selection remain runtime-only through `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE`; the recommended
workspace is `sugarkube-cloudflare-staging-lab`. The root commits only an empty `cloud {}` block.
The [lab runbook](cloudflare/staging/README.md) documents the official basis, prerequisites, and
fail-closed future lifecycle.

Never commit state, state backups, saved plans, `.terraform/` caches, crash logs, override files,
real variable files, credentials, identifiers, or secret-bearing outputs. State and saved plans can
contain sensitive data even when output is marked sensitive. The lock file pins provider 5.23.0 and
its checksums; update it only through a separately reviewed provider upgrade using the pinned CLI.

The shared Cloudflare Tunnel configuration is outside this lab. It must never be partially adopted:
any future Tunnel handoff must inventory and atomically adopt its complete shared configuration and
retire its previous writer.
