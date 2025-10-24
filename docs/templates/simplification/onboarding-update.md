# Onboarding Update Template

## Goals
- What onboarding friction are we removing?
- Which personas benefit (hardware, docs, automation)?
- How will we measure success (time-to-first-change, tutorial completion, etc.)?

## Required Artifacts
- Link to the updated quickstart, handbook, or tutorial draft.
- Evidence that automation (`make doctor`, `START_HERE_ARGS="--path-only" just start-here`,
  `START_HERE_ARGS="--path-only" make start-here`,
  `START_HERE_ARGS="--path-only" task start-here`,
  `python -m sugarkube_toolkit docs start-here --path-only` from the repo root or
  `./scripts/sugarkube docs start-here --path-only` when working in a subdirectory)
  reflects the new path and prints the updated guidance. The Make/Just wrappers now
  defer to `sugarkube docs start-here`, keeping their output aligned with the CLI. Legacy
  automation that still forwards `--no-content` now emits a deprecation warning before printing
  the handbook path (`tests/test_sugarkube_toolkit_cli.py::test_docs_start_here_no_content_warns`,
  `tests/test_start_here_command.py::test_start_here_main_path_only_alias_warns`).
- Update `notes/README.md` (guarded by `tests/test_notes_directory.py`) with links to
  any onboarding evidence you add under `notes/` so collaborators can follow the
  breadcrumbs left by this template.
- Screenshots or recordings that walk through the refreshed flow.

## Stakeholders
- DRI:
- Reviewers:
- Impacted docs/scripts:

## Rollout Plan
- Dry run the new onboarding steps on a clean workstation or Codespace.
- Capture before/after diffs for docs and automation helpers.
- Coordinate announcements (Slack, docs site changelog, README badges).

## Follow-up
- Survey new contributors after launch and record feedback.
- Archive evidence in `notes/onboarding/`.
- File follow-up issues for deferred improvements.

## Actions
- [ ] Draft reviewed by stakeholders
- [ ] Automation validated with `pre-commit run --all-files`
- [ ] Docs checks: `pyspelling -c .spellcheck.yaml`
- [ ] Docs checks: `linkchecker --no-warnings README.md docs/`
- [ ] Post-launch survey scheduled
