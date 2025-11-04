---
mode: 'agent'
description: >-
  Pick a small batch of unchecked CI/test issues from notes/, fix them, add validated
  outages entries (only for fixes in this PR), update notes/, and open a PR.
tools: ['github', 'playwright']
---

**Goal**  
Fix a small, independent batch of remaining CI/test failures documented under `notes/`.
Document each fix with a conformant `outages/` entry (only if the fix lands in the same PR),
update the checkboxes in `notes/`, and open a focused PR.

**Plan**
1) Parse:  
   - #file:notes/ci-test-fixes-action-plan.md  
   - #file:notes/ci-test-failures-remaining-work.md  
   Enumerate all **unchecked** checkboxes.

2) Select 1–2 items that can be implemented together with minimal risk and without broad
   refactors. Write a brief execution plan and proceed.
   - **Select 1–2 unchecked items maximum** that can be completed together without
     cross-cutting refactors or public API changes.

3) Implement:
   - Make the minimal code/test changes needed to resolve each selected item.
   - Identify test commands from the Makefile and `.github/workflows/*.yml`. Run locally the
     same suites CI runs (BATS, Playwright E2E, QEMU smoke, etc.) and iterate until green for
     the affected areas.

**Definition of Done**
- `scripts/ci_commands.sh` passes locally end-to-end.
- All `outages/*.json` added in this PR pass `scripts/validate_outages.py`.
- PR body uses the provided template verbatim and quotes the exact `notes/` checkboxes checked.
- Total diff ≤ ~300 LOC excluding lockfiles/snapshots.

4) Outages:
   - For each fixed failure, create `outages/<yyyy-mm-dd>-<short-slug>.json` describing the
     failure and resolution. Conform **exactly** to `#file:outages/schema.json`.
   - Validate each JSON against the schema before committing (use a JSON Schema validator).
   - Only add outages entries for fixes included in this PR.

   **Outages schema validation (required)**
   - `python3 scripts/validate_outages.py outages/2025-*.json`
   - `jq -e . outages/*.json`

5) Notes:
   - Check off the completed items in `notes/ci-test-failures-remaining-work.md` (and
     `notes/ci-test-fixes-action-plan.md` if applicable).
   - For new bugs discovered, append new unchecked boxes with brief details and repro pointers.

6) PR:
   - Branch: `ci/fix/<area>-<yyyymmdd>`
   - Labels: `ci`, `tests`, `outages`
   - Title: `ci: fix <short summary> (+ outages)`
   - Body sections: **Summary**, **Outages entries** (paths), **Notes updated** (quote exact
     checkboxes), **Verification** (commands + results), **Follow‑ups** (remaining unchecked
     boxes).

**Do not change**
- `outages/schema.json`
- Logging levels or semantics
- Unrelated Playwright snapshots
- Broad refactors

If any chosen item balloons in scope, **drop it from this PR**, restore/append an unchecked
box in `notes/…` with repro details and a brief scope estimate.

Reproduce suspected flakes **3× locally** and apply the **least-invasive** stabilization
(timeouts/retries/backoff) only. Document evidence under **Stabilizations** in the PR body
(logs or notes).

Upload relevant test logs as CI artifacts and summarize key lines (≤5 bullets) in the PR body.

**Agent must not open a PR unless** (1) `scripts/ci_commands.sh` passes locally; (2) all
added `outages/*.json` pass `scripts/validate_outages.py`; (3) the PR body uses the provided
template and quotes the exact `notes/` checkboxes.

**PR Body Template (use verbatim)**
~~~md
## Summary
- Fixed: <bullet list>
- Rationale: <1–2 sentences per item>

## Verification (must match CI)
Commands run locally:
```bash
bash scripts/ci_commands.sh
```
Results:

BATS: ✅ pass

E2E/Playwright: ✅ pass

QEMU smoke: ✅ pass

CI runs:

Before: <link>

After: <link>

Outages entries (added in this PR)
outages/<yyyy-mm-dd>-<short-slug>.json

Schema checks:

```bash
jq -e . outages/<yyyy-mm-dd>-*.json
python3 scripts/validate_outages.py outages/<yyyy-mm-dd>-*.json
```

Notes updated
Checked off:

<quoted line from notes/ci-test-failures-remaining-work.md>

<quoted line from notes/ci-test-fixes-action-plan.md>

Stabilizations (if any)
Test: <name> — Change: <minimal tweak> — Why: <flake evidence>

Follow-ups
Remaining unchecked boxes (verbatim from notes/)

```python
<copy remaining unchecked boxes>
```
~~~

**Constraints**
- Keep scope tight (≈1–3 items; ≤ ~300 changed lines excluding generated/snapshot files).
- Preserve logging semantics unless a specific test requires changes.
- Do not modify `outages/schema.json`.
