---
title: 'Sugarkube Codex Docker Repo Prompt'
slug: 'prompts-codex-docker-repo'
---

# Codex Docker Repo Prompt

Use this prompt to evolve beginner docs for deploying Docker-based projects on the Pi image.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Write step-by-step instructions for running a GitHub repo that includes a
Dockerfile or Docker Compose file (`docker-compose.yml` or `compose.yaml`) on the
prepared Raspberry Pi image.

CONTEXT:
- The base image and tunnel setup live in [`pi_image_cloudflare.md`](./pi_image_cloudflare.md).
- New walkthroughs belong in [`docker_repo_walkthrough.md`](./docker_repo_walkthrough.md).
- Run `pre-commit run --all-files` to lint, format, and test.
- If `package.json` exists, also run:
  - `npm ci`
  - `npm run lint`
  - `npm run test:ci`
- For documentation updates, run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`.
- File recurring deployment failures in [`outages/`](../outages/) per
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Expand the walkthrough or add examples.
2. Reference token.place and dspace where helpful.
3. Verify all commands and links.

OUTPUT:
A pull request with passing checks and a concise summary.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
Run `pre-commit run --all-files`, `pyspelling -c .spellcheck.yaml` (requires
`aspell` and `aspell-en`), `linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
