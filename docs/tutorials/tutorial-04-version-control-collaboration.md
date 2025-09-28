# Tutorial 4: Version Control and Collaboration Fundamentals

## Overview
This tutorial demystifies Git and GitHub so you can collaborate on Sugarkube with confidence. We'll
follow the [Sugarkube Tutorial Roadmap](./index.md#tutorial-4-version-control-and-collaboration-fundamentals)
while restating the learning goals in practical terms: create a repository, make meaningful commits,
open a pull request, and understand the automation that keeps contributions safe.

By the end you will have completed a full contribution loop against a practice repository, resolved a
simulated merge conflict, and documented the automated checks you executed. These activities mirror
real Sugarkube workflows so you are ready for future tutorials that depend on disciplined version
control habits.

## Prerequisites
* All artifacts from [Tutorial 1](./tutorial-01-computing-foundations.md): hardware photos, safety
  notes, and terminology summaries.
* Terminal transcript and notes from [Tutorial 2](./tutorial-02-navigating-linux-terminal.md) so you
  can navigate directories and edit files.
* Network mapping from [Tutorial 3](./tutorial-03-networking-internet-basics.md) to ensure your
  workstation can reach GitHub.com without interruptions.
* A GitHub account. Create one at [https://github.com/join](https://github.com/join) if needed.
* Git installed locally. Follow the official
  [Git installation guide](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git) for your
  operating system.

If you do not have administrative rights on your computer, ask an adult or supervisor to complete the
installation steps. You can still follow the tutorial using GitHub Codespaces or GitPod, but the
commands below assume a local shell.

## Lab: Manage a Practice Contribution End-to-End
Work through the steps in order. Capture screenshots or terminal logs whenever you are prompted—they
become part of your milestone evidence.

### 1. Verify Git configuration
1. Open a terminal on your workstation.
2. Confirm Git is installed:

   ```bash
   git --version
   ```

3. Configure your name and email for commits. Replace the placeholders with your actual details:

   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   ```

> [!WARNING]
> Use an email associated with your GitHub account or enable
> [GitHub's email privacy feature](https://docs.github.com/account-and-profile/email/preventing-unauthorized-email-address-use-by-github).
> Commits made with the wrong identity can block contribution credit or trigger security alerts.

4. List the effective configuration to verify the settings:

   ```bash
   git config --list | grep user.
   ```

5. Record the output in your notes as proof that your environment is ready.

### 2. Create a practice repository
1. Sign in to GitHub in your browser.
2. Visit [https://github.com/new](https://github.com/new) and create a repository named
   `sugarkube-git-lab`. Choose **Public** so you can share results. Leave "Add a README file"
   unchecked—we will create it locally.
3. On the **Quick setup** page, copy the HTTPS clone URL (it ends with `.git`).
4. Back in your terminal, create a working directory for labs and clone the new repo:

   ```bash
   mkdir -p ~/sugarkube-tutorials
   cd ~/sugarkube-tutorials
   git clone https://github.com/<your-username>/sugarkube-git-lab.git
   cd sugarkube-git-lab
   ```

> [!TIP]
> Replace `<your-username>` with your GitHub handle. If you prefer SSH, ensure you have uploaded your
> SSH key to GitHub before cloning.

5. Run `ls -a` to confirm the `.git` directory exists. This hidden folder stores Git history.
6. Create a starter README file using your editor or the command below:

   ```bash
   cat <<'README' > README.md
   # Sugarkube Git Lab

   This repository tracks my progress through Tutorial 4 of the Sugarkube series.
   README
   ```

7. Stage and commit the file:

   ```bash
   git add README.md
   git status
   git commit -m "Add starter README for Sugarkube Git Lab"
   ```

8. Push to GitHub:

   ```bash
   git push origin main
   ```

9. Refresh the repository page in your browser and capture a screenshot showing the README. Save it as
   `tutorial-04-repo.png` in your documentation folder.

### 3. Create a feature branch and make a change
1. Still inside the repository, create a branch for your upcoming documentation update:

   ```bash
   git checkout -b docs/add-collaboration-notes
   ```

2. Open `README.md` in your editor and append the following section at the end:

   ```markdown
   ## Collaboration Notes

   - [ ] Forked from the Sugarkube Git Lab tutorial instructions.
   - [ ] Created a dedicated branch for documentation updates.
   - [ ] Prepared to open a pull request with a clear summary.
   ```

3. Save the file. Use `git diff` to review changes and confirm the checklist items are present.
4. Stage and commit your work:

   ```bash
   git add README.md
   git commit -m "Document collaboration checklist"
   ```

5. Push the branch to GitHub:

   ```bash
   git push --set-upstream origin docs/add-collaboration-notes
   ```

### 4. Open a pull request (PR)
1. In your browser, GitHub will display a prompt to create a pull request for your new branch. Click it.
2. Complete the PR form:
   * **Title:** `Add collaboration checklist to README`
   * **Description:** Summarize why the change matters and include a checkbox list of tests you ran
     (for this lab, mention `git status` and spell check if available).
3. Assign yourself as the reviewer to practice the review flow.
4. Capture a screenshot of the open PR (`tutorial-04-pr.png`).
5. Click **Create pull request**.

> [!NOTE]
> In Sugarkube, pull request descriptions should reference related issues or tutorials. Practicing now
> builds the habit of writing actionable summaries.

### 5. Simulate review feedback
1. Pretend a teammate suggested adding a link to Sugarkube docs. You will incorporate the feedback in a
   follow-up commit.
2. In the terminal, ensure you are still on `docs/add-collaboration-notes`.
3. Append a resource link to the checklist section:

   ```bash
   cat <<'EXTRA' >> README.md

   ### Resources
   - [Sugarkube Tutorial Roadmap](https://github.com/sugarkube-labs/sugarkube/blob/main/docs/tutorials/index.md)
   EXTRA
   ```

4. Stage, commit, and push the update:

   ```bash
   git add README.md
   git commit -m "Link to Sugarkube tutorial roadmap"
   git push
   ```

5. Refresh the PR, verify the new commit appears, and mark the review conversation as resolved. Add a
   comment describing what changed.

### 6. Merge the pull request
1. Confirm the PR shows all checks passing (GitHub automatically runs syntax checks on Markdown).
2. Click **Merge pull request**, then **Confirm merge**.
3. Delete the branch in the GitHub UI when prompted.
4. Back in the terminal, switch to `main` and pull the merge commit:

   ```bash
   git checkout main
   git pull origin main
   ```

5. Run `git branch -a` to ensure the remote feature branch is gone.
6. Update your notes with the merge timestamp and include the PR link for future reference.

### 7. Practice resolving a merge conflict locally
1. Create a new branch:

   ```bash
   git checkout -b docs/merge-conflict-practice
   ```

2. Edit `README.md` to replace the first heading with:

   ```markdown
   # Sugarkube Git Lab (Conflict Practice)
   ```

3. Commit but do not push yet:

   ```bash
   git add README.md
   git commit -m "Prepare conflicting heading"
   ```

4. Switch back to `main` and make a different change to the same line:

   ```bash
   git checkout main
   sed -i '1s/.*/# Sugarkube Git Lab (Main Branch Update)/' README.md
   git commit -am "Update README heading on main"
   git push origin main
   ```

5. Return to your conflict branch and rebase it onto the latest main:

   ```bash
   git checkout docs/merge-conflict-practice
   git rebase main
   ```

6. Git reports a conflict. Open `README.md`, decide on the final heading (for example,
   `# Sugarkube Git Lab (Resolved Conflict)`), and remove the conflict markers (`<<<<<<<`, `=======`,
   `>>>>>>>`).
7. Mark the conflict resolved and continue the rebase:

   ```bash
   git add README.md
   git rebase --continue
   ```

8. Push the resolved branch:

   ```bash
   git push --set-upstream origin docs/merge-conflict-practice
   ```

9. Open a PR for the branch, note how GitHub highlights the conflict resolution, then close the PR
   without merging. Document the steps you took to resolve the conflict in your notes.

> [!TIP]
> If you are uncomfortable with rebasing, you can practice merge conflicts using `git merge` instead.
> The important part is learning how to read conflict markers and preserve the intended content.

### 8. Document continuous integration (CI) expectations
1. Review the `.github/workflows/` directory in the Sugarkube repository to understand which checks run
   on pull requests. Note key commands such as `pre-commit run --all-files` and `pyspelling`.
2. In your lab repository, create a file named `CI-NOTES.md` summarizing:
   * Which checks you ran locally (list at least `git status` and one linting or formatting command).
   * Which checks GitHub executed automatically.
   * How you would respond if a check failed.

   ```bash
   cat <<'CI' > CI-NOTES.md
   # Continuous Integration Notes

   ## Local checks
   - `git status` to confirm a clean worktree before commits.
   - `pre-commit run --all-files` to execute the repository checks before every PR.
   - `pyspelling -c .spellcheck.yaml` to confirm documentation changes pass the spell checker.
   - `linkchecker --no-warnings README.md docs/` to validate links across the handbook.

   ## GitHub checks
   - Pull requests trigger documentation linting and spell checking.
   - Sugarkube requires additional tools like `pyspelling` and `linkchecker` before merge.

   ## Failure response
   - Re-run the failing command locally.
   - Capture logs or screenshots.
   - Update the pull request with findings and request help if needed.
   CI
   ```

> [!NOTE]
> Sugarkube's automated tests verify this tutorial keeps `pre-commit run --all-files`,
> `pyspelling -c .spellcheck.yaml`, and `linkchecker --no-warnings README.md docs/`
> in the checklist so future contributors learn to run the project checks locally.

3. Commit and push the notes:

   ```bash
   git add CI-NOTES.md
   git commit -m "Document CI expectations for Sugarkube"
   git push
   ```

4. Open a final PR summarizing your CI research, then merge it following the earlier steps. Archive the
   PR URL in your knowledge base.

## Milestone Checklist
Use this list to verify you met the roadmap milestones. Mark each box when you have tangible evidence
(screenshots, commit hashes, or notes).

- [ ] **Fork and clone a sandbox repository:** Screenshot of `sugarkube-git-lab` on GitHub and the
      initial commit hash recorded in your notes.
- [ ] **Resolve a simulated merge conflict:** Conflict markers removed, final heading committed, and a
      short write-up explaining your resolution strategy.
- [ ] **Document the CI workflow:** `CI-NOTES.md` pushed to GitHub with links or descriptions of the
      checks you ran locally versus those executed by GitHub.

## Troubleshooting
> [!QUESTION]
> **`git push` fails with `authentication failed`. How can I fix this?**
>
> Ensure you sign in with a [personal access token](https://docs.github.com/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token)
> whenever Git requests credentials. Skip the legacy account login string. Update your credential
> helper with `git config --global credential.helper store`, then retry the push.
>
> [!QUESTION]
> **I cannot resolve the merge conflict markers. What should I try next?**
>
> Run `git status` to see which files are conflicted, then open them in a text editor that highlights
> conflicts (VS Code, Vim, or Nano). Keep the lines you need, delete the markers, and rerun
> `git add <file>` followed by `git rebase --continue` or `git merge --continue`.

## Next Steps
Advance to [Tutorial 5: Programming for Operations with Python and Bash](./index.md#tutorial-5-programming-for-operations-with-python-and-bash).
Bring the repositories and notes you created here—they provide a working sandbox for scripting and
automation practice.

> [!NOTE]
> Automated coverage in `tests/test_tutorial_next_steps.py` keeps this "Next Steps" section aligned
> with the published tutorial roadmap.
