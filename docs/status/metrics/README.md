# Sugarkube Telemetry Snapshot Archive

Store Markdown exports from `scripts/publish_telemetry.py` here so ergonomics
metrics remain versioned alongside the documentation. The helper already
supports both `--markdown-dir` and the `SUGARKUBE_TELEMETRY_MARKDOWN_DIR`
environment variable, letting you persist snapshots without extra scripting.

## Generate snapshots

Run the telemetry publisher after a verifier session to capture the latest
counts and metadata:

```bash
python scripts/publish_telemetry.py \
  --endpoint https://example.com/telemetry \
  --markdown-dir docs/status/metrics
```

> **Note:** When `SUGARKUBE_TELEMETRY_ENABLE` remains `false`, the helper still
> runs the verifier and writes the Markdown snapshot, but it skips uploading the
> payload and prints a reminder to enable telemetry (or pass `--force`) once
> you're ready to publish it. Regression coverage:
> `tests/test_publish_telemetry.py::test_main_writes_markdown_snapshot_when_disabled`.

When automating from cron or CI, set the environment variable instead of passing
the flag explicitly:

```bash
export SUGARKUBE_TELEMETRY_MARKDOWN_DIR=docs/status/metrics
python scripts/publish_telemetry.py --endpoint https://example.com/telemetry
```

Each run writes a file named `telemetry-<id>.md` summarising verifier totals,
failed checks, environment snapshots, and captured errors. The filenames are
stable hashes so you can diff changes between releases.

## Housekeeping

- Generated snapshots are ignored via [`.gitignore`](./.gitignore); keep only the
  curated Markdown reports that should live in version control.
- Link the most recent snapshot from the main
  [status dashboard](../README.md) so contributors can review historical
  performance trends alongside the KPI definitions.
- Tests in `tests/test_publish_telemetry.py` and
  `tests/test_status_metrics_docs.py` guard this workflow—update the assertions
  when adding new guidance.
