# Terraform integration

This directory implements the Terraform portion of the
[Terraform and Ansible integration design](../../docs/design/terraform-ansible-integration.md).
Terraform may own selected external provider resources only after an explicit handoff. Ansible is for
post-boot host configuration, while Helm, Just, and Flux retain their application and Kubernetes
ownership. Every resource has exactly one authoritative writer.

## Milestone status

- **Phase B — validation foundation: complete.** Terraform `1.15.9`, Cloudflare provider `5.23.0`, the
  dependency lock, credential-free validation, and read-only CI are present.
- **Phase C — disposable lab repository support: implemented.** The staging root defines and
  mock-tests the single `tf-lab.gitshelves.com` TXT record and includes its
  [guarded operator runbook](cloudflare/staging/README.md).
- **Phase C — live lifecycle: unexecuted and unauthorized.** No HCP Terraform or Cloudflare login,
  live plan, apply, drift exercise, or destroy is authorized until this repository work merges and a
  separate operator approval is granted.
- **Phase D — adoption of `staging.gitshelves.com`: not started.** Existing DNS and application
  ownership remain unchanged.

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

Staging and production use separate roots and state, not Terraform workspaces that blur the
environment boundary. No production root or workspace exists.

## Credential-free validation

Run from the repository root with Terraform `1.15.9`:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io
unset TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform version
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init \
  -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

Backend-disabled initialization installs only the locked provider. Validation and `terraform test`
need no external credentials; the native tests mock the Cloudflare provider. CI runs only these
formatting, initialization, validation, and mocked-test checks with read-only repository permission.
It cannot perform a live operation.

## State, authentication, and sensitive artifacts

Phase C selects HCP Terraform remote state with local workspace execution for this pilot. Runtime
`TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE` values select the organization and the recommended
`sugarkube-cloudflare-staging-lab` workspace; neither is committed. This keeps state independent of
k3s and gives the pilot remotely stored state, locking, version history, and access controls while
reviewed commands execute on the authorized operator machine. It also avoids bootstrapping another
storage service for one training record. HCP Terraform is an external dependency and may be replaced
only through a separately reviewed state migration. Details and official HashiCorp references are in
the [operator runbook](cloudflare/staging/README.md#state-decision-and-boundaries).

Cloudflare authentication uses the provider's documented `CLOUDFLARE_API_TOKEN` environment variable
only during a later authorized operation. Never add token variables or expose credentials in files,
shell history, logs, configuration, plans, or state. State and saved plans can contain sensitive data
even when outputs are marked sensitive.

Never commit state, backups, saved plans, `.terraform/`, crash logs, overrides, `.tfvars`, credentials,
or secret-bearing outputs. The lock file fixes provider builds and checksums. Any future provider
update must change the reviewed constraint deliberately, use backend-disabled initialization with
`-upgrade`, review the lock diff, and rerun all checks; do not delete the lock file to force an update.

The lab is independent of GitShelves deployment, ACME challenges, Kubernetes, and the shared
Cloudflare Tunnel. Tunnel configuration must never be partially adopted; a future handoff would need
to inventory and atomically adopt the complete shared configuration while retiring its former writer.
