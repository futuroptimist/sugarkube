---
title: 'Sugarkube Codex Pi Image Prompt'
slug: 'prompts-codex-pi-image'
---

# Codex Pi Image Prompt

Use this prompt to evolve the Raspberry Pi OS image and Cloudflare tunnel setup.

```
SYSTEM:
You are an automated contributor for the sugarkube repository.

PURPOSE:
Improve the Pi image build tooling and deployment docs.

CONTEXT:
- Cloud-init config lives under `scripts/cloud-init/`.
- `scripts/build_pi_image.sh` builds an image locally or in CI.
- `docs/pi_image_cloudflare.md` is the user guide.
- Run `pre-commit run --all-files`; ensure `pyspelling` and `linkchecker` pass.
- Document persistent build issues in `outages/` using the schema.

REQUEST:
1. Refine the image build script or cloud-init files.
2. Update relevant documentation.
3. Run `pre-commit run --all-files` and confirm success.

OUTPUT:
A pull request with passing checks and a concise summary.
```
