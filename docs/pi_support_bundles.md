---
personas:
  - hardware
  - software
---

# Pi Support Bundles

Gather a point-in-time snapshot of a running Sugarkube Pi when debugging first boot,
projects-compose, or cluster regressions. The `collect_support_bundle.py` helper connects over
SSH, executes a curated set of Kubernetes, systemd, and Docker Compose commands, and writes
everything to a compressed archive so the artifacts can be attached to GitHub issues or stored
alongside CI runs.

The bundle captures the commands highlighted in the Pi Image UX & Automation checklist:

- `kubectl get events --all-namespaces --sort-by=.lastTimestamp -o wide`
- `helm list -A`
- `systemd-analyze blame` and `systemd-analyze critical-chain`
- `docker compose logs` and `docker compose ps` for `/opt/projects/docker-compose.yml`
- Journals for `projects-compose.service`, `first-boot.service`, `k3s.service`,
  `sugarkube-self-heal@*`, and the current boot (`journalctl -b`)

Each command writes a Markdown preamble (description, command, exit code) before the captured
output. Failures are noted inline, and `summary.json` records the status of every probe so CI or
humans can detect missing data quickly.

## Collect bundles locally

Run the helper directly when you have SSH access to a Pi. A
`collect_support_bundle.sh` wrapper ships alongside it for runbooks that still
reference the historical shell entrypoint; both commands execute the same
Python implementation:

```bash
./scripts/collect_support_bundle.py pi-a.local \
  --identity ~/.ssh/id_ed25519 \
  --output-dir ~/sugarkube/support-bundles
```

Prefer the unified CLI? Preview the helper with:

```bash
python -m sugarkube_toolkit pi support-bundle --dry-run -- pi-a.local \
  --identity ~/.ssh/id_ed25519 --output-dir ~/sugarkube/support-bundles
```

Drop `--dry-run` to collect artefacts immediately. Arguments after the standalone `--` flow directly to
`scripts/collect_support_bundle.py`, matching the behaviour described above.
Regression coverage in
`tests/test_sugarkube_toolkit_cli.py::test_pi_support_bundle_invokes_helper`
ensures the CLI forwards `--dry-run` to the helper so the preview matches the
documented workflow.

The script stores results under `support-bundles/<host>-<timestamp>/` and also emits a matching
`.tar.gz`. Override `--no-archive` to keep only the raw directory, and `--spec` to append extra
commands (`output/path.txt:command:description`).

Pass `--target` to copy remote files or directories into the bundle. Each path is stored beneath
`targets/` using a sanitized directory name so artefacts like `/boot/first-boot-report/` travel with
the captured command output. Failures are logged to stderr and recorded in `summary.json` under the
`targets` key for quick triage. Automated coverage lives in
`tests/test_collect_support_bundle.py::test_copy_targets_captures_paths`.

Make and Just wrappers mirror the CLI:

```bash
SUPPORT_BUNDLE_HOST=pi-a.local \
SUPPORT_BUNDLE_ARGS="--identity ~/.ssh/id_ed25519" \
  make support-bundle

# or
SUPPORT_BUNDLE_HOST=pi-a.local \
SUPPORT_BUNDLE_ARGS="--identity ~/.ssh/id_ed25519" \
  just support-bundle
```

Set `SUPPORT_BUNDLE_CMD` if you need to point the wrappers at a forked script or containerized entry
point.

## CI integration

The `pi-image-release.yml` workflow now uploads a support bundle after every build when the
following secrets are configured:

- `SUPPORT_BUNDLE_HOST` — hostname or IP address of the validation Pi.
- `SUPPORT_BUNDLE_USER` — SSH username (defaults to `pi` when unset).
- `SUPPORT_BUNDLE_SSH_KEY` — private key contents with access to the host.

During the job the workflow writes the key to `~/.ssh/support-bundle`, runs
`collect_support_bundle.py`, and publishes the resulting archive as an artifact named
`sugarkube-support-bundle`. Missing secrets simply skip the step, preventing release failures on
self-hosted forks while still enabling full telemetry on the canonical pipeline.

Every bundle ships with the JSON summary, raw command transcripts, and the compressed archive so
operators can share just the relevant pieces when reporting regressions.
