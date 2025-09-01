---
title: 'Sugarkube Codex Docs Prompt'
slug: 'prompts-codex-docs'
---

# Codex Documentation Prompt

Use this prompt to refine build guides and reference material.

```
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Keep the documentation clear and accurate.

CONTEXT:
- Docs live in `docs/`.
- Follow [AGENTS.md](../AGENTS.md) for style and testing requirements.
- Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`, and
  `linkchecker --no-warnings README.md docs/` (requires `aspell` and `aspell-en`).
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`.
- Record recurring issues in `outages/` using the JSON schema.

REQUEST:
1. Choose a markdown file in `docs/` that needs clarification or an update.
2. Improve wording, fix links, or add missing steps.
3. Re-run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`,
   `linkchecker --no-warnings README.md docs/`, and
   `git diff --cached | ./scripts/scan-secrets.py`, confirming success.

OUTPUT:
A pull request with the refined documentation and passing checks.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow `AGENTS.md` and `README.md`.
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`,
`linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
