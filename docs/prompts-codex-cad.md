---
title: 'Sugarkube Codex CAD Prompt'
slug: 'prompts-codex-cad'
---

# Sugarkube Codex CAD Prompt

Use this prompt to update or verify [OpenSCAD](https://openscad.org) models.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on 3D assets.

PURPOSE:
Keep OpenSCAD models current and ensure they render cleanly.

CONTEXT:
- CAD files reside in [`cad/`](../cad/).
- [`scripts/openscad_render.sh`](../scripts/openscad_render.sh) wraps
  `openscad -o stl/... --export-format binstl`. Run it from the repository root so meshes land
  in the git-ignored [`stl/`](../stl/) directory (see [`.gitignore`](../.gitignore)). Ensure
  [OpenSCAD](https://openscad.org/) is installed and available on `PATH`; the script exits
  early if the binary is missing.
- The CI workflow [`scad-to-stl.yml`](../.github/workflows/scad-to-stl.yml) regenerates these
  models as artifacts. Do not commit `.stl` files.
- Render each model in all supported `standoff_mode` variants—e.g., `heatset`, `printed`,
  or `nut`. `STANDOFF_MODE` is optional; the script normalizes the value
  (case-insensitive, trims whitespace) and defaults to the model’s `standoff_mode`
  value (often `heatset`). Invalid values cause the render script to exit with an error.
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md); see the
  [AGENTS.md spec](https://agentsmd.net/) for instruction semantics.
- Inspect [`.github/workflows/`](../.github/workflows/) to see which checks run in CI.
- Run `pre-commit run --all-files` from the repository root to lint, format, and test via
  [`scripts/checks.sh`](../scripts/checks.sh).
- If `package.json` defines them, run:
  - `npm ci`
  - `npm run lint`
  - `npm run format:check`
  - `npm test -- --coverage`
- For documentation updates, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; see
    [`.spellcheck.yaml`](../.spellcheck.yaml))
  - `linkchecker --no-warnings README.md docs/` to verify links in
    [`README.md`](../README.md) and [`docs/`](../docs/) (install via `pip install linkchecker`)
- Scan staged changes for secrets before committing using
  `git diff --cached | ./scripts/scan-secrets.py`.
- Log tool failures in [`outages/`](../outages/) using
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Inspect `cad/*.scad` for todo comments or needed adjustments.
2. Modify geometry or parameters as required.
3. Render the model via (use `~~~` fences in this prompt to avoid breaking the outer block):
   ~~~bash
   ./scripts/openscad_render.sh path/to/model.scad  # default standoff_mode (model-defined, often heatset)
   STANDOFF_MODE=printed ./scripts/openscad_render.sh path/to/model.scad  # case-insensitive
   STANDOFF_MODE=nut ./scripts/openscad_render.sh path/to/model.scad
   ~~~
   ````

4. Run `pre-commit run --all-files`; for docs changes also run
   `pyspelling -c .spellcheck.yaml` and `linkchecker --no-warnings README.md docs/`.
5. Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`
   before committing updated SCAD sources and any documentation.

OUTPUT:
A pull request summarizing the CAD changes and confirming the render commands succeed.
```

## Upgrade Prompt
Type: evergreen

Use this prompt to refine sugarkube's own prompt documentation.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository.
Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md).
Run `pre-commit run --all-files`.

If `package.json` exists, also run:

- `npm ci`
- `npm run lint`
- `npm run format:check`
- `npm test -- --coverage`

 Then run:

- `pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`; see
  [`.spellcheck.yaml`](../.spellcheck.yaml))
- `linkchecker --no-warnings README.md docs/` (installed by
  [`scripts/checks.sh`](../scripts/checks.sh))
- `git diff --cached | ./scripts/scan-secrets.py` before committing.

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
