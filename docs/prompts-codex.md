---
title: 'Sugarkube Codex Prompt'
slug: 'prompts-codex'
---

# Codex Automation Prompt

Use this prompt to guide OpenAI Codex or similar agents when contributing to
this repository.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Keep the project healthy by making small, well-tested improvements.

CONTEXT:
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
- Run `pre-commit run --all-files` to invoke [`scripts/checks.sh`](../scripts/checks.sh) for
  linting, tests and doc validation.
- On documentation changes ensure `pyspelling -c [.spellcheck.yaml](../.spellcheck.yaml)`
  (requires `aspell` and `aspell-en`) and `linkchecker --no-warnings README.md docs/`
  succeed.
- Scan staged changes for secrets with `git diff --cached |` [`./scripts/scan-secrets.py`](../scripts/scan-secrets.py)
  before committing.
- Log persistent failures in [`outages/`](../outages/) as JSON per
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Identify a small bug fix or documentation clarification.
2. Implement the change following the project's existing style.
3. Update relevant documentation when needed.
4. Run `pre-commit run --all-files` after changes.

OUTPUT:
A pull request describing the change and summarizing test results.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
Run `pre-commit run --all-files`, `pyspelling -c` [`.spellcheck.yaml`](../.spellcheck.yaml)
(requires `aspell` and `aspell-en`), `linkchecker --no-warnings README.md docs/`, and
`git diff --cached |` [`./scripts/scan-secrets.py`](../scripts/scan-secrets.py) before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
