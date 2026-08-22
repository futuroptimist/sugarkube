# Terraform foundation

This directory is the credential-free, validation-only Terraform half of Phase B
in the [Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Terraform may eventually own selected external provider resources. Ansible may
eventually own explicitly handed-off host configuration. Helm/Just and Flux keep
their existing application and Kubernetes ownership. None of those future changes
is implemented here.

## Ownership and scope

Every resource has exactly one authoritative writer. A dashboard-managed resource,
for example, stays dashboard/operator-owned until a separately reviewed handoff
inventories it, proves a zero-change adoption, and retires the previous writer.
Adding a provider declaration does not transfer ownership.

This scaffold implements only:

- an exactly pinned Terraform CLI version;
- a bounded official Cloudflare provider requirement and committed dependency lock;
- an empty Cloudflare staging root; and
- credential-free formatting, backend-disabled initialization, and validation.

It deliberately contains no resources, data lookups, imports, outputs, modules,
provisioners, backend selection, account or zone identifiers, application DNS,
Ansible scaffold, or infrastructure mutation.

## Layout and environment isolation

```text
infra/terraform/
  .terraform-version
  README.md
  cloudflare/
    staging/
      .terraform.lock.hcl
      providers.tf
      versions.tf
```

`cloudflare/staging` is an independent Terraform root. A future production root
must be introduced separately and must use separate state; staging and production
must not share state or use workspaces to obscure the boundary.

## Local validation

Install the version named in `.terraform-version` with your Terraform version
manager, then run these commands from the repository root:

```bash
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
```

Initialization downloads the locked provider into an ignored `.terraform/`
directory. `-backend=false` ensures validation does not select or contact a state
backend. Validation requires no Cloudflare credential because this root has no
resource or data operation.

CI runs exactly this formatting, initialization, and validation boundary. It is
read-only, receives no repository secrets or Cloudflare credentials, and never
applies infrastructure. Keeping CI credential-free makes validation safe for pull
requests and prevents source review from becoming mutation authorization.

## Authentication, state, and plans

Future operator-authorized Cloudflare work must use the provider's documented
environment-based authentication, such as the `CLOUDFLARE_API_TOKEN` environment
variable, with a least-privilege token supplied only at runtime. Do not declare a
Terraform token variable, put credentials in configuration or files, or commit an
account or zone identifier. CI must remain credential-free.

Terraform state and saved plans can contain identifiers, configuration, and secret
values even when terminal output marks a value sensitive. Treat both as sensitive
artifacts with restricted access and retention. This scaffold intentionally makes
no remote-state backend choice.

Never commit `.terraform/`, state or state backups, saved plan files, crash logs,
override files, real `.tfvars`, auto-loaded variable files, credentials, or secrets.
The scoped repository ignore rules are a safety net, not permission to create such
files here.

Do not run `plan`, `apply`, `destroy`, or `import` for this scaffold. Do not add
resources, data sources, a backend, command execution, or credentials without a
separately reviewed and explicitly authorized milestone.

## Dependency lock updates

`.terraform.lock.hcl` records the selected provider version and package checksums
so local validation and CI install the same dependency. Commit it. To update it,
separately review a bounded constraint change, use the repository-pinned Terraform
version, and run:

```bash
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -upgrade
```

Inspect the lock-file diff and repeat every validation command above. A lock update
does not authorize any provider operation.

## Next milestone

The next planned Terraform milestone is a separately reviewed, disposable
`tf-lab.gitshelves.com` TXT-record lifecycle. It may proceed only after explicit
authorization and with operator-reviewed lifecycle commands; this scaffold does
not create that record or authorize live DNS changes.

The shared Cloudflare Tunnel configuration is not part of that DNS lab. It must
not be partially adopted: any future handoff must inventory and atomically adopt
the complete shared configuration, with its prior writer retired.
