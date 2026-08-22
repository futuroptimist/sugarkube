# Disposable Cloudflare TXT-record lab

> [!IMPORTANT]
> This repository preparation is **not authorization for live execution**. Do not run the live
> lifecycle below until this change is merged and an operator gives separate, explicit authorization.
> No live HCP Terraform or Cloudflare command was run while preparing this root.

This root describes exactly one disposable resource: `cloudflare_dns_record.tf_lab`, a non-proxied
TXT record at `tf-lab.gitshelves.com`. Its content is a non-secret operator input beginning with
`sugarkube-terraform-lab:`. The explicit 300-second TTL is within Cloudflare provider 5.23.0's
documented 60–86400 second range and limits negative caching during this short-lived exercise without
using provider-selected automatic TTL.

The lab is independent of GitShelves deployment, Kubernetes, certificates, DNS-01 challenges, and
the shared Cloudflare Tunnel. There is intentionally no `prevent_destroy`: reviewed destruction is
the final lab exercise.

## State decision and repository-only validation

The pilot uses [HCP Terraform CLI integration](https://developer.hashicorp.com/terraform/cli/cloud/settings)
with a workspace configured for **local execution mode**. HCP Terraform stores the workspace state,
while local mode runs Terraform on the operator workstation and disables remote execution. HCP
Terraform documents separate current and historical
[state versions](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/state), workspace
[locking and team access](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings),
and local-mode state access through CLI integration. This keeps state outside the k3s failure domain,
adds locking, history, and access control, and keeps reviewed commands local. It also avoids creating
another cloud storage service for one training resource. HCP Terraform remains an external dependency;
reconsidering it requires a separate, reviewed state migration.

The empty `cloud {}` block intentionally commits no organization or workspace. At authorized runtime,
use the officially supported `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE` environment variables. CI
initializes with `-backend=false`, has no service credentials, and runs only formatting, validation,
and mocked tests. Production will require a separate root and workspace; neither exists here.

Credential-free repository checks are safe before authorization:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

## Future live prerequisites

Only after merge and separate authorization, an operator must:

- manually create an HCP Terraform organization and workspace named
  `sugarkube-cloudflare-staging-lab`;
- set that workspace's execution mode explicitly to **Local**, disable auto-apply, restrict workspace
  and state access to the operators who need it, and confirm it contains no managed resources;
- authenticate using the standard `terraform login`/Terraform runtime credential mechanism, never a
  committed token or credentials file;
- create a distinct least-privilege Cloudflare API token with only **Zone Read** and **DNS Edit** for
  `gitshelves.com`; never reuse the Cloudflare Tunnel connector token;
- obtain the zone ID separately and supply it only at runtime. It is an identifier rather than a
  credential, but it remains an uncommitted operator input; and
- treat state and saved plans as sensitive, even though the TXT value itself must be non-secret.

The workspace's auto-apply switch does not approve CLI runs: HashiCorp documents that CLI runs use
the CLI approval flag independently. Therefore the procedure below also omits `-auto-approve` and
applies only a previously reviewed saved plan.

## Authorized live lifecycle (future only)

> [!CAUTION]
> Fail closed. These commands are narrowly limited to `tf-lab.gitshelves.com`. Never adapt or copy
> them to touch `staging.gitshelves.com`, `_acme-challenge.staging.gitshelves.com`, the zone apex
> `gitshelves.com`, any existing application hostname, shared Cloudflare Tunnel configuration,
> DNSSEC, or DS settings. Stop if the record already exists, another controller owns it, the HCP
> workspace has unexpected resources, or any plan differs from the exact action required below.

### 1. Establish a private runtime

Confirm in the registrar dashboard that the domain transfer lock remains enabled. The lock prevents
unauthorized registrar transfer and is irrelevant to ordinary authoritative DNS management; do not
disable it. Inspect Cloudflare and authoritative/public DNS manually, using the Cloudflare dashboard
and at least two resolvers, and stop unless `tf-lab.gitshelves.com` is absent everywhere. Confirm no
other operator, automation, or Terraform state owns that name.

Then start a fresh shell, disable tracing **before** credentials, and create a mode-`0700` temporary
directory whose contents are always removed:

```bash
set +x
umask 077
LAB_TMP="$(mktemp -d)"
chmod 0700 "$LAB_TMP"
cleanup() {
  unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io TF_CLOUD_ORGANIZATION TF_WORKSPACE
  unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
  rm -rf -- "$LAB_TMP"
}
trap cleanup EXIT HUP INT TERM

export TF_CLOUD_ORGANIZATION='REPLACE_AT_RUNTIME'
export TF_WORKSPACE='sugarkube-cloudflare-staging-lab'
read -rsp 'Cloudflare credential (input hidden): ' CLOUDFLARE_API_TOKEN; echo
export CLOUDFLARE_API_TOKEN
read -rp 'Cloudflare zone ID: ' TF_VAR_cloudflare_zone_id
export TF_VAR_cloudflare_zone_id
read -rp 'Non-secret lab suffix: ' LAB_SUFFIX
export TF_VAR_tf_lab_txt_content="sugarkube-terraform-lab:${LAB_SUFFIX}"
unset LAB_SUFFIX
```

Do not echo, log, or preserve environment variables. Authenticate to HCP Terraform with the standard
`terraform login` mechanism before this shell if needed. Confirm the selected workspace is Local,
auto-apply is disabled, access is restricted, and its state contains zero managed resources. Stop on
any discrepancy.

### 2. Create and verify

Initialize the HCP-connected root, save the creation plan only in the private directory, and convert
it to ephemeral JSON for machine inspection:

```bash
terraform -chdir=infra/terraform/cloudflare/staging init -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -out="$LAB_TMP/create.tfplan"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$LAB_TMP/create.tfplan" >"$LAB_TMP/create.json"
jq -e '
  [.resource_changes[] | select(.change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "cloudflare_dns_record.tf_lab"
  and $changes[0].type == "cloudflare_dns_record"
  and $changes[0].change.actions == ["create"]
' "$LAB_TMP/create.json"
```

Read the human-readable saved plan too. Stop unless `jq` succeeds and it shows exactly one creation,
at `cloudflare_dns_record.tf_lab`, with no update, delete, or replacement. Apply only that artifact:

```bash
terraform -chdir=infra/terraform/cloudflare/staging apply "$LAB_TMP/create.tfplan"
dig +short TXT tf-lab.gitshelves.com @1.1.1.1
dig +short TXT tf-lab.gitshelves.com @8.8.8.8
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -detailed-exitcode
test "$?" -eq 0
```

Require the expected TXT response from both Cloudflare and Google (or substitute another independent
public resolver for Google), and require the no-op plan's detailed exit code to be exactly `0`.

### 3. Controlled drift and reconciliation

Record authorization for a controlled break-glass drill. In the Cloudflare dashboard, modify **only**
this lab record's TXT content. This deliberately demonstrates emergency dashboard access; it is not
shared ownership and dashboard writing must stop after the drill.

```bash
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -out="$LAB_TMP/reconcile.tfplan"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$LAB_TMP/reconcile.tfplan" >"$LAB_TMP/reconcile.json"
jq -e '
  [.resource_changes[] | select(.change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "cloudflare_dns_record.tf_lab"
  and $changes[0].change.actions == ["update"]
  and $changes[0].change.before.content != $changes[0].change.after.content
' "$LAB_TMP/reconcile.json"
terraform -chdir=infra/terraform/cloudflare/staging apply "$LAB_TMP/reconcile.tfplan"
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -detailed-exitcode
test "$?" -eq 0
```

Before applying, inspect the human-readable plan and require exactly one in-place content update that
restores the configured value—no replacement and no other field or resource change. Require the
second no-op plan to return `0`.

### 4. Destroy, prove absence, and freeze

Create and inspect a saved destroy plan. Stop unless it contains exactly one delete of the lab record:

```bash
terraform -chdir=infra/terraform/cloudflare/staging plan -destroy -input=false -out="$LAB_TMP/destroy.tfplan"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$LAB_TMP/destroy.tfplan" >"$LAB_TMP/destroy.json"
jq -e '
  [.resource_changes[] | select(.change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "cloudflare_dns_record.tf_lab"
  and $changes[0].change.actions == ["delete"]
' "$LAB_TMP/destroy.json"
terraform -chdir=infra/terraform/cloudflare/staging apply "$LAB_TMP/destroy.tfplan"
test -z "$(dig +short TXT tf-lab.gitshelves.com @1.1.1.1)"
test -z "$(dig +short TXT tf-lab.gitshelves.com @8.8.8.8)"
```

Inspect Cloudflare as well and require absence. In HCP Terraform, confirm the current state contains
zero managed resources while historical state versions remain available. Lock the workspace to block
further runs until the next authorized phase (or apply an equivalently reviewed freeze control).

Exit the shell so the trap unsets runtime inputs and deletes every saved plan and JSON file. Save only
a sanitized evidence summary containing approvals, expected action counts, resolver results, and
timestamps. Never retain tokens, state, plan files, plan JSON, environment dumps, credentials files,
zone or record identifiers, or the complete TXT value.
