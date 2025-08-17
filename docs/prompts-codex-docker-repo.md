---
title: 'Sugarkube Codex Docker Repo Prompt'
slug: 'prompts-codex-docker-repo'
---

# Codex Docker Repo Prompt

Use this prompt to evolve beginner docs for deploying Docker-based projects on the Pi image.

```
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Write step-by-step instructions for running a GitHub repo that includes a
Dockerfile or docker-compose file on the prepared Raspberry Pi image.

CONTEXT:
- The base image and tunnel setup live in `docs/pi_image_cloudflare.md`.
- New walkthroughs belong in `docs/docker_repo_walkthrough.md`.
- Run `pre-commit run --all-files`; ensure `pyspelling` and `linkchecker` pass.

REQUEST:
1. Expand the walkthrough or add examples.
2. Reference token.place and dspace where helpful.
3. Verify all commands and links.

OUTPUT:
A pull request with passing checks and a concise summary.
```
