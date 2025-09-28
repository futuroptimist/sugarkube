# Pi Image Telemetry Hooks

The sugarkube image now ships an optional telemetry publisher that reports anonymized verifier
results to a dashboard of your choosing. The helper runs `pi_node_verifier.sh --json`, hashes stable
hardware identifiers, and posts a compact JSON payload so operators can monitor first-boot health
across labs without exposing secrets.

## What the publisher sends

`sugarkube-publish-telemetry` emits a JSON document that contains:

- A hashed instance identifier derived from `/etc/machine-id`, the Pi serial number, and
  `/proc/device-tree/model`. Add a `SUGARKUBE_TELEMETRY_SALT` to re-hash the value per deployment.
- The full `pi_node_verifier` check matrix and a summary of passed, failed, skipped, and unknown
  checks.
- Basic environment metadata: kernel version, hardware model, selected keys from `/etc/os-release`,
  and the current uptime in seconds.
- Optional labels (comma-separated `SUGARKUBE_TELEMETRY_TAGS`) to group devices on your dashboard.
- A list of errors captured while running the verifier (timeouts, non-zero exit codes, JSON parse
  issues) so ingestion pipelines can surface telemetry gaps explicitly.

Raw kubeconfigs, hostnames, or IP addresses never leave the Pi. Only hashed fingerprints and the
minimal health summary are posted.

## Configure the endpoint

Every image includes `/etc/sugarkube/telemetry.env` with commented defaults:

```bash
sudo nano /etc/sugarkube/telemetry.env
```

Update the file with your collector URL and credentials:

```ini
SUGARKUBE_TELEMETRY_ENABLE="true"
SUGARKUBE_TELEMETRY_ENDPOINT="https://dashboard.example/api/ingest"
SUGARKUBE_TELEMETRY_SALT="classroom-2025"
SUGARKUBE_TELEMETRY_TAGS="beta-lab,pi-a"
```

The publisher exits early when `SUGARKUBE_TELEMETRY_ENABLE` is still `false`, which keeps telemetry
completely opt-in.

Need authentication? Append a `SUGARKUBE_TELEMETRY_TOKEN` entry to the same file once you have a
bearer token from your collector.

## Enable the systemd timer

Once the environment file is updated, activate the timer that runs the publisher every hour after an
initial five-minute delay:

```bash
sudo systemctl enable --now sugarkube-telemetry.timer
```

Check the timer and service status at any time:

```bash
systemctl list-timers sugarkube-telemetry.timer
journalctl -u sugarkube-telemetry.service --no-pager
```

Disable telemetry later with:

```bash
sudo systemctl disable --now sugarkube-telemetry.timer
sudo sed -i 's/SUGARKUBE_TELEMETRY_ENABLE="true"/SUGARKUBE_TELEMETRY_ENABLE="false"/' \
  /etc/sugarkube/telemetry.env
```

## Publish on demand

For manual reporting or smoke testing collector credentials, run the helper directly:

```bash
sudo make publish-telemetry TELEMETRY_ARGS="--dry-run --print-payload"
```

Pass `--endpoint`, `--token`, or `--tags` inside `TELEMETRY_ARGS` to override values from the
environment file. Developers working from this repository can do the same with:

```bash
sudo just publish-telemetry telemetry_args="--dry-run"
```

Both invocations call `scripts/publish_telemetry.py`, which automatically locates
`pi_node_verifier.sh`, generates an anonymized payload, and prints it when `--dry-run` is supplied.

### Capture Markdown snapshots

Set `SUGARKUBE_TELEMETRY_MARKDOWN_DIR` or pass `--markdown-dir docs/status/metrics` to archive each
payload as a Markdown snapshot alongside your dashboards. The helper writes
`telemetry-<hash>.md` files that summarize verifier counts, failed checks, environment metadata, and
errors so changes are easy to track during retros. Regression coverage lives in
`tests/test_publish_telemetry.py::test_main_writes_markdown_snapshot`.

## Collector integration tips

- Ingest payloads as-is to keep future schema extensions forward-compatible. The top-level
  `schema` field is versioned (`https://sugarkube.dev/telemetry/v1`).
- Track `verifier.summary.failed_checks` to raise alerts when token.place or dspace regressions
  appear across fleets.
- Combine the hashed `instance.id` with your own salt to anonymize data further before storing it in
  a database shared outside your team.
- Use `SUGARKUBE_TELEMETRY_VERIFIER_TIMEOUT` to accommodate slow Pi clusters that need more than the
  default three minutes for a full verifier run.
- Pair telemetry uploads with the built-in exporters by scraping
  `http://<pi-host>:12345/metrics` (Grafana Agent), `:9100` (node), and Netdata's dashboard on
  `:19999`.

Regression tests in `tests/test_publish_telemetry.py` guard this three-minute default so the CLI and
documentation stay aligned as the helper evolves.

By shipping telemetry hooks as an opt-in service, operators gain shared observability across lab
installs while keeping the default image silent until explicitly configured.
