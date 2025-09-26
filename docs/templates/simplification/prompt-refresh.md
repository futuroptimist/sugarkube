# Prompt Refresh Template

## Current Guidance
- Prompt file(s):
- Linked docs or automation that rely on this guidance:
- Known pain points or reports that triggered the refresh:

## Proposed Changes
- Summarize edits by section (additions, removals, clarifications).
- Call out any new guardrails or checklists contributors must follow.
- Note tooling or workflow updates (new commands, required outputs, etc.).

## Verification
- Dry run the prompt against a recent PR or simulation.
- Confirm tests achieve 100% patch coverage on the first run.
- Capture transcripts or artifacts proving the new flow works.

## Rollout Notes
- Update cross-links in other prompts or docs.
- Notify affected contributor groups (automation, docs, hardware).
- Stage follow-up work for deeper changes uncovered during review.

## Follow-up
- Monitor subsequent contributions for regressions.
- File tracking issues for improvements deferred out of scope.
- Record lessons learned in `docs/prompts/CHANGELOG.md` (create if missing).

## Actions
- [ ] Prompt diff reviewed and approved
- [ ] Regression tests updated or added
- [ ] Docs checks: `pyspelling -c .spellcheck.yaml`
- [ ] Docs checks: `linkchecker --no-warnings README.md docs/`
- [ ] Communication plan executed
