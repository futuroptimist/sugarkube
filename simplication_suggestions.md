# Sugarkube Simplification Suggestions

These proposals aim to keep existing functionality intact while reducing
onboarding friction, repetitive chores, and the overall learning curve. Each
idea is scoped so it can be delivered incrementally.

## 1. Consolidate helper scripts into a cohesive CLI toolkit
- **Pain points:** `scripts/` contains 30+ standalone entrypoints (for example,
  `build_pi_image.sh`, `pi_smoke_test.py`, `workflow_flash_instructions.py`, and
  `sugarkube_doctor.sh`). New contributors must read `docs/contributor_script_map.md`
  and memorize file names before they can automate common tasks.
- **Proposal:** Group shared functionality into a Python package (e.g.,
  `sugarkube_toolkit`) with a unified `sugarkube` CLI front-end. Expose commands
  like `sugarkube image build`, `sugarkube image flash`, `sugarkube pi verify`,
  and `sugarkube docs verify` that internally reuse existing modules.
- **Quick wins:**
  - Lift reusable logic (logging, argument parsing, artifact downloads) into
    shared utilities under `scripts/` or a new `toolkit/` module.
  - Provide `--dry-run` and `--json` flags consistently across commands.
  - Maintain backwards compatibility with thin wrappers that print deprecation
    notices before forwarding to the new CLI.
- **Benefits:** Streamlined onboarding, consistent UX, easier automation in CI,
  and fewer places to patch when APIs change.

## 2. Establish a single, guided onboarding path
- **Pain points:** The README links to numerous deep dives (e.g.,
  `docs/pi_carrier_launch_playbook.md`, `docs/pi_image_quickstart.md`, and
  `docs/pi_image_contributor_guide.md`). First-time contributors struggle to
  choose the right entry point.
- **Proposal:** Create a "Start here" handbook that presents a three-tiered
  journey: 15-minute tour, day-one contributor checklist, and advanced
  references. Use tabbed or callout components (compatible with the existing
  docs site) to guide hardware builders vs. software contributors.
- **Quick wins:**
  - Add a short orientation video or diagram summarizing the Pi image, solar
    hardware, and CI workflows.
  - Move repetitive safety notes into shared partials or include macros so they
    stay synchronized.
  - Link the new handbook from `README.md`, the docs index, and the prompt docs.
- **Benefits:** Decreases analysis paralysis, shortens the time-to-first-change,
  and clarifies where deeper manuals live.

## 3. Automate recurring documentation chores
- **Pain points:** Contributors manually run `pyspelling`, `linkchecker`, and
  other checks. The prompts require 100% compliance, but setup steps remain
  scattered across docs and scripts.
- **Proposal:** Provide a `just simplify-docs` (or `make docs-simplify`) recipe
  that installs prerequisites, runs spellcheck/linkcheck, and surfaces common
  fixes. Bundle templates for recurring updates (release notes, outage records)
  so authors can focus on content.
- **Quick wins:**
  - Extend `scripts/checks.sh` with a `--docs-only` flag that skips hardware
    toolchains when unnecessary.
  - Pre-fill `docs/templates/` with checklists for onboarding, prompt reviews,
    and simplification sprints.
  - Add GitHub issue forms that call the new helper, reducing copy/paste errors.
- **Benefits:** Less manual toil, more consistent docs, and faster iteration on
  simplification efforts.

## 4. Modularize hardware vs. software knowledge bases
- **Pain points:** Hardware and software instructions are interleaved under
  `docs/`, making it difficult to filter by persona.
- **Proposal:** Introduce top-level indices (`docs/hardware/index.md`,
  `docs/software/index.md`) that summarize relevant guides, tooling, and safety
  notices. Tag pages with front matter metadata (e.g., `persona: hardware`) so
  the static site can build filtered navigation panes.
- **Quick wins:**
  - Move duplicated background primers (`docs/solar_basics.md`,
    `docs/electronics_basics.md`) into a shared "Fundamentals" section.
  - Cross-link automation docs (like `projects-compose.md` and
    `pi_workflow_notifications.md`) from the software index.
  - Provide printable checklists per persona using the existing PDF renderer
    (`scripts/render_field_guide_pdf.py`).
- **Benefits:** Clearer mental model of the repository, easier delegation across
  mixed hardware/software teams, and fewer doc edits required when scope changes.

## 5. Stage simplification via observability dashboards
- **Pain points:** Simplification work touches CI, release pipelines, and Pi
  telemetry (`docs/pi_image_telemetry.md`). Impact is hard to see during refactors.
- **Proposal:** Ship Grafana dashboards (or markdown snapshots) that track key
  metrics: image build duration, smoke-test pass rate, onboarding task completion
  time. Tie them into `docs/status/` so progress is visible.
- **Quick wins:**
  - Extend `scripts/publish_telemetry.py` to summarize simplification metrics.
  - Add a changelog section dedicated to ergonomics improvements.
  - Document KPIs in the new onboarding handbook so teams can measure success.
- **Benefits:** Data-driven iteration keeps the codebase healthy while avoiding
  regressions during simplification pushes.
