# 🤖 AGENTS

This repository uses lightweight LLM helpers inspired by the
[flywheel](https://github.com/futuroptimist/flywheel) project. It follows the
[AGENTS.md specification](https://agentsmd.net/AGENTS.md), mirroring
[the original gist](https://gist.github.com/dpaluy/cc42d59243b0999c1b3f9cf60dfd3be6).

The name **sugarkube** has two meanings:

1. The physical aluminium cube with solar panels that houses a Pi-based k3s
   cluster.
   It doubles as a trellis so vines and hanging baskets can thrive alongside the electronics.
2. "Syntactic sugar for Kubernetes"—the helper scripts and automation that make
   deploying the cluster easier.

## Code Linter Agent
- **When:** every PR
- **Does:** run `pre-commit run --all-files` (invokes `scripts/checks.sh`) to lint, format and test.

## Docs Agent
- **When:** documentation or README change
- **Does:** run `pyspelling -c .spellcheck.yaml` and
  `linkchecker --no-warnings README.md docs/` to validate docs. This covers guides
  such as `docs/network_setup.md`.

## CAD Agent
- **When:** `.scad` files change
- **Does:**
  1. Render each SCAD in `heatset` and `printed` modes.
  2. Export `*.stl` meshes as workflow artifacts (not committed).
  3. Fail if compilation or regeneration fails.

## KiCad Agent
- **When:** KiCad schematic or PCB files change and on a weekly schedule
- **Does:** run the [KiBot action](https://github.com/INTI-CMNB/kibot) with
  `.kibot/power_ring.yaml` to export Gerbers, PDF schematics and BOM. The project
  requires **KiCad 9** so we use the `v2_k9` container tag.
- **Logs:** workflow logs are uploaded as artifacts so non-admins can download failure details.

## Outage Agent
- **When:** a script or workflow fails repeatedly
- **Does:** add a JSON record under `outages/` using `schema.json` describing the
  root cause and resolution.
- **Date source:** determine the outage date with a reliable clock (`curl -fsS
  https://worldtimeapi.org/api/timezone/Etc/UTC | jq -r '.utc_datetime'` or,
  if offline, `date -u +%F`). Use that value for both the `date` field and the
  filename prefix, and verify the entry with `git blame` before committing so
  regressions never drift into the future again.

### STL generation
STL meshes are not stored in the repository. The `scad-to-stl.yml` workflow renders
them after each commit and exposes the files as downloadable artifacts.

### Development workflow
Run the following before committing:

```bash
pre-commit run --all-files
pyspelling -c .spellcheck.yaml
linkchecker --no-warnings README.md docs/
git diff --cached | ./scripts/scan-secrets.py
```
