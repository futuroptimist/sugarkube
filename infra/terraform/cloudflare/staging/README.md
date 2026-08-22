# Disposable Cloudflare TXT-record lab

> **Repository preparation only:** this root and runbook do not authorize a live run. Do not run
> any command in the **Future authorized lifecycle** section until this change has merged and a
> separate operator approval covers that specific lifecycle.

This Phase C root manages exactly one disposable resource,
`cloudflare_dns_record.tf_lab`: an unproxied TXT record named `tf-lab.gitshelves.com`. Its content and
the `gitshelves.com` zone ID are runtime inputs. The explicit 300-second TTL is within the Cloudflare
provider 5.23.0 documented range of 60 through 86,400 seconds and limits stale answers during a
short-lived exercise without relying on the provider's automatic-TTL sentinel. The comment identifies
the record as disposable training infrastructure. There is intentionally no `prevent_destroy`.

Tests mock the Cloudflare provider. Credential-free CI disables backend initialization, validates the
root, and runs only mocked Terraform tests. It cannot perform a live plan or mutation.

## Pilot state decision

The pilot uses HCP Terraform for remotely stored state and workspace locking, with workspace state
versions and workspace access controls, while the workspace uses **local execution mode**. HashiCorp's
[cloud block documentation](https://developer.hashicorp.com/terraform/language/terraform#cloud)
documents `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE` as runtime alternatives to hard-coded cloud
configuration. Its [execution-mode documentation](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings#execution-mode)
states that local mode performs Terraform operations on the operator machine while HCP Terraform
stores and synchronizes state. HashiCorp also documents
[state versions](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/state#state-versions),
[workspace locking](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings#locking),
and [workspace access controls](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings/access).

This keeps state independent of k3s and keeps reviewed commands on the operator machine. CI has no
HCP or Cloudflare credentials and cannot plan or apply. For one training resource, the pilot avoids
bootstrapping another storage service solely for state. HCP Terraform remains an external dependency;
a later change may reconsider it only through a separately reviewed state migration. Production must
use a separate root and separate workspace; neither is created here.

## Repository-only validation

These commands are safe because backend initialization is disabled and the provider is mocked:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

## Future operator prerequisites

Before separate authorization, an operator must manually create an HCP Terraform organization and a
workspace named `sugarkube-cloudflare-staging-lab`, set its execution mode to **local**, disable
auto-apply, and restrict workspace access. Authenticate with the standard Terraform login/runtime
mechanism; do not commit the organization, project or workspace identifiers, hostname overrides,
credentials files, or user tokens.

Create a separate least-privilege Cloudflare API token with only **Zone Read** and **DNS Edit** for
`gitshelves.com`. Never reuse the Cloudflare Tunnel connector token. Supply the API token and both
Terraform variables through the environment without printing their values. Zone IDs are identifiers,
not credentials, but remain uncommitted operator inputs. Treat HCP state and saved plans as sensitive.

## Hard boundary

Every guard below must fail closed. Stop rather than adapting these commands to touch
`staging.gitshelves.com`, `_acme-challenge.staging.gitshelves.com`, the `gitshelves.com` apex, any
existing application hostname, shared Cloudflare Tunnel configuration, or DNSSEC/DS settings. This
lab gives Terraform ownership of the one disposable record only. It grants no shared ownership and
no authority over GitShelves, ACME, Tunnel, registrar, Kubernetes, or production resources.

## Future authorized lifecycle

> **DO NOT RUN DURING REPOSITORY PREPARATION.** The following is a future, attended operator
> procedure, not approval. Replace placeholders only after merge and explicit authorization.

### 1. Prepare and prove absence

Confirm in the registrar dashboard that the domain-transfer lock remains enabled. That lock controls
registration transfer and is irrelevant to ordinary DNS management; never disable it for this lab.
Inspect Cloudflare and query both authoritative/public DNS for `tf-lab.gitshelves.com`. Stop if the
name exists or another controller owns it. (DNS inspection commands are intentionally not run by this
repository change.) Confirm the HCP workspace is empty and stop if it contains unexpected resources.

In a clean shell, disable tracing before handling credentials, create a mode-`0700` directory, and
install a cleanup trap. Read sensitive values silently rather than placing them in shell history:

```bash
set -Eeuo pipefail
set +x
umask 077
PLAN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sugarkube-tf-lab.XXXXXX")"
chmod 0700 "$PLAN_DIR"
cleanup() {
  unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io TF_CLOUD_ORGANIZATION TF_WORKSPACE
  unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
  rm -rf -- "$PLAN_DIR"
}
trap cleanup EXIT HUP INT TERM

export TF_CLOUD_ORGANIZATION='REPLACE_AFTER_AUTHORIZATION'
export TF_WORKSPACE='sugarkube-cloudflare-staging-lab'
read -rsp 'Cloudflare credential (hidden): ' CLOUDFLARE_API_TOKEN; printf '\n'
export CLOUDFLARE_API_TOKEN
read -rsp 'Cloudflare zone ID: ' TF_VAR_cloudflare_zone_id; printf '\n'
export TF_VAR_cloudflare_zone_id
read -rsp 'Disposable TXT content (sugarkube-terraform-lab:...): ' TF_VAR_tf_lab_txt_content; printf '\n'
export TF_VAR_tf_lab_txt_content
```

Authenticate through Terraform's standard login mechanism, then initialize this HCP-backed root.
Before continuing, verify in HCP Terraform that local execution and disabled auto-apply remain set.

```bash
terraform -chdir=infra/terraform/cloudflare/staging init -input=false
```

### 2. Create exactly one record

Create a saved plan only inside the private directory, convert it to sensitive JSON there, and require
exactly one create at the intended address. The `jq -e` gate rejects every update, delete,
replacement, or second resource:

```bash
CREATE_PLAN="$PLAN_DIR/create.tfplan"
CREATE_JSON="$PLAN_DIR/create.json"
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -out="$CREATE_PLAN"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$CREATE_PLAN" >"$CREATE_JSON"
jq -e '
  [.resource_changes[] | {address, actions: .change.actions}] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "cloudflare_dns_record.tf_lab"
  and $changes[0].actions == ["create"]
' "$CREATE_JSON" >/dev/null || { echo 'STOP: create plan is not exactly one creation' >&2; exit 1; }
terraform -chdir=infra/terraform/cloudflare/staging apply -input=false "$CREATE_PLAN"
```

Inspect the human-readable plan as well as JSON before applying. Verify the TXT answer through
Cloudflare's resolver (`1.1.1.1`) and Google's (`8.8.8.8`), and compare it to the configured value
without recording that value in evidence. Stop on disagreement.

Run a no-op plan and require detailed exit code `0` (not `2`):

```bash
set +e
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -detailed-exitcode
NOOP_RC=$?
set -e
test "$NOOP_RC" -eq 0 || { echo "STOP: expected no-op exit 0, got $NOOP_RC" >&2; exit 1; }
```

### 3. Controlled drift and reconciliation

With the exercise recorded in the authorization, use the Cloudflare dashboard to change **only this
record's TXT content** to another non-secret lab-prefixed value. This is a controlled break-glass
drill, not shared ownership: Terraform remains the sole writer and dashboard editing ends after the
drill.

Create and inspect a new saved reconciliation plan. Require one in-place `update` at the lab address;
reject create, delete, replacement, or any additional action. Inspect the before/after JSON and
confirm only `content` returns to the configured value before applying the reviewed saved plan:

```bash
RECONCILE_PLAN="$PLAN_DIR/reconcile.tfplan"
RECONCILE_JSON="$PLAN_DIR/reconcile.json"
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -out="$RECONCILE_PLAN"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$RECONCILE_PLAN" >"$RECONCILE_JSON"
jq -e '
  [.resource_changes[] | {address, actions: .change.actions}] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "cloudflare_dns_record.tf_lab"
  and $changes[0].actions == ["update"]
' "$RECONCILE_JSON" >/dev/null || { echo 'STOP: expected exactly one in-place update' >&2; exit 1; }
jq -e '
  .resource_changes[0].change as $change
  | (($change.before | del(.content)) == ($change.after | del(.content)))
  and ($change.before.content != $change.after.content)
' "$RECONCILE_JSON" >/dev/null || { echo 'STOP: reconciliation changes more than content' >&2; exit 1; }
terraform -chdir=infra/terraform/cloudflare/staging apply -input=false "$RECONCILE_PLAN"
```

Repeat the detailed-exit-code no-op gate from step 2 and require `0`.

### 4. Destroy exactly the lab record

Create a saved destroy plan; do not use an unsaved automatic destroy. Require exactly one delete at
the lab address and no other action, inspect it, then apply only that saved plan:

```bash
DESTROY_PLAN="$PLAN_DIR/destroy.tfplan"
DESTROY_JSON="$PLAN_DIR/destroy.json"
terraform -chdir=infra/terraform/cloudflare/staging plan -destroy -input=false -out="$DESTROY_PLAN"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$DESTROY_PLAN" >"$DESTROY_JSON"
jq -e '
  [.resource_changes[] | {address, actions: .change.actions}] as $changes
  | ($changes | length) == 1
  and $changes[0].address == "cloudflare_dns_record.tf_lab"
  and $changes[0].actions == ["delete"]
' "$DESTROY_JSON" >/dev/null || { echo 'STOP: destroy plan is not exactly one deletion' >&2; exit 1; }
terraform -chdir=infra/terraform/cloudflare/staging apply -input=false "$DESTROY_PLAN"
```

Verify absence in Cloudflare and through the same two independent public resolvers. Confirm through
HCP Terraform that current state has zero managed resources while the workspace retains its state
version history. Lock the workspace (or apply an organization-approved equivalent freeze) against
further runs until the next authorized phase.

### 5. Clean up and retain only sanitized evidence

Let the trap unset runtime credentials and recursively remove all saved plans and JSON. Explicitly
run `cleanup` before leaving the shell if desired; the EXIT trap also runs it:

```bash
cleanup
trap - EXIT HUP INT TERM
```

Save only a sanitized summary: authorization reference, timestamps, intended resource address,
guard results, resolver pass/fail results, no-op exit codes, drift/reconciliation result, deletion
result, and workspace freeze confirmation. Never retain tokens, credential files, state, plan files,
plan JSON, complete TXT content, environment dumps, zone identifiers, or Terraform login material.
