# Onboarding Feature Briefs

Use this workspace to capture the lab evidence produced while following the
[simplification onboarding update template](../../docs/templates/simplification/onboarding-update.md).
Each brief should summarize the feature, outline the failing or missing behavior
observed during onboarding, and record the remediation you shipped. Keeping the
notes alongside the codebase makes it easy to audit improvements and revisit
decisions during retrospectives.

## Getting started

1. Copy `docs/templates/simplification/onboarding-update.md` into this folder and
   tailor it for the work you are documenting (for example,
   `feature-brief-<date>.md`).
2. Replace placeholder prompts with concrete evidence: command transcripts,
   screenshots, links to workflow runs, and references to supporting PRs.
3. Remove sensitive data (tokens, hostnames, or private URLs) before committing.
4. Link the completed brief from the corresponding pull request description so
   reviewers can trace context quickly.

A seed brief (`feature-brief.md`) lives beside this README to provide a starting
point. Regression coverage: `tests/test_notes_directory.py::test_onboarding_feature_brief_stub_exists`
ensures this workspace stays in sync with the documentation.
