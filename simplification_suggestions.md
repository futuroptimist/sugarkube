# Sugarkube Simplification Suggestions

_Last reviewed: 2025-09-24_

Use this backlog alongside [`docs/prompts-simplification.md`](docs/prompts-simplification.md)
when you staff simplification-focused PRs. Every initiative keeps existing
hardware and software workflows intact while removing friction for new
contributors.

## How to work this list
- Start with the initiative that unblocks the most teams, then open an issue or
  draft PR that references this document.
- Capture experiment notes or new ideas directly in this file so the backlog
  stays current.
- When work lands, link the merged PR next to the relevant bullet.

## 1. Consolidate helper scripts into a cohesive CLI toolkit
**Problem:** `scripts/` exposes 30+ standalone entrypoints (for example,
`build_pi_image.sh`, `pi_smoke_test.py`, `workflow_flash_instructions.py`, and
`sugarkube_doctor.sh`). Contributors must memorize file names and bespoke flags
before they can automate common tasks.

**Current assets:**
- [`docs/contributor_script_map.md`](docs/contributor_script_map.md) – manual
  index of existing scripts.
- [`scripts/checks.sh`](scripts/checks.sh) – canonical runtime environment.
- [`Formula/`](Formula/) – examples of Homebrew packaging that could inspire
  CLI packaging.

**First steps:**
1. Group shared logic (logging, argument parsing, artifact handling) into a
   dedicated Python module such as `scripts/toolkit/`.
2. Expose a unified `sugarkube` CLI via `python -m sugarkube_toolkit` with
   subcommands like `image build`, `image flash`, `pi verify`, and `docs verify`.
3. Provide thin wrapper scripts that print a deprecation notice before handing
   off to the new CLI so existing docs remain valid during the transition.

**Safeguards:**
- Mirror existing exit codes and output formats so CI and human workflows do not
  break unexpectedly.
- Add smoke tests under `tests/cli/` that call both the legacy wrappers and the
  new CLI.

**Payoff:** Streamlined onboarding, consistent UX, easier automation in CI, and
fewer places to update when APIs or dependencies change.

**Follow-up metrics:** Track how many scripts depend on the shared toolkit and
log onboarding feedback about command discoverability.

## 2. Establish a single, guided onboarding path
**Problem:** The README links to numerous deep dives—`docs/pi_carrier_launch_playbook.md`,
`docs/pi_image_quickstart.md`, `docs/pi_image_contributor_guide.md`, and
others—without a "start here" narrative.

**Current assets:**
- [`docs/index.md`](docs/index.md) – high-level overview used by the docs site.
- [`docs/backlog.md`](docs/backlog.md) – captures in-flight documentation work.
- [`docs/templates/`](docs/templates/) – reusable building blocks for long-form
  guides.

**First steps:**
1. Draft a `docs/start-here.md` handbook with three tracks: 15-minute tour,
   day-one contributor checklist, and advanced references.
2. Use tabbed callouts (matching the docs site markdown extensions) to
   differentiate hardware builders vs. software contributors.
3. Embed a quick architecture diagram or recorded walkthrough so new folks
   understand how the Pi image, solar hardware, and CI fit together.

**Safeguards:**
- Cross-link safety notices and ESD guidelines from the new handbook to avoid
  duplicating critical instructions.
- Keep the README lightweight by linking to the handbook instead of copying its
  content.

**Payoff:** Decreases analysis paralysis, shortens the time-to-first-change, and
clarifies where deeper manuals live.

**Follow-up metrics:** Track README bounce rate (via docs site analytics) and
collect feedback from the #onboarding Slack thread.

## 3. Automate recurring documentation chores
**Problem:** Contributors manually run `pyspelling`, `linkchecker`, and other
checks. The prompts require 100% compliance, but setup steps remain scattered.

**Current assets:**
- [`scripts/checks.sh`](scripts/checks.sh) – orchestrates repo-wide tooling.
- [`justfile`](justfile) and [`Makefile`](Makefile) – existing task runners.
- [`docs/prompts-codex-docs.md`](docs/prompts-codex-docs.md) – sets doc-quality
  expectations for automated contributors.

**First steps:**
1. ✅ Introduce a `just simplify-docs` (and equivalent `make docs-simplify`
   target) that installs prerequisites, runs spellcheck/linkcheck, and surfaces
   common fixes. `scripts/checks.sh --docs-only` powers both wrappers and now
   has regression coverage in `tests/checks_script_test.py::test_docs_only_mode_runs_docs_checks`.
2. Extend `scripts/checks.sh` with a `--docs-only` flag that skips hardware
   toolchains when unnecessary.
3. Bundle templates in `docs/templates/` for onboarding updates, prompt refreshes,
   and simplification sprints so authors can focus on content.

**Safeguards:**
- Ensure the new targets still respect `AGENTS.md` expectations (100% patch
  coverage, secret scanning, etc.).
- Document the new commands in the README and relevant prompts.

**Payoff:** Less manual toil, more consistent docs, and faster iteration on
simplification efforts.

**Follow-up metrics:** Monitor how often CI fails due to docs checks and track
usage of the new task runners.

## 4. Modularize hardware vs. software knowledge bases
**Problem:** Hardware and software instructions are interleaved under `docs/`,
which makes it difficult to filter by persona.

**Current assets:**
- Pi image guides such as [`docs/pi_image_quickstart.md`](docs/pi_image_quickstart.md)
  and [`docs/pi_image_contributor_guide.md`](docs/pi_image_contributor_guide.md).
- [`docs/electronics_basics.md`](docs/electronics_basics.md) and
  [`docs/solar_basics.md`](docs/solar_basics.md) – repeated background material.
- [`docs/status/`](docs/status/) – status dashboards that could host persona
  rollups.

**First steps:**
1. Introduce `docs/hardware/index.md` and `docs/software/index.md` pages that
   summarize relevant guides, tooling, and safety notices.
2. Tag existing pages with front matter metadata (e.g., `persona: hardware`) so
   the static site can build filtered navigation panes.
3. Move duplicated primers into a shared "Fundamentals" section referenced by
   both personas.

**Safeguards:**
- Maintain canonical URLs by adding redirect stubs or shortlinks when pages move.
- Verify PDF exports (e.g., `docs/pi_carrier_field_guide.pdf`) still render after
  the restructure.

**Payoff:** Clearer mental model of the repository, easier delegation across
mixed hardware/software teams, and fewer doc edits required when scope changes.

**Follow-up metrics:** Survey contributors on the clarity of persona-based docs
and record navigation improvements in the docs changelog.

## 5. Stage simplification via observability dashboards
**Problem:** Simplification work touches CI, release pipelines, and Pi telemetry
(`docs/pi_image_telemetry.md`), but impact is hard to quantify during refactors.

**Current assets:**
- [`docs/pi_workflow_notifications.md`](docs/pi_workflow_notifications.md) – CI
  alerting overview.
- [`docs/status/`](docs/status/) – existing dashboards and status badges.
- [`scripts/publish_telemetry.py`](scripts/publish_telemetry.py) – telemetry
  exporter for Pi builds.

**First steps:**
1. Define a core set of ergonomics KPIs (image build duration, smoke-test pass
   rate, onboarding checklist completion time) and document them in
   `docs/status/README.md`.
2. Extend the telemetry publisher to emit these metrics into Grafana (or persist
   markdown snapshots under `docs/status/metrics/`).
3. Add a changelog section dedicated to ergonomics improvements so momentum is
   visible across releases.

**Safeguards:**
- Gate any new telemetry behind configurable credentials to avoid leaking secrets
  in CI logs.
- Document fallback procedures if dashboards fail so simplification work stays
  observable.

**Payoff:** Data-driven iteration keeps the codebase healthy while preventing
regressions during simplification pushes.

**Follow-up metrics:** Track dashboard adoption and ensure each simplification
initiative references at least one KPI before it ships.
