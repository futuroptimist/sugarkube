# Sugarkube Tutorial Roadmap

Sugarkube combines hardware, software, and operational practices into a cohesive home-lab scale
platform. This roadmap outlines the tutorials we plan to write, sequenced so a newcomer with no prior
technical background can progress from first principles to confidently maintaining and extending the
platform. Each entry will eventually become its own standalone guide; for now, the descriptions below
capture the narrative arc, learning goals, and practical exercises we intend to include.

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
public endpoints, learning how to interpret latency, packet loss, and HTTP status codes.

The second half bridges networking theory with Sugarkube needs. Learners review how Raspberry Pis
connect over Ethernet or Wi-Fi, how VLANs and subnets can segregate lab traffic, and what it means to
expose services securely. The tutorial sets expectations for the network configuration tasks they
perform in later guides, including firewall adjustments and static DHCP reservations.

### Milestones

1. Diagram a home network, annotate IP ranges, and mark where Sugarkube gear will connect.
2. Run latency and bandwidth measurements between two devices, interpret results, and record them in
   a lab notebook.
3. Configure a sample firewall rule or router reservation in a simulator to cement networking
   vocabulary.

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
where to find contribution guidelines for both code and documentation changes.

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

This tutorial returns to hardware, giving a guided tour of the Sugarkube enclosure, power regulation,
and accessory boards. Readers will learn how to select microSD cards and SSDs, identify compatible USB
to serial adapters, and respect thermal and electrical constraints. We will cover cable management,
mounting considerations, and best practices for handling ribbon cables and GPIO headers.

Hands-on sections will include assembling a mock Pi stack, routing power through recommended hubs,
and verifying voltage with a multimeter. We will emphasize safety, documenting any optional tools or
fixtures that can simplify the build process for classroom or maker-space deployments.

### Milestones

1. Assemble the enclosure using a build checklist and record a time-lapse or photo log for reference.
2. Perform voltage and continuity checks with a multimeter, logging expected versus measured values.
3. Stress-test thermal management with a controlled workload and document mitigation strategies.

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

Here we detail what happens the first time a Sugarkube Pi boots. Learners will explore `first_boot_service.py`,
understand the generated reports, and practice interpreting logs under `/boot/first-boot-report/`.
Step-by-step exercises will validate k3s readiness, confirm token.place and dspace health, and trigger
the self-healing services to see how automated recovery behaves.

We will also demonstrate retrieving kubeconfig and other artifacts without SSH, showing how the
workflow supports classroom or remote deployments. Troubleshooting scenarios will teach learners how
to respond when services fail, encouraging them to gather support bundles before escalating issues.

### Milestones

1. Boot the Pi, collect first-boot reports, and annotate them with commentary on expected behaviors.
2. Run the verification suite, remediate any failures, and track actions in an incident log.
3. Publish a resilience drill that intentionally restarts services and documents recovery timelines.

## Tutorial 11: Storage Migration and Long-Term Maintenance

This tutorial covers SSD cloning, validation, and rollback strategies. Readers will execute the
`ssd_clone.py` helper, review generated reports, and run the health monitor to gauge drive longevity.
We will cover backup strategies, log rotation, and proactive maintenance tasks like updating Helm
bundles or applying OS patches.

The second half explores telemetry and observability. Learners will enable optional metrics exporters,
integrate dashboards, and configure remote notifications so they stay ahead of failures. We will also
share best practices for documenting maintenance windows and communicating status to collaborators.

### Milestones

1. Execute an SSD migration in a lab environment, validate clone integrity, and draft a rollback plan.
2. Configure backup jobs, verify restore procedures, and capture screenshots or logs as evidence.
3. Deploy observability tools, define alert thresholds, and test notification pathways end to end.

## Tutorial 12: Contributing New Features and Automation

Once readers can operate Sugarkube, we show them how to extend it. The tutorial will highlight the
pi-image release workflow, explain how to design checklist-driven improvements, and teach strategies
for writing tests before shipping changes. Learners will practice updating documentation, adding
scripts, and verifying everything with local CI commands before opening a pull request.

We conclude with guidance on reviewing contributions from others, triaging issues, and planning larger
initiatives. By reinforcing collaborative habits, we ensure the community can keep the platform
healthy as it evolves.

### Milestones

1. Draft a feature proposal, break it into issues, and align milestones with community priorities.
2. Implement a small automation improvement, validate it with tests, and shepherd the pull request to
   merge.
3. Run a retrospective on the change, capturing lessons learned and potential follow-up work.

## Tutorial 13: Advanced Operations and Future Directions

The final tutorial explores topics for power users: multi-node expansions, integrating external
storage arrays, and experimenting with edge AI workloads. We will dive into customizing Helm bundles,
writing bespoke self-healing units, and tuning Kubernetes for performance or energy efficiency.

We close the series by outlining research questions and stretch goals—hardware-in-the-loop testing,
recovery console images, and advanced observability pipelines—so motivated readers know where they can
push the platform next. The tutorial will encourage knowledge sharing, inviting graduates to document
their experiments and feed improvements back into Sugarkube.

### Milestones

1. Prototype a multi-node expansion or edge workload, measure performance, and share reproducible
   configs.
2. Conduct a failure-injection exercise, observe recovery, and document tuning insights for others.
3. Present a roadmap update that ties advanced experiments back to Sugarkube's long-term vision.
