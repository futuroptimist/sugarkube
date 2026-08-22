# Terraform integration

Terraform owns only explicitly handed-off external provider resources. Ansible owns selected
post-boot host configuration, while Helm, Just, and Flux retain application and Kubernetes ownership.
Every individual resource has one authoritative writer.

## Milestone status

- **Phase B validation foundation — complete.** The pinned Terraform CLI, locked Cloudflare provider,
  backend-disabled initialization, validation CI, and credential-free conventions are in place.
- **Phase C repository support — implemented.** The staging root defines one disposable,
  mock-tested `tf-lab.gitshelves.com` TXT record and a guarded
  [future operator runbook](cloudflare/staging/README.md).
- **Phase C live lifecycle — unexecuted and unauthorized.** No live command may run until this change
  merges and receives separate operator authorization.
- **Phase D staging adoption — not started.** `staging.gitshelves.com` remains outside Terraform.

The staging root uses Terraform `1.15.9` and Cloudflare provider `5.23.0`. Production will eventually
use a distinct root and state workspace; no production root exists.

## State and execution

The Phase C pilot selects HCP Terraform remote state with workspace local execution mode. The empty
`cloud {}` block keeps its organization and workspace out of the repository; authorized operators
will supply `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE` at runtime. The recommended workspace is
`sugarkube-cloudflare-staging-lab`, configured manually for local execution, disabled auto-apply, and
restricted access. See the runbook for the official HashiCorp references and decision rationale.

CI remains credential-free. It initializes with `-backend=false`, validates configuration, and uses a
mocked provider for `terraform test`; it cannot contact HCP Terraform or Cloudflare or mutate state.

## Credential-free validation

Run from the repository root with all external credentials absent:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

The tests use synthetic values and a mocked Cloudflare provider. They exercise only Terraform's
internal test plan operation and make no provider or backend calls.

## Authentication and sensitive artifacts

A future authorized run supplies a dedicated least-privilege Cloudflare token through
`CLOUDFLARE_API_TOKEN`; never commit or print it. Do not reuse a Tunnel connector token. The zone ID
and prefixed, non-secret TXT content are also uncommitted runtime variables.

State and saved plans can contain sensitive values even when outputs are marked sensitive. Never
commit state, backups, plans, plan JSON, `.terraform/`, crash logs, credentials, real `.tfvars`, zone
identifiers, or secret-bearing outputs. The committed lock file fixes the selected provider build and
checksums. Provider or Terraform upgrades require a separate reviewed change; this phase preserves
the existing pins.
