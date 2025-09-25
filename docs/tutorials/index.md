# Sugarkube Tutorial Roadmap

Sugarkube combines hardware, software, and operational practices into a cohesive home-lab scale
platform. This roadmap outlines the tutorials we plan to write, sequenced so a newcomer with no prior
technical background can progress from first principles to confidently maintaining and extending the
platform. Each entry will eventually become its own standalone guide; for now, the descriptions below
capture the narrative arc, learning goals, and practical exercises we intend to include.

Throughout the series we keep our eye on the real-world goal: installing the aluminium extrusion
Sugarkube cube in an outdoor setting (like a backyard pergola), wiring its solar array and charge
controller, and mounting the fully populated 3D-printed Pi carrier. Every tutorial reinforces a piece
of that deployment so learners finish the sequence ready to assemble, power, and operate the
solar-backed cluster with confidence.

## Tutorial 1: Computing Foundations Without Jargon

**Status:** Published — [Read the tutorial](./tutorial-01-computing-foundations.md)

**Prerequisites satisfied:** None. Bring curiosity and a Raspberry Pi (or diagram) to explore.

We start by explaining the core ideas behind computers—what a CPU, memory, and storage device do—and
how those pieces collaborate to run everyday applications. The tutorial relies on real-world
analogies rather than acronyms, making sure readers feel comfortable with concepts like files,
processes, and networks. Hands-on moments include exploring a Raspberry Pi diagram and identifying
each component, setting expectations for how delicate hardware should be handled, and highlighting
basic electrical safety tips before we ever plug anything in.

The second half introduces operating systems at a conceptual level. We will cover why Linux is a good
fit for Sugarkube, what distinguishes it from Windows or macOS, and how the command line empowers
automation. Readers will perform a guided exercise using an online Linux sandbox to navigate
directories, run simple commands, and begin building muscle memory with shell prompts.

### Milestones

1. Tour real hardware: label Pi components, document safety notes, and assemble a static-safe
   workstation.
2. Practice in a browser sandbox: run file inspection commands, create directories, and capture the
   transcript for later reference.
3. Summarize key terms in a shared glossary so future tutorials can link to an agreed vocabulary.

## Tutorial 2: Navigating Linux and the Terminal

**Status:** Published — [Read the tutorial](./tutorial-02-navigating-linux-terminal.md)

**Prerequisites satisfied:** Tutorial 1 transcript and safety notes.

This tutorial deepens shell skills by introducing the filesystem hierarchy, package managers, and
text editors. We demystify permissions, explain why `sudo` needs to be respected, and teach problem
solving strategies like reading manual pages. Exercises walk learners through capturing a terminal
transcript with `script`, mapping critical directories, and taking structured notes for future
reference.

We close with scripting fundamentals. Readers write a Bash status reporter, compare interactive
commands with reusable scripts, and practice publishing their findings in Markdown so collaborators
can review their workflow.

### Milestones

1. Build a "day in the life" command map that documents filesystem, package, and editor workflows.
2. Complete a permissions troubleshooting lab where a mock service fails until modes and owners are
   corrected.
3. Script a reusable status report, publish it to a gist or repository, and request feedback from a
   peer.

## Tutorial 3: Networking and the Internet Basics

**Status:** Published — [Read the tutorial](./tutorial-03-networking-internet-basics.md)

**Prerequisites satisfied:** Tutorial 1 safety notes, Tutorial 2 terminal transcript, and access to a
home network you can document.

Sugarkube relies on reliable networking, so we dedicate a tutorial to the fundamentals. We introduce
IP addresses, DNS, routing, and ports, using diagrams that connect home router concepts to Kubernetes
services. Readers experiment with diagnostic tools like `ping`, `traceroute`, and `curl` against
public endpoints, learning how to interpret latency, packet loss, and HTTP status codes. We also plan
backhaul routes and wireless links for a backyard enclosure so the aluminium cube and its solar
instrumentation stay reachable without disrupting household bandwidth.

The second half bridges networking theory with Sugarkube needs. Learners review how Raspberry Pis
connect over Ethernet or Wi-Fi, how VLANs and subnets can segregate lab traffic, and what it means to
expose services securely. The tutorial sets expectations for the network configuration tasks they
perform in later guides, including firewall adjustments and static DHCP reservations.

### Milestones

1. Diagram a home network, annotate IP ranges, and mark where Sugarkube gear, the solar charge
   controller, and monitoring sensors will connect outdoors.
2. Run latency and bandwidth measurements between two devices (include the planned outdoor drop if
   possible), interpret results, and record them in a lab notebook.
3. Configure a sample firewall rule or router reservation in a simulator to cement networking
   vocabulary and secure remote management of the backyard enclosure.

## Tutorial 4: Version Control and Collaboration Fundamentals

**Status:** Published — [Read the tutorial](./tutorial-04-version-control-collaboration.md)

**Prerequisites satisfied:** Tutorial 1 safety notes, Tutorial 2 terminal transcript, and Tutorial 3
network topology diagram.

Before touching the Sugarkube repository, readers need to understand Git and GitHub. This tutorial
walks through initializing repositories, making commits, branching, and submitting pull requests. We
will emphasize commit hygiene, writing descriptive messages, and reviewing diffs with confidence.
Interactive labs will have learners fork a practice repo, open a documentation fix, and respond to
review feedback.

We also explain how Sugarkube uses automation bots, continuous integration, and the AGENTS.md
workflow. By the end, readers will know which checks to run locally, how to interpret CI failures, and
where to find contribution guidelines for both code and documentation changes—including the hardware
adjacent ones that cover the Pi carrier CAD files and solar harness wiring templates.

### Milestones

1. Fork and clone a sandbox repository, open a pull request, and request review from a partner.
2. Resolve a simulated merge conflict while keeping commit history clean and well described.
3. Document the CI workflow they executed, including which checks ran locally versus in the cloud.

## Tutorial 5: Programming for Operations with Python and Bash

**Status:** Published — [Read the tutorial](./tutorial-05-programming-for-operations.md)

**Prerequisites satisfied:** Tutorial 1 hardware notes, Tutorial 2 terminal transcript, Tutorial 3
network diagram, and Tutorial 4 Git practice repository.

With collaboration basics covered, we introduce lightweight programming tailored to Sugarkube scripts.
Learners build a fresh workspace, configure shell aliases, and create a Bash status collector that
captures real system metrics. They then write a Python wrapper that validates and formats the logs,
install `pre-commit`, and run unit tests to enforce quality from the start.

The tutorial emphasizes capturing artifacts—logs, screenshots, transcripts—so future maintainers can
review operational changes confidently. By the end, readers understand how to extend automation while
respecting Sugarkube's tooling expectations.

### Milestones

1. Instrument the Bash status collector with logging and archive multiple log files.
2. Capture rich-terminal output from the Python parser and export JSON reports.
3. Achieve clean `pytest` and `pre-commit` runs with transcripts saved for review.
4. Document troubleshooting steps or environment adjustments in the workspace README.
5. Share the lab repository or evidence bundle with a mentor for feedback.

## Tutorial 6: Raspberry Pi Hardware and Power Design

**Status:** Published — [Read the tutorial](./tutorial-06-raspberry-pi-hardware-power.md)

**Prerequisites satisfied:** Tutorials 1–5 artifacts (safety notes, terminal transcripts, network
diagram, Git workspace, and automation toolkit) plus access to the Sugarkube hardware kit.

This tutorial returns to hardware, giving a guided tour of the aluminium extrusion Sugarkube cube,
its solar-backed power regulation, and accessory boards. Readers will learn how to select microSD
cards and SSDs, identify compatible USB to serial adapters, and respect thermal and electrical
constraints. We will cover cable management, mounting considerations for the 3D-printed Pi carrier,
and best practices for handling ribbon cables and GPIO headers.

Hands-on sections will include assembling a mock Pi stack, dry-fitting the Pi carrier inside the cube
frame, routing both solar and auxiliary power through recommended hubs, and verifying voltage with a
multimeter. We will emphasize safety, documenting any optional tools or fixtures (like jig plates or
printed cable clips) that can simplify the build process for classroom or maker-space deployments.

### Milestones

1. Assemble the enclosure using a build checklist, mount the Pi carrier and solar combiner plate, and
   record a time-lapse or photo log for reference.
2. Perform voltage and continuity checks with a multimeter, logging expected versus measured values
   for both the solar charge controller and 5 V rail.
3. Stress-test thermal management with a controlled workload and document mitigation strategies for
   outdoor summer heat.

## Tutorial 7: Kubernetes and Container Fundamentals

**Status:** Published — [Read the tutorial](./tutorial-07-kubernetes-container-fundamentals.md)

**Prerequisites satisfied:** Tutorials 1–6 artefacts (safety notes, terminal transcript, network
diagram, Git workspace, automation toolkit, and validated hardware workspace) plus a workstation or
VM capable of running Docker or Podman.

Before tackling Sugarkube-specific automation, learners need to understand the orchestration layer.
The tutorial explains containers, images, pods, deployments, and services through a kind-based lab.
Readers deploy a sample application, scale it, and observe how Kubernetes maintains desired state.

The second half maps those ideas to Sugarkube. Learners customise a Helm chart, record rollout
evidence, and simulate pod failures to see reconciliation in action. Exercises emphasise creating a
lab evidence trail that mirrors Sugarkube's operational expectations.

### Milestones

1. Launch a local Kubernetes cluster, deploy a sample app, and scale it while observing pod churn.
2. Customise a Helm values file, upgrade the release, and capture before/after resource footprints.
3. Simulate a failure by deleting a pod and verifying self-healing while narrating the reconciliation
   loop.

## Tutorial 8: Preparing a Sugarkube Development Environment

**Status:** Published — [Read the tutorial](./tutorial-08-preparing-development-environment.md)

**Prerequisites satisfied:** Tutorials 1–7 artefacts (safety notes, transcripts, network diagram,
Git workspace, automation toolkit, validated hardware stack, and Kubernetes sandbox). Bring a
workstation with administrative access to install tooling.

Now that the foundational pieces are in place, we describe how to clone the repository, install
prerequisites, and run project automation locally. This tutorial guides readers through the
`justfile` and `Makefile`, demonstrates how to run `pre-commit`, and explains the purpose of each
script under `scripts/`. We also cover managing secrets using `.env` files, GitHub CLI
authentication, and the layout of build artifacts on disk.

To reinforce the workflow, learners perform a dry-run image download, execute the verifier in a
container, and interpret the resulting reports. The exercises highlight common pitfalls, like
stale virtual environments or missing system packages, and document troubleshooting steps.

### Milestones

1. Clone the repository, bootstrap tooling with `just` or `make`, and confirm all local checks pass.
2. Create a personal runbook describing credential management, secrets handling, and directory layout.
3. Record a screen-captured walkthrough that future contributors can replay while setting up.

## Tutorial 9: Building and Flashing the Sugarkube Pi Image

**Status:** Published — [Read the tutorial](./tutorial-09-building-flashing-pi-image.md)

**Prerequisites satisfied:** Tutorials 1–8 artefacts (safety notes, lab journals, network
diagram, Git workspace, automation toolkit, hardware build, Kubernetes sandbox, and local
development environment) plus access to Docker and at least 20 GB of free disk space.

This tutorial provides an end-to-end walkthrough of generating the Pi image. We will explain the
pi-gen stages we customize, how configuration overlays are applied, and where build metadata is
recorded. Learners will run the build locally or via GitHub Actions, monitor progress, and collect the
resulting artifacts for inspection.

With an image in hand, the guide transitions into flashing workflows. We will compare the CLI helper,
PowerShell wrapper, and Raspberry Pi Imager presets, ensuring readers know how to verify checksums and
handle common flashing errors. By the end, they will have a bootable SD card or SSD ready for the next
tutorial.

### Milestones

1. Execute a full image build, archive the artifacts, and summarize build metadata in a changelog.
2. Flash the image using two distinct methods, validate checksums, and log any deviations encountered.
3. Share a templated flashing checklist that can be reused by teammates or classroom cohorts.

## Tutorial 10: First Boot, Verification, and Self-Healing

**Status:** Published — [Read the tutorial](./tutorial-10-first-boot-verification-self-healing.md)

**Prerequisites satisfied:** Tutorials 1–9 artefacts (safety notes, lab journals, network diagram,
Git workspace, automation toolkit, hardware build, Kubernetes sandbox, development environment, and
bootable media) plus physical access to a Sugarkube Pi on a trusted network.

Here we detail what happens the first time a Sugarkube Pi boots. Learners will explore
`first_boot_service.py`, understand the generated reports, and practice interpreting logs under
`/boot/first-boot-report/`. Step-by-step exercises validate k3s readiness, confirm token.place and
dspace health, and trigger the self-healing services to see how automated recovery behaves when the
Pi sits inside the aluminium cube and rides on solar-backed power.

We also demonstrate retrieving kubeconfig and other artifacts over the network, showing how the
workflow supports classroom or remote deployments. Troubleshooting scenarios teach learners how to
respond when services fail, including cases where solar charge dips or outdoor cabling is disturbed,
encouraging them to gather support bundles before escalating issues.

### Milestones

1. Boot the Pi inside the cube, collect first-boot reports, and annotate them with commentary on
   expected behaviors plus solar charge readings.
2. Run the verification suite, remediate any failures, and track actions in an incident log (note if
   the solar charge controller triggered a restart).
3. Publish a resilience drill that intentionally restarts services, documents recovery timelines, and
   verifies loads resume cleanly after a solar-induced power cycle.

## Tutorial 11: Storage Migration and Long-Term Maintenance

**Status:** Published — [Read the tutorial](./tutorial-11-storage-migration-maintenance.md)

**Prerequisites satisfied:** Tutorials 1–10 artefacts (hardware notes, terminal transcripts, network
diagram, Git workspace, automation toolkit, validated hardware stack, Kubernetes sandbox, development
environment, bootable media, and first-boot verification evidence) plus the target SSD and USB bridge
from Tutorial 6.

This tutorial covers SSD cloning, validation, and rollback strategies. Readers execute the
`scripts/ssd_clone.py` helper, review generated reports, and run the health monitor to gauge drive
longevity. We cover backup strategies, log rotation, and proactive maintenance tasks like updating Helm
bundles or applying OS patches.

The second half focuses on automation. Learners capture SMART metrics, configure recurring backups,
and document a monthly maintenance routine so stakeholders can verify upkeep at a glance—including
inspecting solar charge logs, cleaning outdoor cabling, and checking the Pi carrier for weather wear.

### Milestones

1. Execute an SSD migration in a lab environment, validate clone integrity, and draft a rollback plan.
2. Configure backup jobs, verify restore procedures, and capture screenshots or logs as evidence.
3. Deploy observability hooks (logs, SMART, capacity) and test notification pathways end to end.

## Tutorial 12: Contributing New Features and Automation

**Status:** Published — [Read the tutorial](./tutorial-12-contributing-new-features-automation.md)

**Prerequisites satisfied:** Tutorials 1–11 artefacts (safety notes, terminal transcripts, network
diagram, Git workspace, automation toolkit, hardware stack, Kubernetes sandbox, development
environment, storage maintenance evidence) plus an authenticated GitHub CLI session and an open feature
idea aligned with the roadmap.

Once readers can operate Sugarkube, we show them how to extend it. The tutorial walks through
translating a feature brief into issues, implementing changes in focused commits, and exercising the
repository's automation checks. Example projects include refining the Pi carrier CAD, improving solar
charge telemetry dashboards, or scripting maintenance helpers for the outdoor enclosure. Learners
rehearse opening draft pull requests, sharing evidence, and iterating with reviewers until the
contribution is ready to merge.

We conclude with guidance on documenting lessons learned, planning follow-on work, and sharing
retrospectives so the community can keep the platform healthy as it evolves—including ideas for new
mounting fixtures or weatherproofing techniques.

### Milestones

1. Draft a feature proposal, break it into issues, and align milestones with community priorities.
2. Implement a small automation improvement, validate it with tests, and shepherd the pull request to
   merge.
3. Run a retrospective on the change, capturing lessons learned and potential follow-up work.

## Tutorial 13: Advanced Operations and Future Directions

**Status:** Published — [Read the tutorial](./tutorial-13-advanced-operations-future-directions.md)

**Prerequisites satisfied:** Tutorials 1–12 artefacts (safety notes, terminal transcripts, network
diagram, Git workspace, automation toolkit, hardware stack, Kubernetes sandbox, development
environment, storage maintenance evidence, and contribution workflow) plus additional worker nodes,
expanded power capacity, and optional shared storage hardware.

The capstone tutorial guides power users through expanding Sugarkube beyond a single node. Learners
pilot multi-node growth inside the aluminium cube, capture baseline metrics, and observe how workloads
rebalance under stress while powered by solar. They integrate external storage, enforce pod disruption
budgets, and explore edge AI deployments that exercise GPU or CPU accelerators. Every lab emphasises
recording evidence, benchmarking results, and turning observations into future roadmap proposals that
keep backyard deployments resilient.

We close the series by encouraging readers to transform their experiments into community knowledge:
issue proposals, documentation updates, and mentorship for new contributors.

### Milestones

1. Prototype a multi-node expansion, measure performance against the original baseline, and document
   scheduling behaviour.
2. Conduct a failure-injection exercise against a stateful workload, observe recovery, and log tuning
   insights others can replay.
3. Draft an advanced roadmap update that ties edge workload experiments back to Sugarkube's long-term
   vision.
