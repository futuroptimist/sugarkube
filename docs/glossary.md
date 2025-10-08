---
personas:
  - hardware
  - software
---

# Sugarkube Glossary

The tutorials reference a consistent set of core terms. Use this glossary to align on vocabulary
before diving into the roadmap so later guides can assume a shared foundation.

## CPU

The **Central Processing Unit** is the Pi's "brain". It reads instructions from memory, performs the
math or logic they describe, and coordinates peripherals. When tutorials mention "processor load"
or "cores", they are referring to how busy the CPU is.

## Memory

**Random-access memory (RAM)** is short-term workspace for the CPU. Programs place data here while
running so it can be accessed quickly. Low available memory can make commands sluggish or cause
processes to restart.

## Storage

**Persistent storage** retains data even after power is removed. On Sugarkube this usually means the
microSD card or SSD that holds the operating system, configuration, and logs referenced throughout
the guides.

## Operating System

An **operating system (OS)** manages hardware resources and exposes common services—filesystems,
process scheduling, networking—to software. Sugarkube relies on Raspberry Pi OS with additional
cloud-init automation layered on top.

## Shell

The **command shell** (e.g., `bash`) lets you interact with the OS through text commands. Tutorials
reference shell prompts, scripts, and transcripts; they all stem from learning to navigate and
automate via the shell.

---

Regression coverage: `tests/test_glossary_doc.py` keeps this glossary referenced from the tutorial
roadmap and ensures the headings above remain available for cross-linking.
