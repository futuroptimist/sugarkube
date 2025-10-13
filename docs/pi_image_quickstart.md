---
personas:
  - software
---

# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

Need the full narrative? Jump to the [Pi Carrier Launch Playbook](./pi_carrier_launch_playbook.md)
for a 10-minute fast path, persona walkthroughs, and reference maps that connect each automation
helper to its documentation. Return here whenever you need the detailed command-by-command view.

Need a visual overview first? Start with the
[Pi Image Flowcharts](./pi_image_flowcharts.md) to map the journey from download to first boot
before diving into the commands below.

Maintainers updating scripts or docs should cross-reference the
[Pi Image Contributor Guide](./pi_image_contributor_guide.md) to keep automation helpers and
guidance aligned.

Before flashing or booting new hardware, glance at the hardware boot badge in the top-level
[`README`](../README.md). The badge is driven by `docs/status/hardware-boot.json` and signals when the
last manual `pi_smoke_test` run succeeded. Follow the contributor guide's
[Record hardware boot runs](./pi_image_contributor_guide.md#record-hardware-boot-runs) section to
refresh the badge after exercising physical clusters.

Need a hands-on reminder next to the hardware? Print the
[Pi carrier QR labels](./pi_carrier_qr_labels.md) and stick them to the enclosure so anyone can
scan straight to this quickstart or the troubleshooting matrix while standing at the workbench.
Pair them with the [Pi Carrier Field Guide](./pi_carrier_field_guide.md) and its generated
[`pi_carrier_field_guide.pdf`](./pi_carrier_field_guide.pdf) to keep a one-page checklist beside the
cluster.
Run `make field-guide` or `just field-guide` after editing the Markdown to refresh the PDF copy.

## 0. Prepare your workstation (macOS)

Homebrew users can now install a supported tap and run a guided setup wizard:

```bash
brew tap sugarkube/sugarkube https://github.com/futuroptimist/sugarkube
brew install sugarkube
```

The tap ships a `sugarkube-setup` CLI that audits Homebrew formulas (`qemu`, `coreutils`, `just`,
`xz`, and `pipx`), ensures `~/sugarkube/{images,reports,cache}` exist, and writes a starter
`sugarkube.env` with 100% patch coverage reminders. Inspect the plan first:

```bash
just mac-setup
# or
task mac:setup
```

Then apply the changes automatically (or substitute `make mac-setup`):

```bash
just mac-setup MAC_SETUP_ARGS="--apply"
# or
task mac:setup MAC_SETUP_ARGS="--apply"
```

The wizard can also run outside macOS by appending `--force`, which keeps docs and CI rehearsals in
sync without modifying the host.

## 1. Build or download the image

1. Use the one-line installer to bootstrap everything in one step:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/install_sugarkube_image.sh | bash
   ```
   The script installs the GitHub CLI when missing, downloads the latest
   release, verifies the `.img.xz` checksum, expands it to
   `~/sugarkube/images/sugarkube.img`, and records a fresh `.img.sha256` hash.
   Pass `--download-only` to keep just the compressed archive or `--dir` to
   change the destination.
2. When working from a cloned repository, run the same helper locally:
   ```bash
   ./scripts/install_sugarkube_image.sh --dir ~/sugarkube/images --image ~/sugarkube/images/sugarkube.img
   ```
   All flags supported by `download_pi_image.sh` are forwarded, so `--release`
   and `--asset` continue to work. `./scripts/sugarkube-latest` remains
   available if you only need the compressed artifact.
   Prefer the unified CLI? Preview the helper with:
   ```bash
   python -m sugarkube_toolkit pi install --dry-run -- --dir ~/sugarkube/images --image ~/sugarkube/images/sugarkube.img
   ```
   Drop `--dry-run` when you're ready. Everything after the standalone `--`
   flows to `scripts/install_sugarkube_image.sh`, so `--release` and other
   documented flags work unchanged. The CLI forwards `--dry-run` to the
   installer so the helper prints the same plan it would execute, just like
   calling the shell script directly ("Dry-run: would download …",
   "Dry-run: would expand archive …"). Regression coverage in
   `tests/test_sugarkube_toolkit_cli.py::test_pi_install_invokes_helper`,
   `tests/test_sugarkube_toolkit_cli.py::test_pi_install_respects_existing_dry_run`,
   and `tests/install_sugarkube_image_test.py::test_install_dry_run_previews_without_changes`
   (plus neighbouring `test_pi_install_*` cases) ensures the CLI forwards
   arguments exactly as documented and the shell helper's preview mode stays
   aligned with the documentation.
   > [!TIP]
   > Provisioning a full three-node cluster? Copy
   > [`samples/pi-cluster/three-node.toml`](../samples/pi-cluster/three-node.toml), edit the
   > hostnames and devices, then run
   > `python -m sugarkube_toolkit pi cluster --config ./cluster.toml`. The helper chains
   > `install_sugarkube_image.sh`, `flash_pi_media_report.py`, and
   > `pi_multi_node_join_rehearsal.py --apply` so you only swap media when prompted.
3. Want a fresh workflow artifact? You now have two options:
   - **Hands-off:** enable `[image.workflow] trigger = true` in your cluster config (the
     `samples/pi-cluster/three-node.toml` starter already does). The bootstrapper dispatches the
     `pi-image` workflow, polls until the run completes, and downloads the artifact automatically
     before flashing media.
   - **Manual:** open **Actions → pi-image → Run workflow**, tick **token.place** and **dspace** to
     bake those repos into `/opt/projects`, then download `sugarkube.img.xz` once the run succeeds.
     Need a guided path? Launch the [Sugarkube Flash Helper](./flash-helper/) and paste the workflow
     URL to receive OS-specific download, verification, and flashing instructions. Prefer the
     terminal? Run `python scripts/workflow_flash_instructions.py --url <run-url> --os
     linux|mac|windows` from the repository root to print the same steps.
   - `./scripts/download_pi_image.sh --output /your/path.img.xz` still resumes partial downloads and
     verifies checksums automatically.
   - Prefer a unified entry point? Run `python -m sugarkube_toolkit pi download --dry-run` from the
     repository root to preview the helper. When you're in a nested directory, call
     `./scripts/sugarkube pi download --dry-run` so the wrapper bootstraps `PYTHONPATH`. Both
     commands invoke `scripts/download_pi_image.sh --dry-run` with the flags you provide. Pass the
     same arguments (`--dir`, `--release`, `--asset`, etc.) to the CLI and they flow straight to the
     shell script, including the preview mode so you can inspect the exact `curl` commands without
     fetching the artifact. When prerequisites such as the GitHub CLI, `curl`, or `sha256sum` are
     missing, the dry-run prints reminders instead of exiting so you can install them before running
     without `--dry-run`.

> [!NOTE]
> The same repository-root rule applies to other `python -m sugarkube_toolkit ...` examples below.
> Use the `./scripts/sugarkube` wrapper (or add `scripts/` to `PATH`) whenever you're launching
> commands from a nested directory so the CLI can import correctly.
   - Want a hands-off alert when the artifacts land? Run
    ```bash
    make notify-workflow \
      WORKFLOW_NOTIFY_ARGS='--run-url <workflow-url>'
    ```
     to poll the run and raise a desktop notification (or console summary) the
     moment GitHub finishes uploading assets. See the
     [workflow notification guide](./pi_workflow_notifications.md) for
     cross-platform options and advanced flags.
4. Alternatively, build on your machine:
   ```bash
   ./scripts/build_pi_image.sh
   ```
   Skip either project with `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`.
5. After any download or build, verify integrity:
   ```bash
   sha256sum -c path/to/sugarkube.img.xz.sha256
   ```
   The command prints `OK` when the checksum matches the downloaded image.
6. Before touching hardware, boot the artifact in QEMU to confirm the first-boot
   automation still produces healthy reports:
   ```bash
   sudo make qemu-smoke \
     QEMU_SMOKE_IMAGE=deploy/sugarkube.img.xz \
     QEMU_SMOKE_ARGS="--timeout 420"
   ```
   The helper wraps `scripts/qemu_pi_smoke_test.py`, which mounts the image,
   swaps in a stub verifier, boots `qemu-system-aarch64`, and copies
   `/boot/first-boot-report/` plus `/var/log/sugarkube/` into
   `artifacts/qemu-smoke/`. Use `just qemu-smoke` with the same environment
   variables when you prefer Just over Make.

## 2. Flash the image
- Generate a self-contained report that expands `.img.xz`, flashes, verifies, and
  records the results:
  ```bash
  sudo ./scripts/flash_pi_media_report.py \
    --image ~/sugarkube/images/sugarkube.img.xz \
    --device /dev/sdX \
    --assume-yes \
    --cloud-init ~/sugarkube/cloud-init/user-data.yaml
  ```
  The wrapper stores Markdown/HTML/JSON logs under
  `~/sugarkube/reports/flash-*/flash-report.*`, capturing hardware IDs (resolved
  from `/dev/disk/by-id` symlinks or serials), checksum verification, and
  optional cloud-init diffs (regression coverage:
  `tests/flash_pi_media_linux_test.py::test_list_linux_devices_falls_back_to_by_id`). Use
  ```bash
  sudo FLASH_DEVICE=/dev/sdX FLASH_REPORT_ARGS="--cloud-init ~/override.yaml" make flash-pi-report
  ```
  or the equivalent `just flash-pi-report` recipe to combine install → flash →
  report in one go.
  Prefer the unified CLI? Preview the helper with
  `python -m sugarkube_toolkit pi report --dry-run -- --image ~/sugarkube/images/sugarkube.img.xz --device /dev/sdX --assume-yes`,
  then drop `--dry-run` when you're ready. Everything after the `--` flows to
  `scripts/flash_pi_media_report.py`, so `--cloud-init` and other documented flags work unchanged.
  Regression coverage:
  `tests/test_sugarkube_toolkit_cli.py::test_pi_report_invokes_helper`,
  `tests/test_sugarkube_toolkit_cli.py::test_pi_report_forwards_additional_args`,
  `tests/test_sugarkube_toolkit_cli.py::test_pi_report_respects_existing_dry_run`, and
  `tests/test_sugarkube_toolkit_cli.py::test_pi_report_appends_cli_dry_run_with_separator`
  ensure the CLI forwards arguments exactly as documented while preserving safe dry-run previews,
  even when you supply additional flags after `--`.
  > [!TIP]
  > Need to confirm which removable drives are visible before flashing? Run
  > `python3 scripts/flash_pi_media_report.py --list-devices` without
  > specifying `--image`; regression coverage lives in
  > `tests/flash_pi_media_report_test.py::test_list_devices_without_image_exits_cleanly`.
  > Prefer the CLI wrapper? Run
  > `python -m sugarkube_toolkit pi report --dry-run -- --list-devices` for the same preview. The
  > unified CLI forwards its `--dry-run` flag to the helper so the inventory still runs without
  > touching hardware.
- Stream the expanded image (or the `.img.xz`) directly to removable media:
  ```bash
  sudo ./scripts/flash_pi_media.sh --image ~/sugarkube/images/sugarkube.img --device /dev/sdX --assume-yes
  ```
  The helper auto-detects removable drives, streams `.img` or `.img.xz`
  without temporary files, verifies the written bytes with SHA-256, and
  powers the media off when complete. On Windows, run the PowerShell wrapper:
  Prefer the unified CLI? Preview the helper with
  `python -m sugarkube_toolkit pi flash --dry-run -- --image ~/sugarkube/images/sugarkube.img --device /dev/sdX --assume-yes`,
  then drop `--dry-run` when you're ready. Everything after the `--` flows
  straight to `scripts/flash_pi_media.sh`, so `--cloud-init` and other
  documented flags work unchanged. The unified CLI forwards its `--dry-run`
  flag to the helper so argument validation, device discovery, and checksum
  previews still execute without touching hardware. Regression coverage:
  `tests/flash_pi_media_test.py::test_cloud_init_override_copies_user_data`
  confirms the override lands in `/boot/user-data`, while
  `tests/flash_pi_media_report_test.py::test_run_flash_forwards_cloud_init`
  ensures the reporting wrapper forwards the same flag. CLI parity is guarded
  by `tests/test_sugarkube_toolkit_cli.py::test_pi_flash_invokes_helper`,
  `tests/test_sugarkube_toolkit_cli.py::test_pi_flash_forwards_additional_args`,
  and `tests/test_sugarkube_toolkit_cli.py::test_pi_flash_respects_existing_dry_run`.
  ```powershell
  pwsh -File scripts/flash_pi_media.ps1 --image $env:USERPROFILE\sugarkube\images\sugarkube.img --device \\.\PhysicalDrive1
  ```
- To combine download + verify + flash in one command, run from the repo root:
  ```bash
  sudo make flash-pi FLASH_DEVICE=/dev/sdX
  ```
  or use the new [`just`](https://github.com/casey/just) recipes when you prefer a
  minimal runner without GNU Make:
  ```bash
  sudo FLASH_DEVICE=/dev/sdX just flash-pi
  ```
  Both invocations call `install_sugarkube_image.sh` to keep the local cache fresh before
  writing the media with `flash_pi_media.sh`. The `just` recipe reads `FLASH_DEVICE` (and optional
  `DOWNLOAD_ARGS`) from the environment, so prefix variables as shown when chaining commands.
  Set `DOWNLOAD_ARGS="--release vX.Y.Z"` (or any other flags) in the environment to forward
  custom options into the installer when using `just`.
- Raspberry Pi Imager remains a friendly alternative.
  Use advanced options (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>) to set the
  hostname, credentials and network when flashing `sugarkube.img.xz` manually.
  The repository now ships presets under `docs/templates/pi-imager/` plus a
  renderer script:
  ```bash
  python3 scripts/render_pi_imager_preset.py \
    --preset docs/templates/pi-imager/sugarkube-controller.preset.json \
    --secrets ~/sugarkube/secrets.env \
    --apply
  ```
  The command writes your secrets into Raspberry Pi Imager's configuration so
  the advanced options open pre-populated for the next flash.

## 3. Boot and verify
- Insert the card and power on the Pi.
- k3s installs automatically on first boot. Confirm the node is ready:
  ```bash
  sudo kubectl get nodes
  ```
- token.place and dspace run under `projects-compose.service`. Check status:
  ```bash
  sudo systemctl status projects-compose.service
  ```
- Replay the bundled token.place sample dataset to confirm the relay answers
  health, model, and chat requests:
  ```bash
  python -m sugarkube_toolkit token-place samples --base-url http://127.0.0.1:5000
  ```
  ```bash
  /opt/sugarkube/token_place_replay_samples.py
  ```
  The helper stores JSON responses under
  `~/sugarkube/reports/token-place-samples/`. Expect the chat reply to mention
  "Mock response" when `USE_MOCK_LLM=1` is set in `/opt/projects/token.place/.env`.
- Metrics and dashboards are available immediately:
  - `curl http://<pi-host>:9100/metrics` for the node exporter.
  - `curl http://<pi-host>:12345/metrics` for the aggregated Grafana Agent feed.
  - Visit `http://<pi-host>:19999` to load the Netdata UI and confirm charts render.
- Contract tests live in `tests/projects_compose_contract_test.py` and prevent
  regressions in the compose file. They assert that token.place stays on port
  **5000**, dspace on **3000**, and that every bundled observability container
  sticks to its pinned SHA-256 digest. Run `pytest` after editing
    `scripts/cloud-init/docker-compose.yml` to exercise the checks locally. The
    Bats suite (`tests/pi_node_verifier_output_test.bats`) now also spins up a
    temporary HTTP server so the verifier's health probes must report `pass`
    before changes merge, and verifies that `--full` emits both text output and
    a JSON payload for downstream automation.
- systemd now ships a `k3s-ready.target` that depends on the compose service and waits for
  `kubectl get nodes` to report `Ready`. Inspect the target to confirm the cluster finished
  bootstrapping:
  ```bash
  sudo systemctl status k3s-ready.target
  ```
- If the service fails, inspect logs to troubleshoot:
  ```bash
  sudo journalctl -u projects-compose.service --no-pager
  ```
- When symptoms fall outside the happy path, use the
  [Pi Boot & Cluster Troubleshooting Matrix](./pi_boot_troubleshooting.md) to map
  LED patterns, log locations, and fixes.
- Need deeper diagnostics? Capture a support bundle over SSH:
  ```bash
  SUPPORT_BUNDLE_HOST=pi-a.local \
  SUPPORT_BUNDLE_ARGS="--identity ~/.ssh/id_ed25519" \
    make support-bundle
  ```
  Swap in `just support-bundle` when you prefer Just. The helper saves transcripts under
  `support-bundles/` alongside `summary.json` so you can attach the archive to issues or CI logs.
  Prefer the unified CLI? Preview the helper with
  `python -m sugarkube_toolkit pi support-bundle --dry-run -- pi-a.local --identity ~/.ssh/id_ed25519`
  and drop `--dry-run` once you're ready to collect diagnostics. Everything after the standalone `--`
  flows directly to `scripts/collect_support_bundle.py`.
- A new `first-boot.service` waits for `cloud-init` to finish, expands the root
  filesystem when needed, then runs `pi_node_verifier.sh` (with retries) and
  writes Markdown, HTML, and JSON snapshots under `/boot/first-boot-report/`.
  The directory also collects `cloud-init` logs and keeps the legacy
  `/boot/first-boot-report.txt` in sync for historical runs. Inspect the files
  locally after ejecting the boot media or on the Pi itself:
  ```bash
  sudo ls /boot/first-boot-report
  sudo cat /boot/first-boot-report/summary.md
  sudo cat /boot/first-boot-report.txt
  ```
- The verifier also checks for a `Ready` k3s node, confirms `projects-compose.service`
  is `active`, and curls the token.place and dspace endpoints. Override the HTTP
  probes by exporting `TOKEN_PLACE_HEALTH_URL`, `DSPACE_HEALTH_URL`, and related
  `*_INSECURE` flags before invoking `/opt/sugarkube/pi_node_verifier.sh`.
- Before plugging in additional hardware, rehearse the join flow from your workstation:
```bash
make rehearse-join REHEARSAL_ARGS="sugar-control.local --agents pi-a.local pi-b.local"
```
The helper retrieves the mirrored `/boot/sugarkube-node-token`, prints a join command template,
and SSHes into each candidate node to confirm `https://get.k3s.io` and the k3s API are reachable.
See [Pi Multi-Node Join Rehearsal](./pi_multi_node_join_rehearsal.md) for option walkthroughs.
Prefer the unified CLI? `python -m sugarkube_toolkit pi rehearse --dry-run -- sugar-control.local --agents pi-a.local pi-b.local`
shows the forwarded invocation before running it. Drop `--dry-run` to execute immediately—the CLI
forwards everything after `--` to `scripts/pi_multi_node_join_rehearsal.py`.
- Ready for a turnkey three-node cluster? Promote the rehearsal into automation and wait for
  readiness with a single command:
  ```bash
  just cluster-up CLUSTER_ARGS="sugar-control.local --agents pi-a.local pi-b.local --apply --apply-wait"
  ```
  The helper aborts if a worker fails the preflight, joins each node remotely, and polls the
  control-plane until all nodes report `Ready`. Swap `just` for `make` if you prefer GNU Make.
- When `cloud-init` or `projects-compose.service` fail, `sugarkube-self-heal@.service`
  retries Docker Compose pulls, runs `cloud-init clean --logs`, and restarts the units.
  After three unsuccessful attempts it stores escalation summaries under
  `/boot/first-boot-report/self-heal/` and isolates the system in `rescue.target` so you
  can review logs with a console attached.
- The boot partition now includes recovery hand-offs generated once k3s
  finishes installing:
  - `/boot/sugarkube-kubeconfig` is a sanitized kubeconfig whose secrets are
    redacted. Share it with operators who only need cluster endpoints and
    certificate authorities.
  - `/boot/sugarkube-kubeconfig-full` is the raw admin kubeconfig from the Pi.
    Store it securely after ejecting the media or copy it into your own
    workstation to bootstrap kubectl access immediately.
  - `/boot/sugarkube-node-token` contains the k3s cluster join token. Use it to
    recover stalled boots, enroll new agents, or reseed the control plane. A
    systemd path unit watches for the token and re-runs the exporter if k3s
    publishes it later in the boot sequence.
  Copy any of these files from another machine after ejecting the boot media.
  Regenerate fresh copies later with `sudo k3s kubectl config view --raw` or
  `sudo cat /var/lib/rancher/k3s/server/node-token` if you need to rotate them.
- Want Helm workloads to come online automatically? Drop `*.env` definitions
  under `/etc/sugarkube/helm-bundles.d/` before first boot (or via
  configuration management). Each file declares `RELEASE`, `CHART`, optional
  `VERSION` and `VALUES_FILES`, plus rollout checks. When `k3s-ready.target`
  succeeds, `sugarkube-helm-bundles.service` applies every bundle with
  `helm upgrade --install --atomic`, waits for `kubectl rollout status`, runs
  optional health probes, and writes Markdown logs to
  `/boot/first-boot-report/helm-bundles/`. See
  [Sugarkube Helm Bundle Hooks](./pi_helm_bundles.md) for config keys. Failures bubble up to
  `sugarkube-self-heal@.service` so broken charts stop the boot flow instead of
  hiding until later.
- Optional: publish anonymized health telemetry for fleet dashboards:
  1. Edit `/etc/sugarkube/telemetry.env`, set `SUGARKUBE_TELEMETRY_ENABLE="true"`, and populate
     `SUGARKUBE_TELEMETRY_ENDPOINT` (plus optional token, salt, and tags).
  2. Enable the hourly timer: `sudo systemctl enable --now sugarkube-telemetry.timer`.
  3. Inspect uploads with `journalctl -u sugarkube-telemetry.service --no-pager`.
  Review [Pi Image Telemetry Hooks](./pi_image_telemetry.md) for detailed payload and privacy notes.
- Optional: send first boot and SSD clone updates to Slack or Matrix:
  1. Edit `/etc/sugarkube/teams-webhook.env`, set `SUGARKUBE_TEAMS_ENABLE="true"`, and choose
     `SUGARKUBE_TEAMS_KIND="slack"` or `"matrix"` with the appropriate URL and tokens.
  2. Restart `first-boot.service` or rerun `ssd_clone_service.py` to trigger notifications, or test
     manually with `sudo sugarkube-teams --event first-boot --status info --line "test"`.
  3. Review [Sugarkube Team Notifications](./pi_image_team_notifications.md) for Slack/Matrix setup
     walkthroughs and troubleshooting tips.

The image is now ready for additional repositories or joining a multi-node
k3s cluster.

### Run remote smoke tests

Validate a freshly booted node from another machine with the smoke test harness:

```bash
./scripts/pi_smoke_test.py --json pi-a.local
```

The script SSHes into each host, runs `pi_node_verifier.sh`, and prints a PASS/FAIL summary.
Add `--reboot` to confirm the cluster converges after a restart or use the task-runner wrappers
(`make smoke-test-pi` or `just smoke-test-pi`) when you prefer `SMOKE_ARGS` for flag injection.
See [Pi Image Smoke Test Harness](./pi_smoke_test.md) for detailed usage, including how to
override token.place/dspace health URLs or disable individual checks.

### Automatic SSD cloning on first boot

The Pi image now ships with `ssd-clone.service`, a oneshot systemd unit that waits for a
hot-plugged SSD, auto-selects a target disk, and calls `ssd_clone.py --resume` until the
completion marker `/var/log/sugarkube/ssd-clone.done` appears. The unit is triggered by the
`99-sugarkube-ssd-clone.rules` udev rule whenever a USB or NVMe disk is attached, so it no
longer blocks multi-user boot when no SSD is present. Start it manually with
`sudo systemctl start ssd-clone.service` if you prefer to kick off the process without a
fresh hot-plug. Inspect the journal to monitor progress:

```bash
journalctl -u ssd-clone.service
```

Override detection by exporting `SUGARKUBE_SSD_CLONE_TARGET=/dev/sdX` or extend the helper
flags (for example, `--dry-run`) with `SUGARKUBE_SSD_CLONE_EXTRA_ARGS`. Both environment
variables are respected by the systemd unit and by manual invocations of
`scripts/ssd_clone.py --auto-target`, and automated coverage in
`tests/ssd_clone_auto_target_test.py::test_parse_args_appends_extra_env` keeps the manual
path honest. Adjust the discovery window with
`SUGARKUBE_SSD_CLONE_WAIT_SECS` (default: 900 seconds) or poll frequency with
`SUGARKUBE_SSD_CLONE_POLL_SECS` when slower storage bridges are involved
(regression coverage:
`tests/ssd_clone_auto_target_test.py::test_auto_select_target_waits_for_hotplug`
and
`tests/ssd_clone_auto_target_test.py::test_auto_select_target_timeout`).

### Clone the SD card to SSD with confidence

Run the clone helper directly when you want hands-on control. Always start with a dry-run so
you can review the planned steps before any blocks are written:

```bash
sudo ./scripts/ssd_clone.py --target /dev/sda --dry-run
```

Drop `--dry-run` once you are ready for the clone. The helper replicates the
partition table, formats the target partitions, rsyncs `/boot` and `/`, updates
`cmdline.txt`/`fstab` with the fresh PARTUUIDs, and records progress under
`/var/log/sugarkube/ssd-clone.state.json`. If the process is interrupted, rerun
with `--resume` to continue from the last completed step without repeating
earlier work:

```bash
sudo ./scripts/ssd_clone.py --target /dev/sda --resume
```

Prefer autodetection? Skip `--target` entirely and let the helper pick the best candidate:

```bash
sudo ./scripts/ssd_clone.py --auto-target --dry-run
```

Prefer wrappers? Run the equivalent Makefile or justfile recipes, passing the
target device via `CLONE_TARGET` and additional flags through `CLONE_ARGS`:

```bash
sudo CLONE_TARGET=/dev/sda make clone-ssd CLONE_ARGS="--dry-run"
sudo CLONE_TARGET=/dev/sda just clone-ssd CLONE_ARGS="--resume"
```

Check `/var/log/sugarkube/ssd-clone.state.json` for step-level progress and
`/var/log/sugarkube/ssd-clone.done` once the run completes. Continue with
validation before rebooting into the SSD.

### Validate SSD clones

After migrating the root filesystem to an SSD, run the new validation helper to confirm every layer
references the fresh drive and to sanity-check storage throughput:

```bash
sudo ./scripts/ssd_post_clone_validate.py
```

The script compares `/etc/fstab`, `/boot/cmdline.txt`, and the EEPROM boot order against the live
mounts, then performs a configurable read/write stress test. Reports are stored under
`~/sugarkube/reports/ssd-validation/<timestamp>/`. Prefer the wrappers? Run
`sudo make validate-ssd-clone` or `sudo just validate-ssd-clone` to call the same helper and respect
`VALIDATE_ARGS`. See [`SSD Post-Clone Validation`](./ssd_post_clone_validation.md) for flag details
and sample outputs.

### Monitor SSD health (optional)

Run the SMART monitor whenever you want to record wear levels or temperatures:

```bash
sudo ./scripts/ssd_health_monitor.py --tag post-clone
```

The helper auto-detects the active root device (or accepts `--device /dev/sdX` overrides), captures
`smartctl` output, and stores Markdown/JSON reports under
`~/sugarkube/reports/ssd-health/<timestamp>/`. Prefer wrappers? Use
`sudo make monitor-ssd-health HEALTH_ARGS="--tag weekly"` or the matching `just monitor-ssd-health`
recipe. See the [SSD Health Monitor](./ssd_health_monitor.md) guide for threshold tuning and the
systemd timer example when you want recurring snapshots.

### Recover from SSD issues

If an SSD migration fails or you need to boot from the original SD card again,
run the rollback helper to restore `/boot/cmdline.txt` and `/etc/fstab` to the
SD defaults:

```bash
sudo ./scripts/rollback_to_sd.sh --dry-run
```

Review the planned changes, drop `--dry-run` when ready, then reboot. The script
stores backups and writes a Markdown report to `/boot/sugarkube-rollback-report.md`.
See [SSD Recovery and Rollback](./ssd_recovery.md) for the full walkthrough and
Makefile/justfile shortcuts.

## Codespaces-friendly automation

- Launch a new GitHub Codespace on this repository using the default Ubuntu image.
- Run `just codespaces-bootstrap` (or `task codespaces-bootstrap`, `make codespaces-bootstrap`) once to
  install `gh`, `pv`, and other helpers that the download + flash scripts expect.
- Use `just install-pi-image` or `just download-pi-image` to populate `~/sugarkube/images` with
  the latest release, or trigger `sudo FLASH_DEVICE=/dev/sdX just flash-pi` when you attach a USB
  flasher to the Codespace via the browser or VS Code desktop.
- `just doctor` remains available to validate tooling from within the Codespace without juggling
  Makefiles or bespoke shell aliases.
