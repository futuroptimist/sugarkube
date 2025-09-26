# Sugarkube Self-Heal Service

`sugarkube-self-heal@.service` wraps `scripts/self_heal_service.py` so failed boot-
critical units retry with useful telemetry before escalating to rescue mode. The
helper is installed on every image build and watches for units that declare
`OnFailure=sugarkube-self-heal@%n.service` (for example
`projects-compose.service`, `cloud-final.service`, and
`sugarkube-helm-bundles.service`).

When a monitored unit fails the helper:

1. Records the failure inside `/var/log/sugarkube/self-heal/<unit>.json` with
   timestamps, retry counts, and exit codes.
2. Copies Markdown summaries, the most recent journal excerpt, and Docker/Kubernetes
   command output to `/boot/first-boot-report/self-heal/<unit>/` for air-gapped
   debugging.
3. Retries the unit up to the configured limit (default three attempts) before
   isolating the host into `rescue.target` so operators can intervene safely.

## Manual invocation

Run the helper directly to rehearse recovery flows without waiting for a real
failure:

```sh
sudo /opt/sugarkube/self_heal_service.py --unit projects-compose.service \
  --reason "dry run"
```

Supply `--state-dir` and `--boot-dir` to redirect logs when testing from a
workstation. The Python entrypoint honours environment variables like
`SUGARKUBE_SELF_HEAL_MAX_ATTEMPTS` and `SUGARKUBE_SELF_HEAL_RETRY_DELAY` so you
can shorten loops during rehearsals.

## Debugging tips

- Inspect `/boot/first-boot-report/self-heal/<unit>/` first; it mirrors the
  Markdown summaries uploaded to CI artifacts.
- Check `/var/log/sugarkube/self-heal/<unit>.json` for the retry history and the
  final decision (`retry`, `succeeded`, `rescued`).
- Use `journalctl -u "sugarkube-self-heal@<unit>.service" --no-pager` to watch
  live progress while the helper runs.
- Pair the logs with `make support-bundle` to archive additional context during
  post-mortems.

## Regression coverage

Automated coverage for the helper lives in:

- `tests/self_heal_service_test.py` – exercises retry limits, rescue mode, and
  logging behavior.
- `tests/self_heal_service_docs_test.py` – ensures this README documents the key
  locations operators rely on during incidents.
