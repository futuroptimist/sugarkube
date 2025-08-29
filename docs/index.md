# Sugarkube

Welcome to **sugarkube**, a solar-powered off-grid platform for Raspberry Pis and aquarium aeration.
This repo tracks CAD models, electronics schematics, and documentation
so anyone can replicate the setup.
Greenery is encouraged around the cube. Vines can climb the extrusion while
herbs and shade-loving plants enjoy the cover of the solar panels.

![solar cube](images/solar_cube.jpg)

## Getting Started
Review the safety notes before working with power components.

- [SAFETY.md](SAFETY.md) — wiring and battery safety guidelines
- [build_guide.md](build_guide.md) — step-by-step assembly instructions
- [pi_cluster_carrier.md](pi_cluster_carrier.md) — details on the Raspberry Pi mounting plate
- [lcd_mount.md](lcd_mount.md) — optional 1602 LCD placement
- [insert_basics.md](insert_basics.md) — heat-set inserts and printed threads
- [network_setup.md](network_setup.md) — connect the cluster to your network
- [pi_image.md](pi_image.md) — build a minimal k3s-ready Raspberry Pi image
- [raspi_cluster_setup.md](raspi_cluster_setup.md) — build a three-node k3s cluster and deploy apps
- [docker_repo_walkthrough.md](docker_repo_walkthrough.md) — deploy any Docker-based repo

## Learn the Fundamentals
- [solar_basics.md](solar_basics.md) — how photovoltaic panels work
- [electronics_basics.md](electronics_basics.md) — wiring, tools, and safety
- [power_system_design.md](power_system_design.md) — sizing batteries and choosing a
  charge controller

Start with the basics and progress toward a fully autonomous solar cube.

## LLM Prompts
- [prompts-codex.md](prompts-codex.md) — baseline Codex instructions for maintaining the repo
- [prompts-codex-cad.md](prompts-codex-cad.md) — keep OpenSCAD models rendering cleanly
- [prompts-codex-docs.md](prompts-codex-docs.md) — refine build guides and reference docs
- [prompts-codex-pi-image.md](prompts-codex-pi-image.md) — maintain the Pi image tooling
- [prompts-codex-docker-repo.md](prompts-codex-docker-repo.md) — improve Docker repo guides
- [prompts-codex-ci-fix.md](prompts-codex-ci-fix.md) — diagnose and fix failing checks
- [prompts-codex-spellcheck.md](prompts-codex-spellcheck.md) — correct spelling in docs
