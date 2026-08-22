# Terraform validation foundation

This directory is the credential-free Terraform half of Phase B in the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Terraform is reserved for explicitly adopted external provider resources. Ansible may eventually
configure post-boot hosts. Helm, Just, and Flux retain their existing application and Kubernetes
ownership. None of these tools may share authority over one resource: **every resource has exactly
one authoritative writer**, and its existing writer remains authoritative until a reviewed handoff
is complete.

## Current scope

The scaffold contains one empty Cloudflare staging root. It pins Terraform and the official
Cloudflare provider, records provider checksums in a lock file, and supports formatting,
backend-disabled initialization, and validation without credentials.

It deliberately contains no resources, data lookups, imports, outputs, modules, provisioners,
backend configuration, account or zone identifiers, application DNS, Ansible, or live mutation.
In particular, it neither adopts nor changes GitShelves, Kubernetes, Helm, the registrar, DNS, or
Cloudflare Tunnel configuration.

```text
infra/terraform/
  .terraform-version             # exact Terraform CLI release
  README.md
  cloudflare/
    staging/                     # isolated staging root and future staging state
      .terraform.lock.hcl        # selected provider release and checksums
      providers.tf
      versions.tf
```

A future production root must be added separately and use state isolated from staging. Production
and staging must not be combined with Terraform workspaces. A remote state backend has not been
selected or configured.

## Credential-free validation

Install the release named in `.terraform-version`, then run these commands from the repository root:

```bash
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
```

The CI workflow runs only those formatting, initialization, and validation operations. It receives
no Cloudflare credentials or repository secrets and never plans or applies changes. Initialization
downloads the pinned provider but disables backend initialization; validation only checks the
configuration.

For separately authorized, future operator-run work, the Cloudflare provider expects its documented
`CLOUDFLARE_API_TOKEN` environment variable. Supply a least-privilege token only in the operator's
runtime environment. Do not add a Terraform token variable, token value, credentials file, account
ID, or zone ID to this repository.

## State, plans, and dependency locks

Terraform state and saved plans can contain identifiers and secrets even when output is marked
sensitive. Treat them as sensitive artifacts with restricted access and retention. Never commit
state, state backups, saved plans, `.terraform/`, crash logs, override files, real `.tfvars` files,
auto-loaded variable files, backend credentials, provider credentials, or secret-bearing outputs.
The targeted repository ignore rules provide a backstop, not permission to create those artifacts
here.

The `.terraform.lock.hcl` file is intentionally committed. It records the selected provider version
and package checksums so local and CI initialization agree. To update it, make a dedicated reviewed
dependency change: update the bounded provider constraint, run `terraform init -backend=false
-upgrade` in the staging root, inspect the lock-file diff and upstream release notes, then rerun all
credential-free checks. Do not hand-edit the lock file.

Do not run `terraform plan`, `apply`, `destroy`, or `import` for this scaffold. Do not add a backend
or credentials. CI must remain validation-only and credential-free.

## Next milestone

The next planned Terraform milestone is a separately reviewed lifecycle for one disposable
`tf-lab.gitshelves.com` TXT record. It may proceed only after explicit authorization and must define
review, operator-run mutation, verification, drift, and cleanup controls. This scaffold grants no
such authorization.

The shared Cloudflare Tunnel configuration is **not** part of that DNS lab. A remotely managed
tunnel has shared configuration and must never be partially adopted route by route; any future
adoption requires a complete, atomic, separately reviewed handoff.
