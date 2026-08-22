# Terraform validation foundation

This directory is the credential-free Terraform half of Phase B in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Terraform may eventually own selected external provider resources. Ansible is intended for
post-boot host configuration, while Helm, Just, and Flux retain their existing application and
Kubernetes ownership. Every individual resource has exactly one authoritative writer; a resource
remains manual or dashboard owned until a separately reviewed handoff retires that writer.

## Current scope

The scaffold provides one empty Cloudflare staging root, an exact Terraform CLI pin, a bounded
provider pin, a dependency lock file, and credential-free validation CI. It deliberately contains no
resources, data lookups, imports, outputs, modules, provisioners, command execution, backend
configuration, account or zone identifiers, credentials, or live operations. Remote-state selection,
production configuration, Ansible scaffolding, and all infrastructure mutations remain future work.

```text
infra/terraform/
├── .terraform-version
├── README.md
└── cloudflare/
    └── staging/
        ├── .terraform.lock.hcl
        ├── providers.tf
        └── versions.tf
```

Staging and production will be separate roots with separate state; Terraform workspaces must not
blur that boundary. No production root exists yet.

## Local validation

Run these commands from the repository root. They confirm the pinned version, check formatting,
install only provider dependencies with backend initialization disabled, and validate configuration:

```bash
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
```

Use Terraform `1.15.9`, as recorded in `.terraform-version`. The initialization command downloads the
locked provider but does not contact Cloudflare. Validation needs no credentials because this root
contains no provider operations. CI runs only these formatting, backend-disabled initialization, and
validation checks; it receives no Cloudflare credentials or repository secrets and never applies.

## Authentication and sensitive artifacts

Future, explicitly authorized operator-run Cloudflare work must use a least-privilege API token
supplied at runtime through the provider's documented `CLOUDFLARE_API_TOKEN` environment variable.
Do not add a Terraform token variable, write credentials to a file, or show a token value in docs,
shell history, logs, configuration, plans, or state.

Terraform state and saved plans can contain sensitive values even when normal output marks them
sensitive. Store future state only in a separately reviewed encrypted, locked, access-controlled
remote backend with version history or backups. Treat every saved plan as a sensitive, short-lived
operator artifact. Never commit state, state backups, saved plans, `.terraform/` caches, crash logs,
override files, real `.tfvars` or auto-loaded variable files, credentials, or secret-bearing outputs.
Never run `plan`, `apply`, `destroy`, or `import` as part of this validation scaffold.

The committed `.terraform.lock.hcl` records the exact provider build and checksums so local and CI
initialization resolve the same dependency. To update it, first change the bounded constraint in
`versions.tf`, then use the pinned CLI to run an explicitly reviewed
`terraform init -backend=false -upgrade` in the staging root. Review the lock-file diff and rerun all
validation commands before committing. Do not delete the lock file to force an update.

## Next milestone

The next planned Terraform milestone is a separately reviewed, disposable
`tf-lab.gitshelves.com` TXT-record lifecycle, and it may begin only after explicit authorization.
That review must define operator credentials, state, ownership, and guarded lifecycle procedures; it
is not authorized by this scaffold. The shared Cloudflare Tunnel configuration is outside that DNS
lab. It must never be partially adopted: any future Tunnel handoff must inventory and atomically
adopt its complete shared configuration with its previous writer retired.
