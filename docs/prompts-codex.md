---
title: 'Sugarkube Codex Prompt'
slug: 'prompts-codex'
---

# Codex Automation Prompt

Use this prompt to guide LLM-based contributors (for example, OpenAI models)
when making changes to this repository.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Keep the project healthy by making small, well-tested improvements.

CONTEXT:
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md); for
  instruction semantics see the [AGENTS.md spec](https://agentsmd.net/).
- Run `pre-commit run --all-files`, which executes
  [`scripts/checks.sh`](../scripts/checks.sh) to install tooling and run
  linters, tests, and documentation checks.
- If a Node toolchain is present (`package.json` exists), also run:
  - `npm ci`
  - `npm run lint`
  - `npm run test:ci`
- When documentation files (`README.md` or anything under
  [`docs/`](../docs/)) change, additionally run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
- Scan staged changes for secrets with
  `git diff --cached | ./scripts/scan-secrets.py` before committing.
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
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md); for
instruction semantics see the [AGENTS.md spec](https://agentsmd.net/).
Run `pre-commit run --all-files` (invokes
[`scripts/checks.sh`](../scripts/checks.sh) to install tooling and run linters
and tests). If a Node toolchain is present (`package.json` exists), also run:
- `npm ci`
- `npm run lint`
- `npm run test:ci`
Then run:
- `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
- `linkchecker --no-warnings README.md docs/`
- `git diff --cached | ./scripts/scan-secrets.py`
Fix any issues reported by these tools.

USER:
1. Choose a `docs/prompts-*.md` file to update (for example, `prompts-codex-cad.md`).
2. Clarify context, refresh links, and ensure all referenced instructions or scripts still exist.
3. Run the commands above and address any failures.

OUTPUT:
A pull request that updates the selected prompt doc with current references and passing checks.
```
