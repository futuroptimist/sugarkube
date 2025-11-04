---
mode: 'agent'
description: 'Pick a small batch of unchecked CI/test issues from notes/, fix them, add validated outages entries (only for fixes in this PR), update notes/, and open a PR.'
tools: ['github', 'playwright']
---

**Goal**  
Fix a small, independent batch of remaining CI/test failures documented under `notes/`, document each fix with a conformant `outages/` entry (only if the fix lands in the same PR), update the checkboxes in `notes/`, and open a focused PR.

**Plan**
1) Parse:  
   - #file:notes/ci-test-fixes-action-plan.md  
   - #file:notes/ci-test-failures-remaining-work.md  
   Enumerate all **unchecked** checkboxes.

2) Select 1–3 items that can be implemented together with minimal risk and without broad refactors. Write a brief execution plan and proceed.

3) Implement:
   - Make the minimal code/test changes needed to resolve each selected item.  
   - Identify test commands from the Makefile and `.github/workflows/*.yml`. Run locally the same suites CI runs (BATS, Playwright E2E, QEMU smoke, etc.) and iterate until green for the affected areas.

4) Outages:
   - For each fixed failure, create `outages/<yyyy-mm-dd>-<short-slug>.json` describing the failure and resolution. Conform **exactly** to `#file:outages/schema.json`.  
   - Validate each JSON against the schema before committing (use a JSON Schema validator).  
   - Only add outages entries for fixes included in this PR.

5) Notes:
   - Check off the completed items in `notes/ci-test-failures-remaining-work.md` (and `notes/ci-test-fixes-action-plan.md` if applicable).  
   - For new bugs discovered, append new unchecked boxes with brief details and repro pointers.

6) PR:
   - Branch: `ci/fix/<short-slug>-<date>`  
   - Title: `ci: fix <short summary> (+ outages)`  
   - Body sections: **Summary**, **Outages entries** (paths), **Notes updated** (quote exact checkboxes), **Verification** (commands + results), **Follow‑ups** (remaining unchecked boxes).

**Constraints**
- Keep scope tight (≈1–3 items; ≤ ~300 changed lines excluding generated/snapshot files).
- Preserve logging semantics unless a specific test requires changes.
- Do not modify `outages/schema.json`.
