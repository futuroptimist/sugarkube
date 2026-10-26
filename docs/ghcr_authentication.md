# GHCR authentication and PAT renewal

Use this runbook when an operator's GitHub Container Registry (GHCR) pull credential
is expiring, expired, or returning `401`/`403`. Renewal changes credentials; it does
not require a deployment, restart, or Kubernetes Secret update.

## Identify the consumer before changing credentials

Sugarkube's `just helm-oci-install` and `just helm-oci-upgrade` recipes call Helm.
The DSPACE OCI preflight also uses ORAS. There is currently **no registry login
recipe** in the `justfile`. Use the installed Helm/ORAS clients directly; do not
install Docker for this procedure. A Docker-compatible credential file describes
a format used by several OCI clients, not proof that the Docker CLI is used.
`kubectl` talks to Kubernetes; logging in with Helm does not authenticate node
image pulls.

Make a private checklist of required packages, machines, operating-system users,
clients, and effective credential locations. Record only paths and completion
status, never credential values. Inspect launch commands and overrides before
assuming that a file containing a GHCR entry is an active consumer:

| Consumer | Configuration to resolve |
| --- | --- |
| Helm chart pulls | An explicit `--registry-config` overrides `HELM_REGISTRY_CONFIG`; otherwise Helm derives its config location from its environment. Run `helm env` locally to identify `HELM_REGISTRY_CONFIG`. A usual Linux path is `~/.config/helm/registry/config.json`. |
| ORAS preflight | Check `--registry-config` and `DOCKER_CONFIG`; the usual default is `~/.docker/config.json`. Use `oras login --help` for the installed version. |
| Other OCI clients | Check their explicit config options, service environment, user/home directory, and configured credential helpers. Shared format alone does not guarantee shared lookup behavior. |
| k3s/containerd image pulls | Separately inspect the configured registry file (often `/etc/rancher/k3s/registries.yaml`, or a service override), workload and service-account `imagePullSecrets`, and any external secret-management source. |
| Automation | Check CI secrets, timers, and service accounts independently; updating an interactive user's file does not update them. |

Do not print, decode, paste, or commit credential files, Kubernetes Secret contents,
or raw environment dumps. Inspect only config paths, registry names, and helper
names locally. `credHelpers`/`credsStore` may select an external credential helper;
confirm the helper is installed and accessible before proceeding. A root process
or another user may read a different config. No default registry file or current
`imagePullSecret` references does **not** prove that there are no other consumers.
Any cluster credential change needs its own reviewed procedure and authorization.

## Create the replacement with overlap

For pull-only access, create a **new personal access token (classic)** with only
`read:packages`, using an account allowed to read the required packages. Do not
add `repo`, `write:packages`, or `delete:packages` for this task. Complete any
required organization SSO authorization or policy approval. Public artifacts may
be readable anonymously; a successful public pull alone is not proof that the
replacement PAT has private-package access.

Choose a deliberate expiration date and set a private reminder far enough before
expiry to migrate and verify every consumer. Keep the new value in your approved
password manager. Never send it to an assistant, issue, PR, shell history, profile,
or repository file. The clients may persist encoded credentials in their registry
files; those files are secrets, not encrypted backups.

Creating a separate token lets the old token remain valid during migration.
**Regenerating an existing token replaces its value immediately**, so consumers
using the old value can fail before you update them. Prefer a separate new token
for planned renewal. If the old token is already expired or revoked, there is no
working rollback credential. For a suspected compromise, follow incident response
and revoke promptly instead of preserving overlap.

`gh auth token` returns GitHub CLI's currently selected credential; it does not
select a newly created PAT from the website. Do not reuse that bootstrap command
as a renewal step or change GitHub CLI authentication merely to rotate OCI access.

## Check prerequisites, then enter the token privately

Run locally as the operating-system user that actually pulls the artifacts, in a
trusted interactive terminal with session recording disabled. First check the
installed clients and flags, selected config paths, file ownership/permissions,
and any credential helpers. Resolve missing tools or helper access **before**
entering the token. Use the project's normal tool setup; Docker is not required.
Do not use `sudo` to work around a config owned by a different user.

The Bash example below is for a confirmed Helm **and** ORAS consumer with the
usual Linux paths. Edit the two arrays together to match your inventory; remove
the ORAS pair if it is not used. Explicit paths avoid accidentally logging in to
one file and testing another. If both clients intentionally share one file,
select that same path. Helm can also write a Docker-compatible file via
`helm registry login --registry-config /absolute/path/config.json` without Docker.
Do not point it at an arbitrary file simply because it contains a GHCR entry.

The block checks all selected clients and locations before prompting. Hidden input
is read from the terminal into an unexported shell variable, then sent through
standard input using Bash's built-in `printf`. No token literal belongs in the
block or command arguments. Do not enable shell tracing or debug logging.

```bash
bash <<'BASH'
set +x
set +a
set -euo pipefail
unset HELM_DEBUG
umask 077
clients=(helm oras)
configs=("$HOME/.config/helm/registry/config.json" "$HOME/.docker/config.json")
[[ ${#clients[@]} -eq ${#configs[@]} ]]
for i in "${!clients[@]}"; do
  client=${clients[$i]}
  command -v "$client" >/dev/null || {
    printf 'Missing client: %s; stop before entering a token.\n' "$client" >&2
    exit 1
  }
  case "$client" in
    helm) help_text=$(helm registry login --help) ;;
    oras) help_text=$(oras login --help) ;;
    *) printf 'Unsupported client.\n' >&2; exit 1 ;;
  esac
  [[ "$help_text" == *--password-stdin* && "$help_text" == *--registry-config* ]]
  config=${configs[$i]}
  [[ "$config" == /* ]]
  mkdir -p -- "$(dirname -- "$config")"
  [[ -w "$(dirname -- "$config")" ]]
  if [[ -e "$config" ]]; then
    [[ -f "$config" && -r "$config" && -w "$config" && -O "$config" ]]
  fi
done
read -r -p 'GitHub username owning the replacement PAT: ' ghcr_username </dev/tty
[[ -n "$ghcr_username" ]]
unset ghcr_renewal_pat
trap 'unset ghcr_renewal_pat' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
read -r -s -p 'Replacement PAT (hidden): ' ghcr_renewal_pat </dev/tty
printf '\n' >/dev/tty
[[ -n "$ghcr_renewal_pat" ]]
for i in "${!clients[@]}"; do
  client=${clients[$i]}
  config=${configs[$i]}
  if [[ "$client" == helm ]]; then
    login=(helm registry login ghcr.io)
  else
    login=(oras login ghcr.io)
  fi
  if ! builtin printf '%s' "$ghcr_renewal_pat" |
    "${login[@]}" --username "$ghcr_username" --password-stdin --registry-config "$config"; then
    printf 'Login failed for %s (%s). Earlier writes remain; stop and inspect.\n' \
      "$client" "$config" >&2
    exit 1
  fi
  printf 'Login completed for %s (%s); package verification is still required.\n' \
    "$client" "$config"
done
BASH
```

Restrict existing config files and their directories to the intended account;
`umask` only restricts newly created files. If a helper is configured, review its
access controls too. Do not make unprotected backup copies of credential files.
A successful login is only one step, not proof that all required packages work.

## Verify the packages without deploying

Use each consumer's actual account, environment, and config. Substitute a required
chart and its current pinned version from the app runbook, plus the exact image
reference/digest from the approved release manifest. These are templates, not
commands to run unchanged:

```bash
helm show chart oci://ghcr.io/OWNER/charts/APP --version PINNED_VERSION \
  --registry-config /absolute/path/to/helm/config.json
oras manifest fetch --descriptor ghcr.io/OWNER/IMAGE@sha256:APPROVED_DIGEST \
  --registry-config /absolute/path/to/oras/config.json
```

`helm show chart` verifies chart retrieval without installing it. ORAS manifest
access verifies registry access to the selected image manifest; it does not pull
all image layers or prove that a k3s node can authenticate. Verify private packages
if private access is required. Repeat for all needed charts/images, not just one
public chart. Confirm that the real recipes resolve the same credential files;
do not run deployment recipes merely to test a PAT. Existing running pods and
cached images do not prove that future image pulls will work.

If any login or package check fails, stop and mark that consumer incomplete.
Earlier successful writes are not rolled back. Keep the old token until all
consumers are confirmed migrated, and retry only the affected entries after
checking the account, config selection, helper, package permissions/SSO, and
reference. `401`/`403` can indicate expired or stale credentials or access denial;
a missing version is a different failure. Do not broaden scopes to guess at a fix.
Do not delete the whole registry config or log out every registry as a recovery
step. Re-login to the selected GHCR config preserves unrelated registry entries.

After every required consumer passes its own verification, revoke the old token,
repeat the necessary read-only package checks, and record the next expiry/reminder
without the token value. If consumer coverage remains uncertain, report renewal
as incomplete rather than claiming a public chart pull proves full migration.

## References

- [GitHub Container registry authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub personal access token management](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Helm OCI registries and shared credential format](https://helm.sh/docs/topics/registries/)
- [Helm registry login flags](https://helm.sh/docs/helm/helm_registry_login/)
- [ORAS authentication and config selection](https://oras.land/docs/how_to_guides/authentication/)
- [ORAS login flags](https://oras.land/docs/commands/oras_login/)
