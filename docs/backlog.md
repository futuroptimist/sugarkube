# Sugarkube Backlog

The comprehensive Pi image improvement checklist now lives in [`docs/archived/pi_image_improvement_checklist.md`](./archived/pi_image_improvement_checklist.md).
This backlog captures the remaining high-effort work that still requires dedicated time, specialized
hardware, or multimedia production. Each section is written so it can be linked directly from a
GitHub issue when we are ready to tackle that initiative.

## Hardware-in-the-Loop Test Bench

We still need a fully automated validation rig that can exercise real Raspberry Pi hardware. The
bench should combine a USB-controllable PDU for power cycling, HDMI capture so we can archive boot
output, and a serial console for kernel logs. It must orchestrate image flashing, boot verification,
telemetry collection, and regression reporting so nightly builds prove the cluster survives real
world reboots. Capturing wiring diagrams, bill of materials, and control software (likely a Python
harness that drives the PDU, capture card, and USB-UART) is essential so contributors can reproduce
the setup in other labs. Success criteria include publishing captured logs as CI artifacts and
raising automated GitHub issues when a build fails physical validation.

## End-to-End Walkthrough Media

The written guides are complete, but the docs still lack narrated visuals that demonstrate the full
journey from download to k3s readiness. We need a script, screen captures, and optionally voiceover
that cover every milestone: grabbing the latest release, flashing removable media, first boot
validation, SSD migration, verifier runs, and post-clone health checks. The production plan should
include tooling choices (e.g., OBS, ffmpeg, or Descript), storage for raw footage, and an editing
workflow that keeps future refreshes efficient. Deliverables are GIFs for quick-start embeds, a full
narrated demo hosted on a streaming platform, and short clips that can be sprinkled throughout
playbooks for contextual help.

## Golden Recovery Console Image

Operators still need a fall-back environment they can boot when a cluster becomes unrecoverable. The
goal is to publish a lightweight rescue image or partition that bundles reflashing utilities,
network diagnostics, kubeconfig retrieval helpers, and shortcuts for reinstalling k3s. Scoping this
project involves defining supported hardware, ensuring secure defaults (no embedded secrets), and
writing automation to build and release the artifact alongside the primary Pi image. Documentation
must explain how to switch into the rescue environment, capture support bundles, and return to a
healthy state once repairs are complete.
