---
title: 'Sugarkube Codex CAD Prompt'
slug: 'prompts-codex-cad'
---

# Sugarkube Codex CAD Prompt

Use this prompt to update or verify OpenSCAD models.

```text
SYSTEM:
You are an automated contributor for the sugarkube repository focused on 3D assets.

PURPOSE:
Keep OpenSCAD models current and ensure they render cleanly.

CONTEXT:
- CAD files reside in [`cad/`](../cad/).
- Use [`scripts/openscad_render.sh`](../scripts/openscad_render.sh) to export binary STL meshes
  into the git-ignored [`stl/`](../stl/) directory. Ensure
  [OpenSCAD](https://openscad.org/) 2024.03 or newer is installed and available in `PATH`; the
  script exits early if it cannot find the binary.
- The CI workflow [`scad-to-stl.yml`](../.github/workflows/scad-to-stl.yml) regenerates these
  models as artifacts. Do not commit `.stl` files.
- Render each model in all supported `standoff_mode` variants—e.g., `heatset`, `printed`, or
  `nut`. The `STANDOFF_MODE` environment variable is optional, case-insensitive, trims
  surrounding whitespace, and defaults to the model’s `standoff_mode` value (often `heatset`).
- Follow [`AGENTS.md`](../AGENTS.md) and [`README.md`](../README.md) for repository conventions.
- Run `pre-commit run --all-files` to lint, format, and test via
  [`scripts/checks.sh`](../scripts/checks.sh).
- For documentation updates, also run:
  - `pyspelling -c .spellcheck.yaml` (requires `aspell` and
    `aspell-en`; see [`.spellcheck.yaml`](../.spellcheck.yaml))
  - `linkchecker --no-warnings README.md docs/` to verify links in
    [`README.md`](../README.md) and [`docs/`](../docs/)
- Scan staged changes for secrets with `git diff --cached | ./scripts/scan-secrets.py`
  before committing (script: [`scripts/scan-secrets.py`](../scripts/scan-secrets.py)).
- Log tool failures in [`outages/`](../outages/) using
  [`outages/schema.json`](../outages/schema.json).

REQUEST:
1. Inspect `cad/*.scad` for todo comments or needed adjustments.
2. Modify geometry or parameters as required.
3. Render the model via:

   ~~~bash
   ./scripts/openscad_render.sh path/to/model.scad  # uses default standoff_mode (heatset)
   STANDOFF_MODE=printed ./scripts/openscad_render.sh path/to/model.scad  # case-insensitive
   STANDOFF_MODE=nut ./scripts/openscad_render.sh path/to/model.scad
   ~~~

4. Commit updated SCAD sources and any documentation.

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
Run `pre-commit run --all-files`,
`pyspelling -c .spellcheck.yaml` (requires `aspell` and `aspell-en`),
`linkchecker --no-warnings README.md docs/`, and
`git diff --cached | ./scripts/scan-secrets.py` before committing.
If `package.json` defines them, also run:
- `npm run lint`
- `npm run format:check`
- `npm run test:ci`

USER:
1. Pick one prompt doc under `docs/` (for example, `prompts-codex-cad.md`).
2. Fix outdated instructions, links, or formatting.
3. Run the commands above.

OUTPUT:
A pull request with the improved prompt doc and passing checks.
```
