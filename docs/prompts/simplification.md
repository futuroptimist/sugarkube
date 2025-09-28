---
title: 'Sugarkube Simplification Prompt'
slug: 'simplification'
---

# Codebase Simplification Prompt

Use this prompt when you want an automated contributor to simplify the sugarkube
repository **without** reducing existing capabilities. It pairs well with the
roadmap in [`simplification_suggestions.md`](../../simplification_suggestions.md),
which captures current opportunities and ready-made follow-up tasks.

## Before you run the prompt

* Confirm you understand the repo topology from [`README.md`](../../README.md) and
  the contributor map in [`docs/contributor_script_map.md`](../contributor_script_map.md).
* Review the automation stack described in [`llms.txt`](../../llms.txt) and the
  active workflows inside [`.github/workflows/`](../../.github/workflows/) so local
  runs mirror CI expectations.
* Skim the simplification backlog above and log any new ideas you discover so
  they remain actionable for future iterations.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Retain the repo's functionality while simplifying framing, onboarding,
maintenance chores, and the learning curve.

CONTEXT:
- Sugarkube blends hardware (see [`cad/`](../../cad/) and [`elex/`](../../elex/)) with
  software helpers (`scripts/`, `Formula/`, and automation under
  [`docs/`](../)). Start with the contributor story in
  [`docs/index.md`](../index.md) and the script map linked above.
- Follow [`AGENTS.md`](../../AGENTS.md), [`CONTRIBUTING.md`](../../CONTRIBUTING.md),
  and [`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md).
- Run `pre-commit run --all-files`, which shells into
  [`scripts/checks.sh`](../../scripts/checks.sh) to install tooling, lint, format,
  and execute tests. The helper triggers `npm ci`, `npm run lint`, and
  `npm run test:ci` whenever a `package.json` is present.
- When documentation changes (`README.md` or files under `docs/`), additionally
  run:
  - `pyspelling -c .spellcheck.yaml`
  - `linkchecker --no-warnings README.md docs/`
- Before committing, scan staged changes with
  `git diff --cached | ./scripts/scan-secrets.py` (script lives at
  [`scripts/scan-secrets.py`](../../scripts/scan-secrets.py)).
- Demand **100% patch coverage on the first test run**—no retries to minimize the
  chance of regressions or unexpected functionality being introduced.
- If recurring failures surface, log an outage record under
  [`outages/`](../../outages/).

REQUEST:
1. Audit onboarding flows, contributor ergonomics, and redundant scaffolding.
2. Propose and implement scoped simplifications (e.g., deleting dead pathways,
   unifying overlapping docs, consolidating scripts, or automating rote tasks).
3. Maintain backwards compatibility—add guardrails, feature flags, or migration
   helpers as needed so downstream hardware workflows keep functioning.
4. Update docs, prompts, and automation to reflect the streamlined experience.
5. Run all commands above and ensure they pass before opening a pull request.

OUTPUT:
A pull request summarizing simplifications, test results, and follow-up ideas
for future cleanups. Cross-link relevant entries in
[`simplification_suggestions.md`](../../simplification_suggestions.md) or add new
ones so the backlog stays fresh.
```

## Upgrade Prompt
Type: evergreen

Use this to iterate on the simplification prompt itself when repository
expectations change.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../../AGENTS.md), [`CONTRIBUTING.md`](../../CONTRIBUTING.md), and
[`README.md`](../../README.md). Consult [`llms.txt`](../../llms.txt) for the current
component map.
Run `pre-commit run --all-files` (invokes
[`scripts/checks.sh`](../../scripts/checks.sh) to install tooling and execute
linters, formatters, and tests). When docs change also run:
- `pyspelling -c .spellcheck.yaml`
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py`
Ensure the final diff delivers **100% patch coverage on the first test run** to
minimize the chance of regressions or unexpected functionality being
introduced.

USER:
1. Review this prompt for stale context, missing onboarding cues, or redundant
   instructions compared to other prompt docs under `docs/prompts/`.
2. Refresh links, command references, and expectations so they align with the
   current repository workflow and the simplification backlog.
3. Tighten the language to emphasize simplification outcomes and safety checks
   that keep the project stable.
4. Run the commands above and fix any failures.

OUTPUT:
A pull request that modernizes `docs/prompts/simplification.md` while preserving
its focus on safe simplification.
```
