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
- Follow AGENTS.md for style and testing requirements.
- Run `pre-commit run --all-files`; ensure `pyspelling` and `linkchecker`
  succeed.

REQUEST:
1. Choose a markdown file in `docs/` that needs clarification or an update.
2. Improve wording, fix links, or add missing steps.
3. Re-run `pre-commit run --all-files` and confirm no errors.

OUTPUT:
A pull request with the refined documentation and passing checks.
```
