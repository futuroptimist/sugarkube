# Sugarkube Status Dashboards

Track the health of Sugarkube automation and ergonomics efforts from a single
reference point. This index complements the existing Shields.io badges (for
example [`docs/status/hardware-boot.json`](./hardware-boot.json)) by outlining
which metrics matter, how they are measured, and where to publish updates so
contributors can tell at a glance whether the platform is improving.

## Ergonomics KPIs

These core indicators gauge how approachable the platform feels for new and
returning contributors. Record snapshots in release notes, internal dashboards,
or documentation updates whenever the numbers move.

### Image build duration

* **What it measures:** Total runtime of the GitHub Actions `pi-image` workflow
  from queue to artifact upload.
* **Why it matters:** Faster builds shorten the feedback loop when iterating on
  cloud-init hooks, bundled repositories, or base OS upgrades.
* **How to measure:** Pull the `workflow_run.duration_ms` field from the
  `pi-image` workflow or export the value from `scripts/publish_telemetry.py`
  when posting build metrics.
* **Where to log it:** Include the value in the `pi-image` release notes and any
  dashboard cards that summarize build health.

### Smoke-test pass rate

* **What it measures:** Success percentage of `scripts/pi_smoke_test.py` runs
  across physical hardware and QEMU rehearsals.
* **Why it matters:** Catching regressions in token.place, dspace, or verifier
  plumbing keeps first boot reliable for real deployments.
* **How to measure:** Track the ratio of `PASS` lines in the smoke test logs or
  record the result exported by the `pi_smoke_test` JSON summary. Combine
  results from the scheduled QEMU job with manual hardware runs documented via
  the hardware boot badge updates.
* **Where to log it:** Summarize the current pass rate in `docs/status/` badge
  descriptions or in a `status.md` snippet linked from contributor retros.

### Onboarding checklist completion time

* **What it measures:** The elapsed time for a new contributor to work through
  the onboarding checklist from [docs/tutorials/index.md](../tutorials/index.md)
  (cloning the repo, running `just codespaces-bootstrap`, generating required
  artifacts, and opening their first PR).
* **Why it matters:** Lower completion times signal that documentation, prompts,
  and automation helpers remain approachable.
* **How to measure:** Capture timestamps in tutorial artifacts (for example,
  commit logs or notes files) and subtract the start time of Tutorial 1 from the
  completion time of Tutorial 4’s checklist submission.
* **Where to log it:** Record representative values in contributor retros,
  simplification sprint reports, or a shared spreadsheet so trends stay visible.

## Publishing updates

* Snapshot metrics during each release and link supporting evidence (workflow
  URLs, smoke-test reports, tutorial logs).
* When numbers change materially, update dashboards (Markdown badges, Grafana,
  or internal tools) and reference the delta in the next changelog entry.
* Tie simplification proposals back to at least one KPI so reviewers can confirm
  the expected impact.

## Related resources

- [docs/pi_image_quickstart.md](../pi_image_quickstart.md) — operational source
  of truth for build, flash, and verification flows.
- [docs/pi_smoke_test.md](../pi_smoke_test.md) — CLI usage and report formats for
  the smoke-test harness.
- [docs/tutorials/index.md](../tutorials/index.md) — onboarding roadmap used to
  measure checklist completion time.
- [scripts/publish_telemetry.py](../../scripts/publish_telemetry.py) — exporter
  that can surface build metrics alongside other fleet telemetry.
