---
title: 'Sugarkube Codex Docs Prompt'
slug: 'prompts-codex-docs'
---

# Codex Documentation Prompt

Use this prompt to refine build guides and reference material.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Keep the documentation clear and accurate.

CONTEXT:
- Docs live in [`docs/`](./).
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for style,
  testing, and repository conventions.
- Inspect [`.github/workflows/`](../.github/workflows/) to see which checks run in CI.
- Run `pre-commit run --all-files` to invoke [`scripts/checks.sh`](../scripts/checks.sh) for
  linting, formatting, and tests. If `package.json` exists, the script automatically
  runs `npm ci`, `npm run lint`, and `npm run test:ci`.
- Structure edits and any supporting tests so the diff achieves **100% patch coverage on the first
  test execution**—no reruns.
- For documentation changes, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; see
    [`.spellcheck.yaml`](../.spellcheck.yaml))
  - `linkchecker --no-warnings README.md docs/`
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`.
- Record recurring issues in [`outages/`](../outages/) using the
  [`schema.json`](../outages/schema.json).

REQUEST:
1. Choose a markdown file in `docs/` that needs clarification or an update.
2. Improve wording, fix links, or add missing steps.
3. Re-run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`,
   `linkchecker --no-warnings README.md docs/`, and
   `git diff --cached | ./scripts/scan-secrets.py`. Confirm all checks pass with 100% patch
   coverage on the first attempt.
   If `package.json` exists, also run:
   - `npm ci`
   - `npm run lint`
   - `npm run test:ci`
   Confirm all checks pass with 100% patch coverage on the first run.

OUTPUT:
A pull request with the refined documentation and passing checks.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
Run `pre-commit run --all-files` (invokes [`scripts/checks.sh`](../scripts/checks.sh) for
linting, formatting, and tests; it automatically runs `npm ci`, `npm run lint`, and
`npm run test:ci` when `package.json` exists). Then run `pyspelling -c .spellcheck.yaml`
(requires `aspell` and `aspell-en`; see [`.spellcheck.yaml`](../.spellcheck.yaml)),
`linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.
- Ensure the refreshed prompt explicitly directs contributors to deliver **100% patch coverage on
  the first test run** without retries.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Add or reinforce guidance requiring 100% patch coverage on the first test execution.
4. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
