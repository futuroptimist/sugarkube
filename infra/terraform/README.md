# Terraform validation and disposable DNS lab

This directory contains the completed credential-free Terraform half of Phase B and the repository
support for Phase C in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Terraform may eventually own selected external provider resources. Ansible is intended for
post-boot host configuration, while Helm, Just, and Flux retain their existing application and
Kubernetes ownership. Every individual resource has exactly one authoritative writer; a resource
remains manual or dashboard owned until a separately reviewed handoff retires that writer.

## Current scope and phase status

Phase B is complete: the foundation provides an exact Terraform CLI pin, a bounded provider pin, a
dependency lock file, and credential-free validation CI. Phase C repository support adds exactly one
mock-tested, disposable Cloudflare TXT-record contract and its
[guarded operator runbook](cloudflare/staging/README.md). The Phase C live lifecycle has not run and
is unauthorized until this change merges and receives separate operator approval. Phase D adoption
of `staging.gitshelves.com` has not started.

The root has no data lookups, imports, modules, provisioners, command execution, account or zone
identifiers, credentials, or live operations. Its empty HCP Terraform cloud configuration accepts
organization and workspace only at runtime. Production configuration and all infrastructure
mutations remain future work.

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

Staging and production will be separate roots with separate state; Terraform workspaces must not
blur that boundary. No production root exists yet.

## Local validation

Run these commands from the repository root. They confirm the pinned version, check formatting,
install only provider dependencies with backend initialization disabled, validate configuration,
and run the mocked provider tests:

```bash
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

Use Terraform `1.15.9`, as recorded in `.terraform-version`. The initialization command downloads the
locked provider but does not contact Cloudflare. Validation and Terraform-native tests need no
credentials because the tests mock the Cloudflare provider. CI runs only formatting,
backend-disabled initialization, validation, and mocked tests; it receives no Cloudflare or HCP
Terraform credentials or repository secrets and never runs live operations.

## Authentication and sensitive artifacts

Future, separately authorized operator-run Cloudflare work must use a least-privilege API token
supplied at runtime through the provider's documented `CLOUDFLARE_API_TOKEN` environment variable.
Do not add a Terraform token variable, write credentials to a file, or show a token value in docs,
shell history, logs, configuration, plans, or state.

Terraform state and saved plans can contain sensitive values even when normal output marks them
sensitive. The pilot's reviewed remote-state choice is HCP Terraform with local execution mode,
selected at runtime as documented in the [lab runbook](cloudflare/staging/README.md). Treat every
saved plan as a sensitive, short-lived operator artifact. Never commit state, state backups, saved
plans, `.terraform/` caches, crash logs, override files, real `.tfvars` or auto-loaded variable files,
credentials, or secret-bearing outputs. Never run live operations as part of credential-free
validation.

The committed `.terraform.lock.hcl` records the exact provider build and checksums so local and CI
initialization resolve the same dependency. To update it, first change the bounded constraint in
`versions.tf`, then use the pinned CLI to run an explicitly reviewed backend-disabled upgrade in the
staging root. Review the lock-file diff and rerun all validation commands before committing. Do not
delete the lock file to force an update.

## Live Phase C remains blocked

The checked-in `tf-lab.gitshelves.com` contract and runbook do not authorize their live lifecycle.
That lifecycle may begin only after merge and separate explicit authorization. The shared Cloudflare
Tunnel configuration remains outside the lab and must never be partially adopted: any future Tunnel
handoff must inventory and atomically adopt its complete shared configuration with its previous
writer retired.
