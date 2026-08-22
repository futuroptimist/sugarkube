# Disposable Cloudflare TXT-record lab

This root is the repository preparation for Phase C. **Nothing in this document authorizes live
execution.** Do not run the operator sequence until this change has merged and a separate, explicit
authorization names the operator and maintenance window. Repository and CI checks use only the
mocked provider; they do not authenticate, inspect DNS, or mutate an external system.

The one managed object is `cloudflare_dns_record.tf_lab`, a non-proxied TXT record named exactly
`tf-lab.gitshelves.com`. Its content is a non-secret runtime input beginning
`sugarkube-terraform-lab:`. Its explicit 300-second TTL is within Cloudflare provider 5.23.0's
documented 60–86,400 second range and keeps this disposable exercise's DNS cache lifetime bounded.
Destruction is intentional, so the resource has no `prevent_destroy` rule.

## State decision and boundaries

The pilot uses [HCP Terraform](https://developer.hashicorp.com/terraform/cloud-docs) with a workspace
configured for [local execution](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings#execution-mode).
The empty `cloud {}` block deliberately leaves the organization and workspace to the supported
[`TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE` environment variables](https://developer.hashicorp.com/terraform/cli/cloud/settings#environment-variables).
HCP Terraform stores workspace state remotely, provides state locking and state version history, and
allows workspace access to be restricted; local execution keeps Terraform operations on the operator
machine. See HashiCorp's documentation for [state](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/state),
[locking](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings#locking), and
[permissions](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/permissions).

This keeps state independent of k3s and avoids creating another cloud storage service for one
training record. CI has neither the runtime selection nor credentials and can only initialize with
`-backend=false`, validate, and use the mock provider. HCP Terraform remains an external dependency;
a later, separately reviewed state migration may reconsider it. Production requires a separate root
and workspace, neither of which exists here.

## Repository-only validation (authorized now)

These commands are credential-free and do not perform a real plan:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io
unset TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/cloudflare/staging init \
  -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

## Future live prerequisites (not authorized by this change)

Before a later authorized window, an administrator must manually create an HCP Terraform organization
and the `sugarkube-cloudflare-staging-lab` workspace. Restrict workspace access, set its execution mode
to **local**, and disable auto-apply. Authenticate with Terraform's standard login/runtime mechanism;
do not commit its user token, credentials file, organization, project or workspace identifiers, or a
hostname override.

Create a separate least-privilege Cloudflare API token with only **Zone Read** and **DNS Edit** for the
`gitshelves.com` zone. Never reuse the Cloudflare Tunnel connector token. The zone ID is an identifier,
not a credential, but still remains an uncommitted runtime input. Supply all inputs through environment
variables without printing values. Treat state and plans as sensitive, use `set +x` before credentials,
and create saved plans only under a mode-`0700` temporary directory removed by a trap.

## Future authorized lifecycle

> **STOP:** The commands below are a fail-closed template, not current authorization. Never adapt them
> to touch `staging.gitshelves.com`, `_acme-challenge.staging.gitshelves.com`, the zone-apex
> `gitshelves.com` record, an existing application hostname, the shared Cloudflare Tunnel, or DNSSEC/DS
> settings. Stop if the lab name exists, another controller owns it, workspace state is unexpected, or
> any inspected action differs from the exact action stated below.

### 1. Establish the guardrails

Confirm in the registrar dashboard that the transfer lock remains enabled. That lock governs domain
transfer and is irrelevant to ordinary authoritative DNS management; do not disable it. Using both
authoritative/public DNS inspection and the Cloudflare dashboard, confirm that only
`tf-lab.gitshelves.com` is absent and no controller claims it. Do not copy commands from this runbook
to inspect or alter any other hostname.

Confirm the HCP workspace is empty, locally executed, auto-apply is disabled, and access is restricted.
If it contains any managed resource or unexpected state version, stop. Then, with approved values at
hand, begin a clean shell session:

```bash
set -euo pipefail
set +x
umask 077
export TF_CLOUD_ORGANIZATION='REPLACE_WITH_APPROVED_ORGANIZATION'
export TF_WORKSPACE='sugarkube-cloudflare-staging-lab'
export TF_VAR_cloudflare_zone_id='REPLACE_WITH_INSPECTED_ZONE_ID'
export TF_VAR_tf_lab_txt_content='sugarkube-terraform-lab:REPLACE_WITH_APPROVED_NON_SECRET_MARKER'
read -rsp 'Cloudflare credential (input hidden) ' CLOUDFLARE_API_TOKEN; printf '\n'
export CLOUDFLARE_API_TOKEN
PLAN_DIR="$(mktemp -d)"
chmod 0700 "$PLAN_DIR"
cleanup() {
  unset CLOUDFLARE_API_TOKEN TF_CLOUD_ORGANIZATION TF_WORKSPACE
  unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
  rm -rf -- "$PLAN_DIR"
}
trap cleanup EXIT HUP INT TERM
ROOT='infra/terraform/cloudflare/staging'
terraform -chdir="$ROOT" init -input=false -lockfile=readonly
```

The placeholders are deliberate. Replace them only in the shell during an authorized window; never
save the resulting exports, shell history, or environment dump.

### 2. Create exactly one record

Create and inspect a sensitive saved plan:

```bash
terraform -chdir="$ROOT" plan -input=false -out="$PLAN_DIR/create.tfplan"
terraform -chdir="$ROOT" show -json "$PLAN_DIR/create.tfplan" >"$PLAN_DIR/create.json"
jq -e '
  [.resource_changes[] | select(.change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
    and $changes[0].address == "cloudflare_dns_record.tf_lab"
    and $changes[0].change.actions == ["create"]
' "$PLAN_DIR/create.json" >/dev/null
terraform -chdir="$ROOT" show "$PLAN_DIR/create.tfplan"
```

Stop unless `jq` succeeds and human review confirms one TXT creation with the approved name, content,
TTL, comment, and `proxied = false`, with no update, delete, or replacement. Apply only that saved plan:

```bash
terraform -chdir="$ROOT" apply -input=false "$PLAN_DIR/create.tfplan"
```

Verify the exact TXT answer through Cloudflare's `1.1.1.1` and Google's `8.8.8.8` independently, and
compare it to the approved value without recording it:

```bash
test "$(dig +short TXT tf-lab.gitshelves.com @1.1.1.1)" = \
  "\"$TF_VAR_tf_lab_txt_content\""
test "$(dig +short TXT tf-lab.gitshelves.com @8.8.8.8)" = \
  "\"$TF_VAR_tf_lab_txt_content\""
terraform -chdir="$ROOT" plan -input=false -detailed-exitcode
```

The last command must return detailed exit code `0`; `1` is an error and `2` means changes. Stop on
either nonzero result.

### 3. Controlled drift and reconciliation

This is a documented, controlled break-glass drill—not shared ownership or permission for continued
dashboard edits. In the Cloudflare dashboard only, change this lab record's TXT content to a second
approved non-secret value. Touch no other field or resource. Immediately create and inspect the
reconciliation plan:

```bash
terraform -chdir="$ROOT" plan -input=false -out="$PLAN_DIR/reconcile.tfplan"
terraform -chdir="$ROOT" show -json "$PLAN_DIR/reconcile.tfplan" >"$PLAN_DIR/reconcile.json"
jq -e '
  [.resource_changes[] | select(.change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
    and $changes[0].address == "cloudflare_dns_record.tf_lab"
    and $changes[0].change.actions == ["update"]
    and $changes[0].change.before.content != $changes[0].change.after.content
' "$PLAN_DIR/reconcile.json" >/dev/null
terraform -chdir="$ROOT" show "$PLAN_DIR/reconcile.tfplan"
```

Stop unless review proves exactly one in-place content update restoring the configured value, with no
creation, deletion, replacement, or other field change. Apply only the reviewed saved plan, verify the
answer through both resolvers as above, and demand another no-op:

```bash
terraform -chdir="$ROOT" apply -input=false "$PLAN_DIR/reconcile.tfplan"
terraform -chdir="$ROOT" plan -input=false -detailed-exitcode
```

### 4. Destroy only the disposable record

Create a destroy plan, inspect its JSON, and fail closed:

```bash
terraform -chdir="$ROOT" plan -destroy -input=false -out="$PLAN_DIR/destroy.tfplan"
terraform -chdir="$ROOT" show -json "$PLAN_DIR/destroy.tfplan" >"$PLAN_DIR/destroy.json"
jq -e '
  [.resource_changes[] | select(.change.actions != ["no-op"])] as $changes
  | ($changes | length) == 1
    and $changes[0].address == "cloudflare_dns_record.tf_lab"
    and $changes[0].change.actions == ["delete"]
' "$PLAN_DIR/destroy.json" >/dev/null
terraform -chdir="$ROOT" show "$PLAN_DIR/destroy.tfplan"
```

Stop unless the only action is deletion of the lab address. Apply only that saved destroy plan:

```bash
terraform -chdir="$ROOT" apply -input=false "$PLAN_DIR/destroy.tfplan"
```

After the 300-second cache window, require the TXT name to be absent through both public resolvers and
confirm in Cloudflare. In the HCP Terraform UI, confirm the current state contains zero managed
resources while its state-version history remains available. Lock the workspace (or otherwise freeze
it against runs) until a separately authorized phase.

### 5. Cleanup and evidence

Exit the shell or invoke `cleanup`; the trap removes plans and JSON and unsets runtime values. Confirm
the temporary directory is gone. Retain only a sanitized summary containing authorization reference,
timestamps, reviewed action counts, resolver pass/fail results, and workspace freeze confirmation.
Never retain tokens, state, saved plans, plan JSON, complete TXT values, environment dumps, shell
history containing values, or Terraform credential files.
