# Pi Support Bundles

`scripts/pi_support_bundle.py` captures Kubernetes events, Helm releases, Compose logs, and
`systemd` journals from remote Pi nodes so every CI run and incident report ships with the same
context. Bundles land in timestamped folders under `~/sugarkube/support-bundles/` (or a custom
path) and the script archives each run as `<timestamp>-<host>.tar.gz` for quick attachment to issue
threads.

## Collecting bundles manually

```bash
./scripts/pi_support_bundle.py pi-a.local \
  --identity ~/.ssh/pi-support \
  --ssh-option StrictHostKeyChecking=no \
  --ssh-option UserKnownHostsFile=/dev/null
```

The command above gathers:

- `kubectl get events --all-namespaces -o yaml` plus pod, node, and service summaries.
- `helm list --all-namespaces --output yaml` so pinned release versions travel with the bundle.
- `docker compose` logs from `/opt/projects` alongside `journalctl -u projects-compose.service`.
- `systemd-analyze blame`/`critical-chain` output for boot timing analysis.
- `journalctl` slices for `k3s`, cloud-init phases, and the self-heal units.
- `/boot/first-boot-report` (when present) packaged as `boot/first-boot-report.tar.gz`.

Additional flags:

- `--since "6 hours ago"` narrows journal slices when you only need the latest boot.
- `--skip-first-boot-report` speeds up captures when the boot partition is not mounted.
- `--strict` flips the exit code to non-zero if **any** remote command fails.
- Pass multiple hosts (`pi-a.local pi-b.local`) to build one archive per node in a single run.

Prefer wrappers? Use the new task runner hooks:

```bash
SUPPORT_BUNDLE_ARGS="pi-a.local --identity ~/.ssh/pi-support" make support-bundle
# or
SUPPORT_BUNDLE_ARGS="pi-a.local --identity ~/.ssh/pi-support" just support-bundle
```

Both targets pass arguments verbatim to `scripts/pi_support_bundle.py` so you can reuse saved shell
snippets without editing the Makefile.

## CI integration

The release pipeline now uploads a `sugarkube-support-bundle` artifact whenever the following secrets
are configured:

- `SUPPORT_BUNDLE_HOSTS` – space- or newline-separated hostnames/IPs reachable from the runner.
- `SUPPORT_BUNDLE_SSH_KEY` – private key used for the SSH connection.
- `SUPPORT_BUNDLE_SSH_USER` (optional) – overrides the default `pi` user.

Each run writes the key to `support-bundle.key`, invokes the collector with the hardened SSH options,
and publishes the resulting archives as workflow artifacts. Missing secrets simply skip the step, so
existing builds continue to succeed without additional setup.

Set the secrets, verify connectivity with a manual run, then inspect the `sugarkube-support-bundle`
artifact on subsequent `pi-image-release` builds to confirm the captured logs match expectations.
