---
title: 'Sugarkube Pi Image Improvement Checklist Prompt'
slug: 'prompt-pi-image-improvement-checklist'
---

# Pi Image Improvement Checklist Implementation Prompt
Type: evergreen

Use this prompt to implement items from [`docs/pi_image_improvement_checklist.md`](./pi_image_improvement_checklist.md).

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Ship incremental improvements from the Pi image UX & automation checklist.

CONTEXT:
- Review the checklist in [`docs/pi_image_improvement_checklist.md`](./pi_image_improvement_checklist.md)
  and pick one actionable item.
- Inspect related guides and scripts such as
  [`docs/pi_image_quickstart.md`](./pi_image_quickstart.md), [`scripts/`](../scripts/), and the
  root [`Makefile`](../Makefile) to understand current behavior.
- Follow [`AGENTS.md`](../AGENTS.md) and repository conventions in [`README.md`](../README.md).
- Before committing, run:
  - `pre-commit run --all-files`
  - `pyspelling -c .spellcheck.yaml`
  - `linkchecker --no-warnings README.md docs/`
  - `git diff --cached | ./scripts/scan-secrets.py`
- Ensure the refined prompt explicitly instructs contributors to attain **100% patch coverage on the
  first test run** without retries.
- Design changes and supporting tests to achieve **100% patch coverage on the first test run** with
  no retries.

REQUEST:
1. Choose one unchecked checklist task and implement it end-to-end (code, docs, tooling as
   needed).
2. Update any affected documentation, samples, or automation scripts to match the new behavior.
3. Tick the corresponding checkbox in `docs/pi_image_improvement_checklist.md` and summarize the
   change in relevant docs.
4. Run the commands above and ensure they succeed with 100% patch coverage on the first attempt.
5. Commit with a concise message and prepare a PR summary highlighting the checklist item you
   completed.

OUTPUT:
A pull request that completes at least one checklist item with all required checks passing.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to iterate on the Pi Image Improvement Checklist Implementation Prompt above.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Improve the "Pi Image Improvement Checklist Implementation Prompt" so it reliably guides agents
to ship unchecked items from [`docs/pi_image_improvement_checklist.md`](./pi_image_improvement_checklist.md).

CONTEXT:
- Review the prompt text directly above this one and ensure it is accurate, actionable, and
  aligned with the checklist workflow.
- Cross-check supporting docs and automation referenced in that prompt (for example,
  [`docs/pi_image_quickstart.md`](./pi_image_quickstart.md), [`scripts/`](../scripts/), and the root
  [`Makefile`](../Makefile)).
- Follow [`AGENTS.md`](../AGENTS.md) and repository conventions in [`README.md`](../README.md).
- Before committing, run:
  - `pre-commit run --all-files`
  - `pyspelling -c .spellcheck.yaml`
  - `linkchecker --no-warnings README.md docs/`
  - `git diff --cached | ./scripts/scan-secrets.py`

USER:
1. Identify confusing, outdated, or missing guidance in the implementation prompt above.
2. Update the prompt so agents consistently implement unchecked checklist items end-to-end.
3. Emphasize the need for 100% patch coverage on the first test execution.
4. Run the commands listed under CONTEXT and confirm they succeed.

OUTPUT:
A pull request with an improved checklist implementation prompt and passing checks.
```
