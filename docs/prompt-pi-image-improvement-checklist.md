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

REQUEST:
1. Choose one unchecked checklist task and implement it end-to-end (code, docs, tooling as
   needed).
2. Update any affected documentation, samples, or automation scripts to match the new behavior.
3. Tick the corresponding checkbox in `docs/pi_image_improvement_checklist.md` and summarize the
   change in relevant docs.
4. Run the commands above and ensure they succeed.
5. Commit with a concise message and prepare a PR summary highlighting the checklist item you
   completed.

OUTPUT:
A pull request that completes at least one checklist item with all required checks passing.
```
