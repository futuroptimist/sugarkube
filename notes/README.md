# Sugarkube Notes Workspace

Use this directory to capture working notes that tutorials and simplification
prompts reference. Templates such as
[`docs/templates/simplification/onboarding-update.md`](../docs/templates/simplification/onboarding-update.md)
expect onboarding updates, retrospective summaries, and other lab evidence to
live under `notes/` (for example, `notes/onboarding/feature-brief.md`). Keeping
these artifacts versioned alongside the codebase makes it easier to audit
improvements and share context with reviewers.

## Structure

- `onboarding/` — track feature briefs, lab journals, and retrospective notes
  produced while following the onboarding update template. The directory ships
  with a `README.md` and seed `feature-brief.md` so docs referencing this path
  stay accurate. Regression coverage lives in
  `tests/test_notes_directory.py::test_onboarding_feature_brief_stub_exists`.
- Additional subdirectories — feel free to add project-specific folders (for
  example, `notes/tests/` or `notes/research/`) while keeping sensitive data out
  of the repository.

## Maintenance

- Reference the onboarding update template when adding new material so the
  evidence matches expectations.
- Leave clear README files inside newly created subdirectories that explain
  their purpose and any redaction requirements.
- Regression coverage:
  `tests/test_notes_directory.py` ensures this workspace and index remain in
  place.
