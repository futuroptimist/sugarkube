# Pi Support Bundle Collector

Use the support bundle helper to capture cluster state, service logs, and first-boot reports
whenever a pipeline run or operator session needs additional context. The script works against
both the local host (for CI runners) and remote Raspberry Pis reached over SSH.

## Quick start

Run the helper locally to gather diagnostics from the active shell:

```bash
python3 scripts/collect_support_bundle.py --output support-bundle.tar.gz
```

To collect from a remote node, provide SSH connection details. The command below gathers
Kubernetes events, Helm releases, Compose logs, relevant journal slices, and the most recent
`pi_node_verifier` output. Passing `--include-first-boot-report` also archives the boot hand-off
artifacts from `/boot/first-boot-report`.

```bash
python3 scripts/collect_support_bundle.py \
  --host pi-a.local \
  --user pi \
  --identity ~/.ssh/id_ed25519 \
  --include-first-boot-report \
  --output ~/sugarkube/reports/pi-a-support-bundle.tar.gz
```

Use `just support-bundle` or `make collect-support-bundle` when you prefer task runners:

```bash
SUPPORT_BUNDLE_ARGS="--host pi-a.local --include-first-boot-report" just support-bundle
```

## What lands in the bundle?

Each support bundle is a `.tar.gz` containing timestamped command output alongside metadata that
records exit codes and stderr for every command. The defaults capture:

- `kubectl get events -A --sort-by=.lastTimestamp`
- `kubectl get pods -A -o wide`
- `helm list -A`
- `systemd-analyze blame`
- `docker compose -f /opt/projects/docker-compose.yml ps`
- `docker compose -f /opt/projects/docker-compose.yml logs --tail 400`
- `journalctl -u projects-compose.service --since -6h`
- `journalctl -u k3s.service --since -6h`
- `pi_node_verifier` JSON output (if present)
- Optional `/boot/first-boot-report` archives when `--include-first-boot-report` is provided

Add more snippets with repeated `--extra-command NAME='command'` flags. The helper stores stdout
and stderr for every snippet even when binaries are missing, helping CI runs surface missing tools
without failing the entire bundle.

## Pipeline integration

`pi-image-release.yml` now calls the collector as a post-build step and uploads the resulting
`support-bundle.tar.gz` artifact for **every** release or nightly image build. When CI environment
variables `SUPPORT_BUNDLE_HOST`, `SUPPORT_BUNDLE_USER`, or `SUPPORT_BUNDLE_KEY` are set, the
workflow automatically switches to remote collection. Otherwise it defaults to a local sweep so
maintainers still get build logs, environment metadata, and error placeholders in the artifact.

Store long-running bundles under `~/sugarkube/reports/` when troubleshooting manually so they sit
alongside flash, clone, and verifier reports.
