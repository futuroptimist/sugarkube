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
- Run `pyspelling -c .spellcheck.yaml` to scan `README.md` and `docs/`.
- Add legitimate new words to `.wordlist.txt`.
- Follow AGENTS.md and run `pre-commit run --all-files`; ensure `linkchecker --no-warnings README.md docs/` also passes.

REQUEST:
1. Run the spellcheck and review results.
2. Fix misspellings or update `.wordlist.txt`.
3. Re-run spellcheck and link checks until clean.

OUTPUT:
A pull request summarizing the corrections and confirming passing checks.
```
