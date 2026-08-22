# Terraform Validation Foundation

This directory starts Phase B of the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
It provides one reproducible, credential-free Cloudflare staging root for formatting,
initialization, and static validation. It does not manage or inspect infrastructure.

## Ownership boundaries

Terraform may eventually own selected stateful resources exposed by external provider
APIs. Ansible may eventually own explicitly handed-off post-boot host configuration.
Helm, Just, and Flux retain their existing application and Kubernetes responsibilities.
None of those future ownership changes is implemented here.

Every individual resource has exactly one authoritative writer. A dashboard-managed
resource remains dashboard-managed until a separately reviewed handoff inventories it,
proves a zero-change adoption, verifies behavior, and retires the former writer. Merely
describing a resource in Terraform does not transfer ownership.

The current scaffold deliberately contains:

- an exact Terraform CLI version pin;
- a bounded official Cloudflare provider requirement and generated dependency lock;
- an empty Cloudflare provider configuration that relies only on its documented runtime
  environment variable; and
- no resources, data lookups, imports, outputs, modules, backend, provisioners, or
  command execution.

## Layout and environment isolation

```text
infra/terraform/
  .terraform-version
  README.md
  cloudflare/
    staging/
      versions.tf
      providers.tf
      .terraform.lock.hcl
```

`cloudflare/staging` is an independent Terraform root. A future production root must be
added only by a separate review and must use separate configuration and state. Staging
and production must not share state or use workspaces to obscure their boundary.

## Safe local validation

From the repository root, install the version recorded in `.terraform-version` with
your preferred version manager, then run exactly:

```bash
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
```

Initialization downloads only the declared provider and updates the local `.terraform/`
cache. `-backend=false` is mandatory because no state backend has been selected. These
commands require no Cloudflare credential and perform no provider API operation.

CI runs only these formatting, backend-disabled initialization, and validation checks.
It receives no Cloudflare credentials or repository secrets and never applies changes.
This makes pull-request validation useful without granting CI infrastructure authority.

## Authentication and sensitive artifacts

For future, explicitly authorized operator-run work, the Cloudflare provider reads a
least-privilege API token at runtime from the `CLOUDFLARE_API_TOKEN` environment
variable. Do not add a token input variable or place a token in configuration, command
history, examples, or files. No credential is needed for the validation workflow above.

Terraform state and saved plans can contain resource attributes and secrets even when
values are marked sensitive. Treat them as sensitive artifacts with restricted access
and retention. Never commit `.terraform/`, state or state backups, saved plans, crash
logs, override files, real `.tfvars`, auto-loaded variable files, credentials, or secret
values. The repository's scoped ignore rules are a safety net, not permission to create
these files here.

The `.terraform.lock.hcl` file is intentionally committed. It records the selected
provider version and package checksums so local and CI initialization resolve the same
dependency. To update it, first review and change the bounded provider constraint, use
the repository-pinned Terraform CLI to run `terraform init -backend=false -upgrade` in
the staging root, inspect the lock-file diff, and rerun all validation checks. Provider
and CLI upgrades require their own review.

Do not run `terraform plan`, `apply`, `destroy`, `import`, or any authenticated provider
operation as part of this foundation. Do not add backend configuration, resources,
data sources, modules, provisioners, shell commands, real identifiers, or credentials.

## Next milestone

The next planned Terraform milestone is a separately reviewed, disposable
`tf-lab.gitshelves.com` TXT-record lifecycle. It can proceed only after explicit
authorization, backend and state handling are reviewed, credentials are supplied safely
to an operator, and the design's review and verification gates are met.

The shared Cloudflare Tunnel configuration is not part of that DNS lab. It is one shared
configuration and must never be partially adopted route by route; any future adoption
must inventory and transfer the complete configuration atomically in a separate review.
