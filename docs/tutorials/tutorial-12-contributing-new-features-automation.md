# Tutorial 12: Contributing New Features and Automation

## Overview
This chapter of the [Sugarkube Tutorial Roadmap](./index.md#tutorial-12-contributing-new-features-and-automation)
shows you how to plan, implement, and ship an improvement to the project like a seasoned contributor.
You will turn a feature idea into an actionable issue, drive the change through local automation, and
publish a polished pull request complete with tests, documentation, and review-ready evidence.

By the end you will have:
* Captured a contribution proposal that aligns with roadmap milestones and clearly states the
  acceptance criteria.
* Implemented a small automation or documentation enhancement in a clean Git branch while exercising
  Sugarkube's quality gates.
* Practiced reviewing your own work, gathering artefacts, and narrating the change so maintainers can
  merge it confidently.

## Prerequisites
* Completed artefacts from [Tutorial 1](./tutorial-01-computing-foundations.md) through
  [Tutorial 11](./tutorial-11-storage-migration-maintenance.md), especially your Git workspace,
  automation toolkit, and maintenance notes.
* A fork of the Sugarkube repository with SSH access configured, plus a workstation that can run
  Docker (for optional validation) and the required tooling (`python3`, `pre-commit`, `pyspelling`,
  `linkchecker`).
* The [GitHub CLI](https://cli.github.com/) (`gh`) authenticated with the account that owns your fork.
* Optional: a collaborator or mentor who can supply review feedback while you practice the workflow.

> [!IMPORTANT]
> You will exercise real contribution paths. Work in your fork until a maintainer invites you to open
> a pull request against the canonical repository. Never commit secrets, tokens, or personally
> identifiable information. If you see sensitive data in your diff, stop and sanitize it before
> continuing.

## Lab: Plan, Build, and Ship a Sugarkube Improvement
Open your lab workspace at `~/sugarkube-labs/tutorial-12/` and store all transcripts, screenshots,
and notes. Treat this as the audit log you will share with reviewers.

### 1. Align on the feature goal and scope
1. Pull the latest main branch and synchronise your fork:

   ```bash
   cd ~/code/sugarkube
   git checkout main
   git pull upstream main
   git push origin main
   ```

2. Create a planning folder and start a feature brief:

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-12/{notes,logs,media,evidence}
   cat <<'MARKDOWN' > ~/sugarkube-labs/tutorial-12/notes/feature-brief.md
   # Feature Brief: <replace-with-your-idea>
   - Date:
   - Author:
   - Problem statement:
   - Desired behaviour:
   - Success metrics / acceptance criteria:
   - Rollback or mitigation plan:
   MARKDOWN
   ```

3. Inventory existing issues related to your idea. Use labels like `good first issue` or
   `documentation` to find candidates:

   ```bash
   gh issue list --limit 20 --label "good first issue"
   gh issue view <ISSUE_NUMBER> --web
   ```

4. If no issue exists, open one in your fork using the "Feature request" template. Paste a summary of
   your brief and link to prerequisite tutorials.

> [!TIP]
> Share the issue URL with your mentor or study group. Ask them to challenge the acceptance criteria
> so you catch assumptions before you start coding.

### 2. Spin up a feature branch and record baselines
1. Create a branch that follows your personal naming convention (for example `feature/tutorial-12-lab`):

   ```bash
   git switch -c feature/tutorial-12-lab
   ```

2. Snapshot the current automation status so you can prove you started from a clean slate:

   ```bash
   pre-commit run --all-files | tee ~/sugarkube-labs/tutorial-12/logs/pre-change-pre-commit.txt
   pyspelling -c .spellcheck.yaml | tee ~/sugarkube-labs/tutorial-12/logs/pre-change-spellcheck.txt
   linkchecker --no-warnings README.md docs/ \
     | tee ~/sugarkube-labs/tutorial-12/logs/pre-change-linkchecker.txt
   ```

3. Create a lab diary to log every command you run during the feature work:

   ```bash
   script --command "bash" ~/sugarkube-labs/tutorial-12/logs/feature-session.typescript
   ```

   Leave the shell open and keep working inside this session until you reach the review stage. Press
   `Ctrl+D` when the change is ready for submission to save the transcript.

> [!WARNING]
> If any baseline command fails, fix the environment before you proceed. Opening a PR on top of a
> broken main branch will waste reviewer time and may trigger CI outages. Capture the error logs under
> `logs/` so you can attach them to your issue if you need help.

### 3. Write the failing test or verification first
1. Update or create a test that demonstrates the missing feature. For example, extend an existing
   `pytest` case under `tests/` or add a doctest-style snippet in the documentation. Make sure the
   change fails when run against the current code.

   ```bash
   # Example: extend a CLI unit test (replace with the test relevant to your feature)
   $EDITOR tests/test_checks_script.py
   pytest tests/test_checks_script.py
   ```

2. Capture the failing output in your lab diary and copy the summary into `notes/feature-brief.md`
   under a new "Observed failure" heading. This record proves the test guards against regressions.

> [!TROUBLESHOOT]
> If you cannot find a natural home for your test, open a discussion in the issue or start a thread in
> the Sugarkube chat. Proposing the test location early prevents refactors later in the review.

### 4. Implement the feature with incremental commits
1. Modify the relevant code or documentation to satisfy the acceptance criteria. Commit in logical
   chunks with clear messages. A minimal example for a documentation automation tweak might look like:

   ```bash
   $EDITOR scripts/checks.sh
   git add scripts/checks.sh
   git commit -m "Add --summary flag to checks helper"
   ```

2. Update or create user-facing documentation alongside the code change. For example, modify the
   README, a tutorial, or `docs/automation/` reference files so readers know how to use the new
   capability.

3. Rerun the targeted test and any affected suites until they pass:

   ```bash
   pytest tests/test_checks_script.py
   ```

4. Once the feature works locally, run the full project automation to guarantee parity with CI:

   ```bash
   pre-commit run --all-files
   pyspelling -c .spellcheck.yaml
   linkchecker --no-warnings README.md docs/
   ```

5. Record command outputs under `~/sugarkube-labs/tutorial-12/logs/` and update your brief with
   highlights or surprises encountered during implementation.

> [!NOTE]
> Keep your commits focused. If you discover unrelated issues, file a new ticket and park the idea.
> Small, reviewable diffs merge faster and reduce the risk of regressions.

### 5. Prepare the pull request package
1. Summarise the change in a `docs/changes/tutorial-12-lab.md` file inside your branch. Include:
   * What problem you solved.
   * How you validated the fix.
   * Links to logs, screenshots, or transcripts stored in your lab workspace.

   ```bash
   mkdir -p docs/changes
   cat <<'MARKDOWN' > docs/changes/tutorial-12-lab.md
   # Tutorial 12 Lab Change Summary
   - Problem solved:
   - Files touched:
   - Tests and checks:
   - Evidence archive location:
   MARKDOWN
   git add docs/changes/tutorial-12-lab.md
   git commit -m "Document tutorial 12 lab change summary"
   ```

2. Push the branch to your fork and open a draft pull request using the repository template:

   ```bash
   git push origin feature/tutorial-12-lab
   gh pr create --fill --draft --base main --head feature/tutorial-12-lab
   ```

3. Upload supporting artefacts (for example, the `feature-session.typescript` transcript or
   screenshots) to your lab workspace. Share them with reviewers through the PR description or as
   attachments if policy allows.

4. Review your own diff in the GitHub UI. Confirm the tests now pass and the documentation reflects the
   new behaviour. Address any formatting or spelling issues before requesting review.

> [!TIP]
> Use GitHub's "Preview" tab on the PR description to confirm checklists render correctly. A polished
> description signals you respect reviewer time and understand Sugarkube's contribution standards.

### 6. Iterate with reviewers and merge
1. Respond to reviewer comments within one business day. Quote the feedback, explain the change you
   made, and push follow-up commits that keep history clean. Squash only when a maintainer requests it.

2. Each time you push, rerun:

   ```bash
   pre-commit run --all-files
   pyspelling -c .spellcheck.yaml
   linkchecker --no-warnings README.md docs/
   ```

   Attach updated logs to your evidence folder.

3. When checks are green and approvals are in, merge using "Squash and merge" or the repository's
   preferred strategy. Tag your mentor or teammate in the PR to celebrate the milestone and solicit a
   retrospective conversation.

4. Update `notes/feature-brief.md` with a final "Lessons learned" section. Include how long each stage
   took, what you would automate next, and any documentation gaps you noticed.

> [!SUCCESS]
> Congratulations! You have now executed the full Sugarkube contribution workflow—from idea to merged
> change—while leaving an audit trail future maintainers can trust.

## Milestone Checklist
Use this checklist to verify you achieved the roadmap milestones. Mark each box only when you have
supporting evidence (issue links, commit hashes, transcripts, or screenshots).

- [ ] **Draft a feature proposal and align with community priorities:** Feature issue opened (or
      claimed) with acceptance criteria, stakeholder feedback captured in your brief, and links to
      relevant tutorials.
- [ ] **Implement and validate an automation improvement:** Failing test reproduced, code and docs
      updated, and full `pre-commit`, `pyspelling`, `linkchecker`, and `pytest` logs archived in your
      lab workspace.
- [ ] **Run a retrospective on the change:** PR merged, lessons learned recorded in
      `notes/feature-brief.md`, and follow-up actions (if any) filed as issues or TODOs.

## Next Steps
Advance to [Tutorial 13: Advanced Operations and Future Directions](./index.md#tutorial-13-advanced-operations-and-future-directions)
when it becomes available. Bring the contribution evidence you just produced—future experiments will
build on your ability to plan, implement, and communicate complex changes.
