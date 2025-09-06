---
title: 'Sugarkube Codex Pi token.place & dspace Prompt'
slug: 'prompts-codex-pi-token-dspace'
---

# Codex Pi token.place & dspace Prompt

Use this prompt to streamline building a Raspberry Pi 5 image that hosts
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) via
[Docker Compose](https://docs.docker.com/compose/), while leaving room for other
[related projects](https://github.com/futuroptimist#related-projects).

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Reduce the end-to-end steps to build and deploy a Pi image ready for
`token.place` and `dspace`, leaving extension points for future repos.

CONTEXT:
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for workflow
  guidelines.
- Raspberry Pi OS build script: [`scripts/build_pi_image.sh`](../scripts/build_pi_image.sh)
  (targets Raspberry Pi OS Bookworm 64‑bit).
- Docker Engine setup: follow [Docker's Debian install guide](https://docs.docker.com/engine/install/debian/)
  for ARM devices.
- First-boot cloud-init configs: [`scripts/cloud-init/`](../scripts/cloud-init/).
- Upstream apps:
  - [token.place](https://github.com/futuroptimist/token.place) — see its
    [README](https://github.com/futuroptimist/token.place#readme) for service details.
  - [dspace](https://github.com/democratizedspace/dspace) — see its
    [README](https://github.com/democratizedspace/dspace#readme).
- Existing Pi image prompt: [`prompts-codex-pi-image.md`](./prompts-codex-pi-image.md).
- Repository checks:
  - `pre-commit run --all-files` (executes [`scripts/checks.sh`](../scripts/checks.sh))
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`)
  - `linkchecker --no-warnings README.md docs/`
  - `git diff --cached | ./scripts/scan-secrets.py`
- Review [CI workflows](../.github/workflows/) to anticipate automated checks.

REQUEST:
1. Add or refine scripts and docs so `token.place` and `dspace` run as services on the Pi
   image via `docker-compose.yml`.
2. Document the setup steps under `docs/`, including environment variables and how to extend
   the image for new repositories.
3. Keep hooks for adding other repositories later.
4. Run the commands above and confirm success.

OUTPUT:
A pull request with updated scripts and docs enabling `token.place` and
`dspace` on a Pi 5 image with passing checks.
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
1. Improve this prompt by clarifying context, links, or instructions.
2. Ensure references stay current.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
