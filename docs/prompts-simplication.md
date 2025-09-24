---
title: 'Sugarkube Simplification Prompt'
slug: 'prompts-simplication'
---

# Codebase Simplification Prompt

Use this prompt when you want an automated contributor to reduce the cognitive
load of the sugarkube repository **without** dropping existing capabilities.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Retain the repo's functionality while simplifying framing, onboarding,
maintenance chores, and the learning curve.

CONTEXT:
- Sugarkube blends hardware (see [`cad/`](../cad/) and [`elex/`](../elex/)) with
  software helpers (`scripts/`, `Formula/`, and automation under
  [`docs/`](../docs/)). Start with [`README.md`](../README.md) and the
  contributor map in [`docs/contributor_script_map.md`](../docs/contributor_script_map.md).
- Follow [`AGENTS.md`](../AGENTS.md) and [`CONTRIBUTING.md`](../CONTRIBUTING.md).
- Review [`llms.txt`](../llms.txt) for a machine-readable summary of the repo
  layout and priority workflows.
- Inspect [`.github/workflows/`](../.github/workflows/) so local checks mirror
  CI expectations.
- Run `pre-commit run --all-files`, which shells into
  [`scripts/checks.sh`](../scripts/checks.sh) to install tooling, lint, format,
  and execute tests. The helper triggers `npm ci`, `npm run lint`, and
  `npm run test:ci` whenever a `package.json` is present.
- When documentation changes (`README.md` or files under `docs/`), additionally
  run:
  - `pyspelling -c .spellcheck.yaml`
  - `linkchecker --no-warnings README.md docs/`
- Before committing, scan staged changes with
  `git diff --cached | ./scripts/scan-secrets.py` (helper lives at
  [`scripts/scan-secrets.py`](../scripts/scan-secrets.py)).
- Demand **100% patch coverage on the first test run**—no retries.

REQUEST:
1. Audit onboarding flow, contributor ergonomics, and redundant scaffolding.
2. Propose and implement scoped simplifications (e.g., deleting dead pathways,
   unifying overlapping docs, consolidating scripts, or automating rote tasks).
3. Maintain backwards compatibility, adding guardrails or migration helpers as
   needed.
4. Update docs and automation to reflect the streamlined experience.
5. Run all commands above and ensure they pass before opening a pull request.

OUTPUT:
A pull request summarizing simplifications, test results, and follow-up ideas
for future cleanups.
```

## Upgrade Prompt
Type: evergreen

Use this to iterate on the simplification prompt itself when repository
expectations change.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../AGENTS.md), [`CONTRIBUTING.md`](../CONTRIBUTING.md), and
[`README.md`](../README.md). Consult [`llms.txt`](../llms.txt) for the current
component map.
Run `pre-commit run --all-files` (invokes
[`scripts/checks.sh`](../scripts/checks.sh) to install tooling and execute
linters, formatters, and tests). When docs change also run:
- `pyspelling -c .spellcheck.yaml`
- `linkchecker --no-warnings README.md docs/`
Scan staged changes via `git diff --cached | ./scripts/scan-secrets.py`.
Ensure the final diff delivers **100% patch coverage on the first test run**.

USER:
1. Review this prompt for stale context, missing onboarding cues, or redundant
   instructions compared to other `docs/prompts-*.md` files.
2. Refresh links, command references, and expectations so they align with the
   current repository workflow.
3. Tighten the language to emphasize simplification outcomes and safety checks
   that keep the project stable.
4. Run the commands above and fix any failures.

OUTPUT:
A pull request that modernizes `docs/prompts-simplication.md` while preserving
its focus on safe simplification.
```
