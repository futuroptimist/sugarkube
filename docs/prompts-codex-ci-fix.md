---
title: 'Sugarkube Codex CI-Failure Fix Prompt'
slug: 'prompts-codex-ci-fix'
---

# Codex CI-Failure Fix Prompt

Use this prompt to diagnose and resolve failing checks in this repository.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Diagnose and fix continuous integration failures so all checks pass.

CONTEXT:
- Follow [AGENTS.md](../AGENTS.md) and [README.md](../README.md) for workflow and
  testing requirements.
- Inspect [`.github/workflows/`](../.github/workflows/) to understand the checks
  run in continuous integration.
- Run `pre-commit run --all-files` to reproduce failures; it executes
  `scripts/checks.sh`.
- If a Node toolchain exists (`package.json` is present), also run:
  - `npm ci`
  - `npm run lint`
  - `npm run test:ci`
- Ensure `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  and `linkchecker --no-warnings README.md docs/` succeed.
- Install missing dependencies with `pip` or `npm` as needed.
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`
  before committing.

REQUEST:
1. Re-run the failing check locally.
2. Investigate and apply minimal fixes.
3. Re-run all checks until they succeed.

OUTPUT:
A pull request describing the fix and showing passing checks.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [AGENTS.md](../AGENTS.md) and [README.md](../README.md).
Run `pre-commit run --all-files`.
If a Node toolchain exists (`package.json` is present), also run:
- `npm ci`
- `npm run lint`
- `npm run test:ci`
Then run:
- `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
