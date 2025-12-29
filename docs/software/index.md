---
personas:
  - software
---

# Sugarkube Software Index

Navigate software automation, release tooling, and operations guides from a
single hub. Each section links back to the docs that explain how the Pi image
and supporting services stay healthy.

## Shared Fundamentals
- [Sugarkube Fundamentals](../fundamentals/index.md) — keep core concepts fresh
  so automation guides can skip repeated primers.

## Image Tooling
- [pi_image_quickstart.md](../pi_image_quickstart.md) — build, flash, and verify the
  published image.
- [pi_image_builder_design.md](../pi_image_builder_design.md) — architecture of the
  pi-gen workflow and CI release jobs.
- [pi_image_contributor_guide.md](../pi_image_contributor_guide.md) — map scripts
  to the docs they power.

## Automation and Monitoring
- [pi_smoke_test.md](../pi_smoke_test.md) — remote verifier runs and reporting
  formats.
- [pi_image_team_notifications.md](../pi_image_team_notifications.md) — Slack and
  Matrix boot/migration alerts.
- [pi_image_telemetry.md](../pi_image_telemetry.md) — opt-in health reporting for
  fleet dashboards.

## Operations Playbooks
- [pi_carrier_launch_playbook.md](../pi_carrier_launch_playbook.md) — end-to-end
  rollout covering hardware prep through k3s readiness.
- [Pi Support Bundles](../pi_support_bundles.md) — collect evidence for
  debugging.
- [apps/tokenplace-relay.md](../apps/tokenplace-relay.md) — operate the
  token.place relay deployment on Sugarkube.
- [operations/security-checklist.md](../operations/security-checklist.md) — record
  credential rotations and post-maintenance evidence.
- [projects-compose.md](../projects-compose.md) — run token.place and dspace via
  Docker Compose.
- [pi_token_dspace.md](../pi_token_dspace.md) — expose token.place/dspace through
  Cloudflare tunnels.

## Developer Workflow
- [contributor_script_map.md](../contributor_script_map.md) — keep automation docs
  aligned with helper scripts.
- [prompts/codex/tests.md](../prompts/codex/tests.md) — expectations for growing
  test coverage.
- [simplification_suggestions.md](../simplification_suggestions.md) — backlog of
  DX improvements and persona-aware initiatives.
