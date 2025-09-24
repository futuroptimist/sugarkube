# Tutorial 8: Preparing a Sugarkube Development Environment

## Overview
This tutorial continues the
[Sugarkube Tutorial Roadmap](./index.md#tutorial-8-preparing-a-sugarkube-development-environment)
by showing you how to stand up a reliable workstation for contributing to the project.
You will clone
the repository, install the automation toolchain, and rehearse the local checks so continuous
integration succeeds on your first pull request. Every step includes artefact capture so you can
prove what you executed and share it with mentors or reviewers.

By the end you will have:
* Provisioned a clean workspace on disk with version-controlled lab notes.
* Installed Git, Python, `pipx`, `pre-commit`, `pyspelling`, `linkchecker`, and supporting packages.
* Explored the project task runners (`just`, `make`) and the `scripts/` helpers used by CI.
* Run the documentation and repository checks locally, collecting transcripts and screenshots.
* Documented how you will manage credentials and secrets on your workstation.

## Prerequisites
* Safety and hardware handling practices from
  [Tutorial 1](./tutorial-01-computing-foundations.md).
* Terminal navigation habits and transcript capture workflow from
  [Tutorial 2](./tutorial-02-navigating-linux-terminal.md).
* Network inspection notes from [Tutorial 3](./tutorial-03-networking-internet-basics.md) so you can
  diagnose connectivity issues while installing dependencies.
* Git collaboration workflow from
  [Tutorial 4](./tutorial-04-version-control-collaboration.md) for branching and recording evidence.
* Automation scripts workspace from
  [Tutorial 5](./tutorial-05-programming-for-operations.md) to reuse logging conventions.
* Sugarkube hardware kit assembly from
  [Tutorial 6](./tutorial-06-raspberry-pi-hardware-power.md) to reference when identifying connected
  devices.
* Kubernetes sandbox experience from
  [Tutorial 7](./tutorial-07-kubernetes-container-fundamentals.md) so `kubectl` and
  container tooling are already familiar.

> [!NOTE]
> You can complete this tutorial on macOS, Windows (with WSL), or Linux. When you encounter an
> operating-system-specific step, follow the subsection matching your platform.

## Lab: Bootstrap, Validate, and Document Your Development Environment
Create a working directory called `~/sugarkube-labs/tutorial-08/`. All screenshots, transcripts,
configuration files, and notes for this tutorial will live underneath it.

### 1. Create the workspace and baseline documentation
1. Open a terminal and create the directories you will need:

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-08/{notes,logs,screenshots,workspace}
   cd ~/sugarkube-labs/tutorial-08
   ```

2. Initialise a Git repository dedicated to your lab evidence:

   ```bash
   git init
   echo "# Tutorial 8 Lab Journal" > notes/README.md
   git add notes/README.md
   git commit -m "Start Tutorial 8 lab journal"
   ```

3. Record the hostname, OS details, and current user so reviewers understand the context:

   ```bash
   {
     echo "# System fingerprint"
     date --iso-8601=seconds
     uname -a
     id
   } > logs/system-fingerprint.txt
   git add logs/system-fingerprint.txt
   git commit -m "Capture system fingerprint"
   ```

4. Launch your preferred screen-recording tool and document the terminal during each major step.
   Save
   captures in `screenshots/` or export `.mp4` files to `logs/` if the tool supports it.

> [!TIP]
> If you are new to screen capture, install [OBS Studio](https://obsproject.com/) or use the
> built-in recorder on your platform. Annotate the files with timestamps in `notes/README.md`
> so you can locate them later.

### 2. Install base tooling with `pipx`
1. Confirm that Python 3.11 or newer is available. On Linux or macOS run:

   ```bash
   python3 --version
   ```

   On Windows PowerShell use:

   ```powershell
   py --version
   ```

   If Python is missing, install it using your OS package manager before proceeding.

2. Install `pipx` to manage Python command-line tools in isolated environments:

   * **Debian/Ubuntu Linux**:

     ```bash
     sudo apt-get update
     sudo apt-get install -y python3-pip python3-venv pipx
     pipx ensurepath
     ```

   * **Fedora/RHEL**:

     ```bash
     sudo dnf install -y python3-pip python3-virtualenv pipx
     pipx ensurepath
     ```

   * **macOS with Homebrew**:

     ```bash
     brew install python@3.11 pipx
     pipx ensurepath
     ```

   * **Windows (PowerShell)**:

     ```powershell
     winget install --id=Python.Python.3.11
     python -m pip install --user pipx
     python -m pipx ensurepath
     ```

3. Close and reopen your terminal so the `pipx` path changes apply, then install the core tools:

   ```bash
   pipx install pre-commit
   pipx install pyspelling
   pipx install linkchecker
   ```

4. Log tool versions for your records:

   ```bash
   {
     echo "# Tutorial 8 Tool Versions"
     date --iso-8601=seconds
     git --version
     python3 --version
     pipx --version
     pre-commit --version
     pyspelling --version
     linkchecker --version
   } > logs/tool-versions.txt
   git add logs/tool-versions.txt
   git commit -m "Document toolchain versions"
   ```

> [!WARNING]
> `linkchecker` crawls URLs you specify. Run it only against documentation you trust to avoid
> hitting sensitive endpoints unexpectedly. In this tutorial we restrict it to local Markdown files.

### 3. Clone the Sugarkube repository and explore task runners
1. Move into the `workspace/` directory and clone the upstream repository:

   ```bash
   cd ~/sugarkube-labs/tutorial-08/workspace
   git clone https://github.com/futuroptimist/sugarkube.git
   cd sugarkube
   ```

2. Configure Git remotes for your fork if you have one:

   ```bash
   git remote add personal git@github.com:<your-username>/sugarkube.git
   git remote -v
   ```

   Record the output inside `../../notes/README.md` so reviewers know which remotes exist.

3. Create a Python virtual environment specifically for repository development:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   python -m pip install --upgrade pip
   ```

4. Install repository dependencies referenced by CI:

   ```bash
   pip install -r requirements.txt 2>/dev/null || true
   pip install -r requirements-dev.txt 2>/dev/null || true
   pip install pre-commit pyspelling linkchecker
   ```

   Not every branch uses `requirements*.txt`. The commands above succeed even when the files are
   absent, mirroring how `scripts/checks.sh` behaves.

5. Explore the `justfile` and `Makefile` to understand available helpers:

   ```bash
   just --list
   make help
   ```

   Copy the command output into `../../logs/task-runner-overview.txt` for later reference.

6. Bootstrap `pre-commit` within the repository:

   ```bash
   pre-commit install
   pre-commit autoupdate
   ```

7. Run the doctor check to ensure your environment matches project expectations:

   ```bash
   just doctor || make doctor
   ```

   Save the transcript using the `script` utility from Tutorial 2:

   ```bash
   script -q ../../logs/doctor-transcript.txt just doctor || make doctor
   ```

> [!TIP]
> If `just` is not installed, install it via `brew install just` (macOS), `sudo apt-get install`
> `just` (Debian/Ubuntu), or download a release from
> [github.com/casey/just](https://github.com/casey/just). Document the installation command in
> `notes/README.md`.

### 4. Rehearse repository automation and capture evidence
1. Execute the full suite of required documentation checks:

   ```bash
   pre-commit run --all-files
   pyspelling -c .spellcheck.yaml
   linkchecker --no-warnings README.md docs/
   ```

   Use `script` to capture each command run:

   ```bash
   script -q ../../logs/pre-commit.txt pre-commit run --all-files
   script -q ../../logs/spellcheck.txt pyspelling -c .spellcheck.yaml
   script -q ../../logs/linkcheck.txt linkchecker --no-warnings README.md docs/
   ```

2. Run the project secret scanner against an empty diff to understand the output format:

   ```bash
   git diff --cached | ./scripts/scan-secrets.py
   ```

   Take a screenshot of the terminal showing the command and store it at
   `../../screenshots/scan-secrets.png`.

3. Explore other helper scripts so you know where to look later. Start with the Pi image
   download dry run:

   ```bash
   ./scripts/download_pi_image.sh --dry-run
   ```

   Copy the resulting summary into `../../notes/README.md` under a heading titled "Pi image helper".

4. Identify the checks GitHub Actions will run by browsing `.github/workflows/`. Use `less` or your
   editor to inspect `docs.yml`, `spellcheck.yml`, and `scad-to-stl.yml`. Summarise what each
   workflow validates in `../../notes/README.md`.

> [!IMPORTANT]
> Whenever `pre-commit run --all-files` reports fixes, rerun the command until it exits cleanly.
> Commit the generated changes to your lab evidence repository so auditors can verify the
> before/after state.

### 5. Capture your credential-handling plan
1. Create `../../notes/credentials.md` and describe how you will store API tokens, SSH keys, and
   environment-variable files such as ones named `.env`.
   Reference the secret storage solution you rely on (for example a hardware security module).

2. Document how you will rotate credentials and what evidence (logs, screenshots) you will retain
   after each rotation.

3. Add both files to your lab repository and commit the changes:

   ```bash
   cd ~/sugarkube-labs/tutorial-08
   git status
   git add notes/README.md notes/credentials.md logs/*.txt screenshots/
   git commit -m "Document Sugarkube development environment setup"
   ```

4. Tag the repository so you can reference this state later:

   ```bash
   git tag tutorial-08-environment-ready
   git log --oneline --decorate
   ```

> [!CAUTION]
> Never commit actual secrets or private keys. Instead, reference secure storage locations or masked
> placeholders. Use `git commit --amend` only inside your lab evidence repo, not inside the
> Sugarkube repository you cloned for development.

## Milestone Checklist
Use this section to verify progress against the roadmap. Mark each item as you complete it.

- [ ] **Repository cloned and checks passing**
  - [ ] Workspace directories created under `~/sugarkube-labs/tutorial-08/`.
  - [ ] Sugarkube repository cloned, virtual environment activated, and `pre-commit run --all-files`
        passes without modifications.
  - [ ] `pyspelling` and `linkchecker` complete with logs stored in `logs/`.
- [ ] **Personal runbook drafted**
  - [ ] `notes/README.md` updated with remote names, workflow summaries, and helper script notes.
  - [ ] `notes/credentials.md` describes how secrets are stored, rotated, and audited.
  - [ ] Tool and doctor transcripts committed to the evidence repository.
- [ ] **Onboarding walkthrough recorded**
  - [ ] Screen capture or screenshot saved in `screenshots/` showing the secret scan execution.
  - [ ] Optional narrated walkthrough exported to `logs/` or linked from the notes file.
  - [ ] Git tag `tutorial-08-environment-ready` created to bookmark the finished environment.

## Next Steps
Once you are comfortable running local automation, continue with the roadmap entry for
[Tutorial 9: Building and Flashing the Sugarkube Pi Image]
(./index.md#tutorial-9-building-and-flashing-the-sugarkube-pi-image).
Publish your lab evidence alongside your pull requests so reviewers can trust the environment you
used.
