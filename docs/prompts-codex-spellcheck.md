---
title: 'Sugarkube Codex Spellcheck Prompt'
slug: 'prompts-codex-spellcheck'
---

# Codex Spellcheck Prompt

Use this prompt to catch and correct spelling issues in Markdown docs.

```
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Keep Markdown documentation free of spelling errors.

CONTEXT:
- Run `pyspelling -c .spellcheck.yaml` to scan `README.md` and `docs/`
  (requires `aspell` and `aspell-en`).
- Add legitimate new words to [`.wordlist.txt`](../.wordlist.txt).
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
- Run `pre-commit run --all-files` and `linkchecker --no-warnings README.md docs/`.
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`.

REQUEST:
1. Run the spellcheck and review results.
2. Fix misspellings or update `.wordlist.txt`.
3. Re-run spellcheck and link checks until clean.

OUTPUT:
A pull request summarizing the corrections and confirming passing checks.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow `AGENTS.md` and `README.md`.
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml`, and
`linkchecker --no-warnings README.md docs/` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
