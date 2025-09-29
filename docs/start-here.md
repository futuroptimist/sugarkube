# Start Here

Kick off your Sugarkube journey from a single launchpad. This guide condenses the repository into
three tracks so you can build context quickly, complete the onboarding chores, and know where to dive
when you are ready for deeper automation or hardware projects.

## Persona quick links

Use the tabs below to jump straight to the references that match how you plan to contribute today.
Each list links to maintained guides and tooling so you can gather context without guessing which
docs apply to you.

=== "Hardware builders"

    - Print the [Pi carrier launch playbook](./pi_carrier_launch_playbook.md) to prepare the enclosure
      build, wiring harness, and solar checks.
    - Stage the [hardware index](./hardware/index.md) for diagrams, bill of materials, and safety
      notes before you open a toolkit.
    - Bookmark [tutorial 6](./tutorials/tutorial-06-raspberry-pi-hardware-power.md) to rehearse power
      budgeting and enclosure assembly.
    - Keep [docs/ssd_recovery.md](./ssd_recovery.md) handy for contingency plans when a boot device
      misbehaves during testing.

=== "Software contributors"

    - Start with the [software index](./software/index.md) for quick access to automation guides and
      helper scripts.
    - Review [docs/pi_image_quickstart.md](./pi_image_quickstart.md) to understand the build pipeline
      before you edit cloud-init or verifier hooks.
    - Practice the contribution workflow by following
      [tutorial 12](./tutorials/tutorial-12-contributing-new-features-automation.md).
    - Skim [docs/prompts/codex/tests.md](./prompts/codex/tests.md) so you know which checks run in CI
      and how to extend regression coverage.

## 15-minute tour

> [!TIP]
> Run `just start-here` (or `make start-here`) to print this handbook directly in your terminal.
> Append `--path-only` to either command when you simply need the absolute path for note-taking or automation evidence.
> Skim this track the moment you clone the repository. It orients you before you touch any
> automation.

1. Read the project overview in [README.md](../README.md) to learn what "Sugarkube" means in both the
   hardware and automation contexts.
2. Flip through the curated sitemap in [docs/index.md](./index.md) for a directory-first view of the
   guides.
3. Visit the [tutorial roadmap](./tutorials/index.md) to see how the hands-on series is structured and
   which artefacts each tutorial expects.
4. Check the [status dashboards](./status/README.md) so you know the latest hardware boot date and the
   ergonomics metrics we track.

## Day-one contributor checklist

> [!IMPORTANT]
> Budget a focused afternoon to work through these steps. They line up with Tutorials 1–4 and leave
> you with verified tooling plus a pull request rehearsal.

1. Run either `just codespaces-bootstrap` or `make codespaces-bootstrap` to install the Python, spell
   check, and link check prerequisites wired into `pre-commit`.
2. Execute `pre-commit run --all-files` once locally; it shells into `scripts/checks.sh` so you see
   the full lint, test, and docs pipeline.
3. Follow the first four tutorials in [docs/tutorials/index.md](./tutorials/index.md) to capture lab
   notes, network sketches, and your first automation exercise.
4. Use [docs/pi_image_quickstart.md](./pi_image_quickstart.md) as a dry-run reference while you learn
   the build workflow—no hardware required yet.
5. Map helper scripts to their docs using [docs/pi_image_contributor_guide.md](./pi_image_contributor_guide.md)
   so you can discover relevant guides quickly.

## Advanced references

> [!NOTE]
> Graduate to these once you are comfortable contributing code or maintaining the physical cube.

- Bookmark the full hardware launch process in [docs/pi_carrier_launch_playbook.md](./pi_carrier_launch_playbook.md).
- Study the observability hooks documented in [docs/pi_image_telemetry.md](./pi_image_telemetry.md) before
  enabling telemetry or extending Grafana dashboards.
- Rehearse the recovery flows under [docs/ssd_recovery.md](./ssd_recovery.md) and
  [docs/ssd_post_clone_validation.md](./ssd_post_clone_validation.md) so maintenance windows stay calm.
- Use [docs/contributor_script_map.md](./contributor_script_map.md) and the changelog to keep up with new helpers.
- Track simplification and roadmap proposals in [simplification_suggestions.md](../simplification_suggestions.md)
  when you are ready to staff improvements.

Each section references existing, maintained guides so newcomers have an immediate, documented path
from first clone to confident contributions.
