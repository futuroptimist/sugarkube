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
- Docs live in [`docs/`](../docs/).
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for style,
  testing, and repository conventions.
- Run `pre-commit run --all-files` to invoke [`scripts/checks.sh`](../scripts/checks.sh) for
  linting, formatting, and tests.
- If a Node toolchain is present (`package.json` exists), also run:
  - `npm ci`
  - `npm run lint`
  - `npm run test:ci`
- For documentation changes, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`.
- Record recurring issues in [`outages/`](../outages/) using the
  [`schema.json`](../outages/schema.json).

REQUEST:
1. Choose a markdown file in `docs/` that needs clarification or an update.
2. Improve wording, fix links, or add missing steps.
3. Re-run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`,
   `linkchecker --no-warnings README.md docs/`, and
   `git diff --cached | ./scripts/scan-secrets.py`.
   If `package.json` exists, also run:
   - `npm ci`
   - `npm run lint`
   - `npm run test:ci`
   Confirm all checks pass.

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
Run `pre-commit run --all-files`.
If a Node toolchain exists, also run:
- `npm ci`
- `npm run lint`
- `npm run test:ci`
Then run `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; see
[`.spellcheck.yaml`](../.spellcheck.yaml)), `linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
