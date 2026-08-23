# Disposable Cloudflare TXT-record lab

> [!CAUTION]
> This page is a runbook for a **future, separately authorized operator session**. Checking in the
> configuration is not authorization to authenticate, inspect live DNS, initialize HCP Terraform,
> or run a live Terraform plan, apply, destroy, import, refresh, or state command. None of those
> actions is part of repository preparation.

This root manages exactly one training resource: `cloudflare_dns_record.tf_lab`, a non-proxied TXT
record at `tf-lab.gitshelves.com`. Its explicit 300-second TTL is inside the Cloudflare provider
5.23.0 supported range of 60–86,400 seconds and limits stale training data without selecting the
provider's automatic-TTL value. Destruction is intentional, so the resource has no
`prevent_destroy` rule.

## State decision and boundaries

The pilot uses [HCP Terraform](https://developer.hashicorp.com/terraform/cloud-docs) for remote state
and a workspace configured for **local execution**. HCP Terraform documents
[workspace state storage and history](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/state),
[user tokens for local-execution state access](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/run/run-environment#user-token),
[user API tokens and expiration](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/api-tokens),
[user token creation and revocation](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/users#tokens),
[workspace access controls](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/permissions),
and [state locking](https://developer.hashicorp.com/terraform/language/state/locking). Local execution
means Terraform operations run on the operator's machine rather than HCP Terraform's execution
environment, as described in the
[workspace settings documentation](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings).
This keeps state outside the k3s recovery domain while keeping reviewed commands local. It also
avoids bootstrapping another cloud storage service for one training record. HCP Terraform remains an
external dependency; replacing it requires a separate, reviewed state migration.

The empty `cloud {}` block deliberately commits no organization or workspace. At runtime, the
[CLI cloud settings](https://developer.hashicorp.com/terraform/cli/cloud/settings) support selecting
them with `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE`. Credential-free CI disables backend
initialization and can only format, validate, and run mocked tests; it cannot plan or apply.
Production will require a different root and workspace, neither of which exists here.

This lab does **not** grant ownership of `staging.gitshelves.com`,
`_acme-challenge.staging.gitshelves.com`, the `gitshelves.com` apex, any existing application
hostname, the shared Cloudflare Tunnel, DNSSEC/DS settings, certificates, or Kubernetes resources.
Never adapt the commands below to touch them.

## Repository preparation (safe now)

These credential-free checks mock the provider and disable backend initialization:

```bash
unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io
unset TF_CLOUD_ORGANIZATION TF_WORKSPACE
unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
terraform -chdir=infra/terraform/cloudflare/staging init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform/cloudflare/staging validate -no-color
terraform -chdir=infra/terraform/cloudflare/staging test -no-color
```

The dependency lock supports GitHub Actions on Linux AMD64 and the `sugarkube3` operator host on
Linux ARM64. Regenerate it from the origin registry with the pinned Terraform version and both
platforms, then review and commit the result:

```bash
terraform -chdir=infra/terraform/cloudflare/staging providers lock \
  -platform=linux_amd64 \
  -platform=linux_arm64 \
  registry.terraform.io/cloudflare/cloudflare
```

Stop here during repository work. Everything below is future live work.

## Prerequisites for a separately authorized live session

An operator must manually create or verify:

- an HCP Terraform organization and the workspace `sugarkube-cloudflare-staging-lab`;
- workspace execution mode **Local**, auto-apply disabled, and access restricted to the authorized
  operators;
- a short-duration HCP Terraform **user API token** that authenticates the individual authorized
  operator. The associated user must have only the workspace permissions required to read and write
  state versions, perform the intended local CLI operations, and lock and unlock the workspace when
  this runbook requires it. Select the shortest practical expiration HCP Terraform supports for
  this exercise and revoke the token immediately afterward;
- environment-only delivery of that user token through the hidden `TF_TOKEN_app_terraform_io`
  variable. For this disposable flow, do not create or modify `credentials.tfrc.json`, and never put
  the token in command arguments, shell history, logs, plans, state, evidence, or Git;
- a separate least-privilege Cloudflare API token with only **Zone Read** and **DNS Edit** for the
  `gitshelves.com` zone—never reuse the Cloudflare Tunnel connector token; and
- `jq`, `dig`, Terraform 1.15.9, and the reviewed merge commit on the operator machine.

The Cloudflare zone ID is an identifier rather than a credential, but it remains an uncommitted
runtime operator input. The TXT value must be non-secret and start with
`sugarkube-terraform-lab:`. Treat state and saved plans as sensitive anyway: a plan may contain
provider and input data. Never retain state copies, plan JSON, environment dumps, credentials, or
tokens as evidence.

## Authorized create and verification

Begin only with recorded authorization. Disable shell tracing before handling credentials, create a
mode-`0700` plan directory, and arrange unconditional cleanup. Supply values without printing them:

```bash
set -Eeuo pipefail
set +x
umask 077
PLAN_DIR="$(mktemp -d)"
chmod 0700 "$PLAN_DIR"
cleanup() {
  rm -rf -- "$PLAN_DIR"
  unset CLOUDFLARE_API_TOKEN TF_TOKEN_app_terraform_io
  unset TF_CLOUD_ORGANIZATION TF_WORKSPACE
  unset TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
}
trap cleanup EXIT HUP INT TERM

read -r -p 'HCP Terraform organization: ' TF_CLOUD_ORGANIZATION
TF_WORKSPACE=sugarkube-cloudflare-staging-lab
read -r -s -p 'HCP Terraform user API token (input hidden): ' TF_TOKEN_app_terraform_io; printf '\n'
read -r -s -p 'Cloudflare API credential: ' CLOUDFLARE_API_TOKEN; printf '\n'
read -r -s -p 'Cloudflare zone ID: ' TF_VAR_cloudflare_zone_id; printf '\n'
read -r -p 'Non-secret lab TXT content (prefix required): ' TF_VAR_tf_lab_txt_content
export TF_CLOUD_ORGANIZATION TF_WORKSPACE TF_TOKEN_app_terraform_io
export CLOUDFLARE_API_TOKEN TF_VAR_cloudflare_zone_id TF_VAR_tf_lab_txt_content
```

Before Terraform initialization, define fail-closed DNS helpers. They classify the exact owner as
`absent`, `present`, or `occupied`; valid `NXDOMAIN` and `NOERROR`/NODATA responses are absence, but
unexpected values, mixed answers, and other record types are occupied. Query failures and malformed
responses are errors rather than absence. The SOA negative cache lifetime is the smaller of its TTL
and MINIMUM fields; it bounds later public-resolver waits.

```bash
DNS_NAME=tf-lab.gitshelves.com
DNS_ZONE=gitshelves.com
escaped_txt="${TF_VAR_tf_lab_txt_content//\\/\\\\}"
escaped_txt="${escaped_txt//\"/\\\"}"
EXPECTED_TXT="\"$escaped_txt\""
ns_response="$(dig +time=5 +tries=1 +short NS "$DNS_ZONE")" || {
  echo 'Authoritative nameserver discovery failed' >&2; exit 1;
}
mapfile -t AUTHORITATIVE_NS < <(printf '%s\n' "$ns_response" | sed '/^$/d; s/\.$//')
test "${#AUTHORITATIVE_NS[@]}" -gt 0 || { echo 'No authoritative nameservers found' >&2; exit 1; }

dns_txt() {
  resolver="$1" require_authoritative="${2:-false}"
  DNS_STATE= DNS_ANSWER=
  response="$(dig +time=5 +tries=1 +noall +comments +answer TXT "$DNS_NAME" "@$resolver")" || {
    echo "DNS query to $resolver failed" >&2; return 1;
  }
  header="$(printf '%s\n' "$response" | awk '/^;; ->>HEADER<<-/ { print; exit }')"
  test -n "$header" || { echo "Malformed DNS header from $resolver" >&2; return 1; }
  status="$(printf '%s\n' "$header" | sed -n 's/.*status: \([A-Z]*\),.*/\1/p')"
  case "$status" in
    NOERROR|NXDOMAIN) ;;
    *) echo "DNS query to $resolver returned ${status:-a malformed status}" >&2; return 1 ;;
  esac
  if test "$require_authoritative" = true; then
    printf '%s\n' "$response" | grep -Eq 'flags: [^;]*aa([ ;])' || {
      echo "DNS response from $resolver was not authoritative" >&2; return 1;
    }
  fi
  answers="$(printf '%s\n' "$response" | awk '!/^;/ && NF { print }')"
  if test "$status" = NXDOMAIN; then
    test -z "$answers" || { echo "NXDOMAIN response from $resolver had answers" >&2; return 1; }
    DNS_STATE=absent
    return 0
  fi
  if test -z "$answers"; then
    DNS_STATE=absent
    return 0
  fi
  answer_count="$(printf '%s\n' "$answers" | awk 'END { print NR }')"
  txt_count="$(printf '%s\n' "$answers" | awk '$1 == "'"$DNS_NAME"'." && $4 == "TXT" { count++ } END { print count+0 }')"
  DNS_ANSWER="$(printf '%s\n' "$answers" | awk '$1 == "'"$DNS_NAME"'." && $4 == "TXT" { print substr($0, index($0, $5)) }')"
  if test "$answer_count" -eq 1 && test "$txt_count" -eq 1 && test "$DNS_ANSWER" = "$EXPECTED_TXT"; then
    DNS_STATE=present
  else
    DNS_STATE=occupied
  fi
}

soa="$(dig +time=5 +tries=1 +noall +comments +answer SOA "$DNS_ZONE" "@${AUTHORITATIVE_NS[0]}")" || {
  echo 'Authoritative SOA query failed' >&2; exit 1;
}
printf '%s\n' "$soa" | grep -q 'status: NOERROR' &&
  printf '%s\n' "$soa" | grep -Eq 'flags: [^;]*aa([ ;])' || {
    echo 'SOA response was not authoritative NOERROR' >&2; exit 1;
  }
soa_fields="$(printf '%s\n' "$soa" | awk '$1 == "'"$DNS_ZONE"'." && $4 == "SOA" { count++; ttl=$2; minimum=$NF } END { if (count == 1) print ttl, minimum }')"
read -r soa_ttl soa_minimum <<<"$soa_fields"
test "${soa_ttl:-}" -ge 0 2>/dev/null && test "${soa_minimum:-}" -ge 0 2>/dev/null || {
  echo 'Malformed or absent authoritative SOA response' >&2; exit 1;
}
NEGATIVE_TTL=$((soa_ttl < soa_minimum ? soa_ttl : soa_minimum))
for ns in "${AUTHORITATIVE_NS[@]}"; do
  dns_txt "$ns" true || exit 1
  test "$DNS_STATE" = absent || { echo "DNS name is $DNS_STATE at $ns" >&2; exit 1; }
done
for resolver in 1.1.1.1 8.8.8.8; do
  dns_txt "$resolver" || exit 1
  test "$DNS_STATE" = absent || { echo "DNS name is $DNS_STATE through $resolver" >&2; exit 1; }
done
```

Confirm in the registrar dashboard that the transfer lock remains
enabled. The transfer lock prevents unauthorized registrar transfer; it does not prevent normal DNS
management and is not a reason to disable it. Also inspect the exact name manually in Cloudflare's
dashboard so the operator can identify any existing record or controller before Terraform can act.

**Stop** if the name exists in either DNS inspection or the Cloudflare dashboard; if another
controller claims it; if the HCP workspace has any unexpected managed resource or run; or if its
organization, execution mode, auto-apply setting, or access differs from the prerequisites.

Only after those gates pass, initialize the HCP-backed root and save a proposed plan privately:

```bash
terraform -chdir=infra/terraform/cloudflare/staging init -input=false -lockfile=readonly
CREATE_PLAN="$PLAN_DIR/create.tfplan"
CREATE_JSON="$PLAN_DIR/create.json"
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -out="$CREATE_PLAN"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$CREATE_PLAN" >"$CREATE_JSON"
jq -e '.resource_changes | map({address, actions: .change.actions})' "$CREATE_JSON"
test "$(jq '[.resource_changes[] | select(.address == "cloudflare_dns_record.tf_lab" and .change.actions == ["create"])] | length' "$CREATE_JSON")" -eq 1
test "$(jq '.resource_changes | length' "$CREATE_JSON")" -eq 1
```

Both tests must pass, and human review must confirm exactly one creation at
`cloudflare_dns_record.tf_lab`, with the intended name, type, TTL, non-proxied setting, comment, and
non-secret content. Any update, delete, replacement, other address, or unexpected state blocks the
run. Apply only the reviewed saved plan—never regenerate it implicitly:

```bash
terraform -chdir=infra/terraform/cloudflare/staging apply -input=false "$CREATE_PLAN"
for ns in "${AUTHORITATIVE_NS[@]}"; do
  dns_txt "$ns" true || exit 1
  test "$DNS_STATE" = present || { echo "DNS name is $DNS_STATE at $ns" >&2; exit 1; }
done
wait_for_txt_presence() {
  resolver="$1" deadline=$((SECONDS + NEGATIVE_TTL + 30))
  while test "$SECONDS" -lt "$deadline"; do
    dns_txt "$resolver" || return 1
    case "$DNS_STATE" in
      present) return 0 ;;
      absent) sleep 10 ;;
      *) echo "DNS name is $DNS_STATE through $resolver" >&2; return 1 ;;
    esac
  done
  echo "TXT absent through $resolver after the negative-cache window" >&2; return 1
}
wait_for_txt_presence 1.1.1.1
wait_for_txt_presence 8.8.8.8
if terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -detailed-exitcode; then
  :
else
  status=$?; echo "No-op plan failed with exit code $status" >&2; exit "$status"
fi
```

Require the expected TXT response from Cloudflare and Google's independent public resolver. A
detailed plan exit code other than `0` fails the no-op gate.

## Controlled drift and reconciliation drill

This is a documented **break-glass drill**, not shared ownership. In the Cloudflare dashboard,
change only the content of `tf-lab.gitshelves.com` to another non-secret lab-prefixed value. Do not
touch any other field or resource. Record who authorized the drill and its time in sanitized notes.

```bash
RECONCILE_PLAN="$PLAN_DIR/reconcile.tfplan"
RECONCILE_JSON="$PLAN_DIR/reconcile.json"
terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -out="$RECONCILE_PLAN"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$RECONCILE_PLAN" >"$RECONCILE_JSON"
jq -e --arg content "$TF_VAR_tf_lab_txt_content" --arg zone "$TF_VAR_cloudflare_zone_id" '
  .resource_changes | length == 1 and
  .[0].address == "cloudflare_dns_record.tf_lab" and
  .[0].change.actions == ["update"] and
  .[0].change.before.content != .[0].change.after.content and
  .[0].change.after.content == $content and
  .[0].change.before.zone_id == $zone and .[0].change.after.zone_id == $zone and
  (.[0].change as $change | ["name", "type", "ttl", "proxied", "comment"] |
    all(. as $key | $change.before[$key] == $change.after[$key]))
' "$RECONCILE_JSON" >/dev/null
```

Human review must also show that the sole in-place update restores only the configured TXT content.
Stop on replacement or any other change. Then apply only that reviewed plan and require no changes:

```bash
terraform -chdir=infra/terraform/cloudflare/staging apply -input=false "$RECONCILE_PLAN"
if terraform -chdir=infra/terraform/cloudflare/staging plan -input=false -detailed-exitcode; then
  :
else
  status=$?; echo "No-op plan failed with exit code $status" >&2; exit "$status"
fi
```

## Reviewed destroy and cleanup

Create a saved destroy plan; do not use an unsaved automatic destroy:

```bash
DESTROY_PLAN="$PLAN_DIR/destroy.tfplan"
DESTROY_JSON="$PLAN_DIR/destroy.json"
terraform -chdir=infra/terraform/cloudflare/staging plan -destroy -input=false -out="$DESTROY_PLAN"
terraform -chdir=infra/terraform/cloudflare/staging show -json "$DESTROY_PLAN" >"$DESTROY_JSON"
jq -e '.resource_changes | map({address, actions: .change.actions})' "$DESTROY_JSON"
test "$(jq '[.resource_changes[] | select(.address == "cloudflare_dns_record.tf_lab" and .change.actions == ["delete"])] | length' "$DESTROY_JSON")" -eq 1
test "$(jq '.resource_changes | length' "$DESTROY_JSON")" -eq 1
```

Stop unless review proves exactly one deletion and no other action. Apply only the reviewed plan,
verify absence through two public resolvers and Cloudflare, and inspect HCP Terraform to confirm the
current state contains zero managed resources while its prior state versions remain available:

```bash
terraform -chdir=infra/terraform/cloudflare/staging apply -input=false "$DESTROY_PLAN"
for ns in "${AUTHORITATIVE_NS[@]}"; do
  dns_txt "$ns" true || exit 1
  test "$DNS_STATE" = absent || { echo "DNS name is $DNS_STATE at $ns" >&2; exit 1; }
done
wait_for_txt_absence() {
  resolver="$1"
  deadline=$((SECONDS + 330)) # Poll through the 300-second positive TTL plus grace.

  while test "$SECONDS" -lt "$deadline"; do
    dns_txt "$resolver" || return 1
    case "$DNS_STATE" in
      absent) return 0 ;;
      present) sleep 10 ;;
      *) echo "DNS name is $DNS_STATE through $resolver" >&2; return 1 ;;
    esac
  done

  echo "TXT record remained visible through $resolver after the TTL window" >&2
  return 1
}
wait_for_txt_absence 1.1.1.1
wait_for_txt_absence 8.8.8.8
terraform -chdir=infra/terraform/cloudflare/staging show -json |
  jq -e '([.values.root_module.resources[]?] | length) == 0'
```

Finally, use HCP Terraform's workspace controls to lock or otherwise freeze the workspace against
further runs until the next separately authorized phase. Let the trap erase the private plan
directory and unset the local `TF_TOKEN_app_terraform_io` environment variable with the other
runtime values; explicitly run `cleanup` before leaving the shell if desired. Unsetting the variable
does **not** revoke the user token. Separately, immediately revoke the user token through the
authorized operator's HCP Terraform account settings, and confirm that revocation before closing the
exercise. Save only a sanitized summary of authorization, reviewed action counts, resolver outcomes,
no-op results, drift/reconciliation, destruction, empty current state, workspace freeze, and token
revocation. Never save tokens, state, saved plans, plan JSON, environment dumps, complete TXT values,
or credential files.
