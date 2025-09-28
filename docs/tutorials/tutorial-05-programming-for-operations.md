# Tutorial 5: Programming for Operations with Python and Bash

## Overview
This tutorial follows the [Sugarkube Tutorial Roadmap](./index.md#tutorial-5-programming-for-operations-with-python-and-bash)
by teaching you how to translate day-to-day operations tasks into repeatable scripts. You will learn
when to reach for Bash, when Python is a better fit, and how to combine both to automate Sugarkube
workflows without breaking project standards. The hands-on lab builds a monitoring helper from
scratch, instruments it with logging, and validates behaviour with tests so you are confident editing
real repository automation later in the series.

By the end you will have:
* Configured a dedicated workspace with shell aliases, a Python virtual environment, and `pre-commit`.
* Written a Bash status collector that records system health data for Sugarkube Pis.
* Authored a Python wrapper that parses the Bash output, enforces safety checks, and prints structured
  JSON.
* Captured evidence—logs, screenshots, and test results—aligned with the roadmap milestones.

## Prerequisites
* Completed artifacts from [Tutorial 1](./tutorial-01-computing-foundations.md): your hardware safety
  notes and component labels help you interpret system readings.
* Terminal transcript and navigation skills from [Tutorial 2](./tutorial-02-navigating-linux-terminal.md).
* Networking diagram from [Tutorial 3](./tutorial-03-networking-internet-basics.md) to validate hostnames
  referenced in scripts.
* Git and GitHub workflow practice from [Tutorial 4](./tutorial-04-version-control-collaboration.md) so
  you can version-control the lab repository and share findings.
* Python 3.11 or newer and `pip`. Follow the
  [official installation instructions](https://www.python.org/downloads/) for your platform if needed.
* Optional but recommended: [Visual Studio Code](https://code.visualstudio.com/) or another editor with
  integrated terminal support for quicker iteration.

> [!TIP]
> If you cannot install Python locally, use [GitHub Codespaces](https://github.com/features/codespaces)
> or [PythonAnywhere](https://www.pythonanywhere.com/) to access a managed shell. The commands below
> are cross-platform and work in those environments.

## Lab: Build an Operations Helper from Bash to Python
Follow the steps sequentially. Store all artifacts (terminal transcripts, screenshots, JSON output) in
`~/sugarkube-tutorials/tutorial-05/` so you can reference them during reviews.

### 1. Create and document your workspace
1. Open a terminal.
2. Create the lab directory and initialise a Git repository:

   ```bash
   mkdir -p ~/sugarkube-tutorials/tutorial-05
   cd ~/sugarkube-tutorials/tutorial-05
   git init
   ```

3. Configure a project-specific `.gitignore` to avoid committing temporary files:

   ```bash
   cat <<'GITIGNORE' > .gitignore
   __pycache__/
   .venv/
   *.log
   *.json
   transcripts/
   screenshots/
   GITIGNORE
   ```

4. Record a workspace README:

   ```bash
   cat <<'README' > README.md
   # Tutorial 5 Lab Workspace

   This repository stores my exercises for Sugarkube Tutorial 5.
   README
   ```

5. Capture a `git status` screenshot showing the untracked files. Save it as
   `screenshots/step-1-status.png`.
6. Stage and commit the scaffolding:

   ```bash
   git add .
   git commit -m "Initialise tutorial 5 workspace"
   ```

> [!WARNING]
> Keep the repository private if you record hostnames or internal IP addresses in future steps.
> Sanitise any sensitive values before sharing artifacts publicly.

### 2. Prepare the shell environment
1. Create helper directories for logs and transcripts:

   ```bash
   mkdir -p logs transcripts
   ```

2. Define aliases that mirror Sugarkube scripts. Append to `~/.bashrc` (or `~/.zshrc`):

   ```bash
   cat <<'ALIASES' >> ~/.bashrc
   alias sk-status="bash ~/sugarkube-tutorials/tutorial-05/scripts/sk-status.sh"
   alias sk-python="python ~/sugarkube-tutorials/tutorial-05/scripts/sk_status.py"
   ALIASES
   ```

   Reload your shell: `source ~/.bashrc`.

3. Document the aliases in your lab README so future you understands their purpose:

   ```bash
   cat <<'DOC' >> README.md

   ## Aliases
   - `sk-status`: Runs the Bash system status collector.
   - `sk-python`: Executes the Python JSON converter for status reports.
   DOC
   ```

4. Stage and commit the documentation update:

   ```bash
   git add README.md
   git commit -m "Document shell aliases for tutorial helpers"
   ```

> [!NOTE]
> If you cannot modify your shell profile (e.g., in a managed classroom environment), create a shell
> script called `enter-env.sh` that exports the aliases each time you start work. Record the workaround
> in `README.md`.

### 3. Build the Bash status collector
1. Create a `scripts/` directory:

   ```bash
   mkdir -p scripts
   ```

2. Draft the Bash script:

   ```bash
   cat <<'SCRIPT' > scripts/sk-status.sh
   #!/usr/bin/env bash
   set -euo pipefail

   LOG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../logs && pwd)"
   TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
   LOG_FILE="$LOG_DIR/status-$TIMESTAMP.log"

   {
     echo "timestamp=$TIMESTAMP"
     echo "hostname=$(hostname)"
     echo "uptime=$(uptime -p)"
     echo "load_average=$(uptime | awk -F 'load average: ' '{print $2}')"
     echo "disk_usage=$(df -h / | tail -1 | awk '{print $5}')"
     echo "memory_usage=$(free -h | awk '/Mem:/ {print $3 "/" $2}')"
     echo "k3s_service_status=$(systemctl is-active k3s 2>/dev/null || echo unknown)"
   } | tee "$LOG_FILE"

   echo "Log written to $LOG_FILE" >&2
   SCRIPT
   ```

3. Make it executable: `chmod +x scripts/sk-status.sh`.
4. Run the script and capture output:

   ```bash
   scripts/sk-status.sh | tee transcripts/step-3-status.txt
   ```

5. Review the generated log file under `logs/` to confirm the metrics match your expectations. Add a
   note to `README.md` summarising any anomalies.
6. Stage and commit your progress:

   ```bash
   git add scripts/sk-status.sh README.md logs/ transcripts/
   git commit -m "Add Bash status collector script"
   ```

> [!TIP]
> If `systemctl` is unavailable (common in containerised shells), replace that line with
> `echo "k3s_service_status=not_applicable"`. Document the change in `README.md` so reviewers know why
> the field differs.

### 4. Create a Python virtual environment and install tooling
1. Set up the environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   ```

2. Install dependencies:

   ```bash
   pip install click rich
   pip install pytest
   pip install pre-commit
   ```

3. Freeze versions for reproducibility:

   ```bash
   pip freeze > requirements.txt
   ```

4. Register `pre-commit` hooks:

   ```bash
   cat <<'PRECOMMIT' > .pre-commit-config.yaml
   repos:
     - repo: https://github.com/psf/black
       rev: 24.8.0
       hooks:
         - id: black
           language_version: python3
     - repo: https://github.com/PyCQA/flake8
       rev: 7.1.1
       hooks:
         - id: flake8
     - repo: https://github.com/pre-commit/mirrors-mypy
       rev: v1.11.1
       hooks:
         - id: mypy
           additional_dependencies: [click, rich]
   PRECOMMIT
   pre-commit install
   ```

5. Document how to activate the environment in `README.md` and commit the changes:

   ```bash
   cat <<'DOC' >> README.md

   ## Python Environment
   1. Run `source .venv/bin/activate`.
   2. Execute `pre-commit run --all-files` before each commit.
   3. Use `pytest` to validate the Python wrapper.
   DOC

   git add .pre-commit-config.yaml requirements.txt README.md
   git commit -m "Configure Python environment with pre-commit"
   ```

> [!WARNING]
> Keep the virtual environment inside the project folder so you can remove it later with
> `rm -rf .venv`. Do not commit the directory—`pip freeze` captures everything you need for
> reproducibility.

### 5. Write the Python status parser
1. Create the Python script:

   ```bash
   cat <<'PYTHON' > scripts/sk_status.py
   """Convert Sugarkube status logs into structured JSON."""

   from __future__ import annotations

   import json
   import pathlib
   from typing import Dict

   import click
   from rich.console import Console
   from rich.table import Table

   console = Console()


   def parse_status_file(path: pathlib.Path) -> Dict[str, str]:
       """Parse key=value lines from a status log file."""
       data: Dict[str, str] = {}
       for line in path.read_text().splitlines():
           if "=" not in line:
               continue
           key, value = line.split("=", maxsplit=1)
           data[key.strip()] = value.strip()
       return data


   def validate_metrics(data: Dict[str, str]) -> None:
       """Raise a click.ClickException if required metrics are missing."""
       required_keys = {"timestamp", "hostname", "disk_usage", "memory_usage"}
       missing = required_keys - data.keys()
       if missing:
           raise click.ClickException(
               f"Status report is missing required keys: {', '.join(sorted(missing))}"
           )


   def display_table(data: Dict[str, str]) -> None:
       table = Table(title="Sugarkube Status Report", show_header=True, header_style="bold cyan")
       table.add_column("Metric", style="bold")
       table.add_column("Value", overflow="fold")
       for key, value in sorted(data.items()):
           table.add_row(key, value)
       console.print(table)


   @click.command()
   @click.argument("status_file", type=click.Path(exists=True, path_type=pathlib.Path))
   @click.option(
       "--json-output",
       "json_output",
       type=click.Path(path_type=pathlib.Path),
       help="Optional path to write a JSON copy of the report.",
   )
   def main(status_file: pathlib.Path, json_output: pathlib.Path | None) -> None:
       """Load a Sugarkube status log and print structured output."""
       data = parse_status_file(status_file)
       validate_metrics(data)
       display_table(data)
       if json_output:
           json_output.write_text(json.dumps(data, indent=2))
           console.print(f"[green]JSON saved to {json_output}")


   if __name__ == "__main__":
       main()
   PYTHON
   ```

2. Ensure the script is executable:

   ```bash
   chmod +x scripts/sk_status.py
   ```

3. Run the parser against the latest log:

   ```bash
   latest_log=$(ls logs/status-*.log | sort | tail -n 1)
   scripts/sk_status.py "$latest_log" --json-output reports/latest-status.json
   ```

   Create the `reports/` directory first if it does not exist.

4. Inspect the JSON output and take a screenshot of the rich table rendered in your terminal.
5. Stage and commit:

   ```bash
   git add scripts/sk_status.py reports/ README.md
   git commit -m "Add Python status parser with JSON export"
   ```

> [!NOTE]
> `click.ClickException` provides user-friendly error messages. If the parser fails, capture the
> traceback and include it in `transcripts/` so you can troubleshoot later.

### 6. Add automated tests
1. Create a tests directory with sample data:

   ```bash
   mkdir -p tests/samples
   cat <<'SAMPLE' > tests/samples/status.log
   timestamp=2024-01-01T00:00:00Z
   hostname=sugarkube-lab
   uptime=up 1 hour, 2 minutes
   load_average=0.10, 0.05, 0.01
   disk_usage=42%
   memory_usage=512M/1G
   k3s_service_status=active
   SAMPLE
   ```

2. Write unit tests using `pytest`:

   ```bash
   cat <<'TESTS' > tests/test_sk_status.py
   """Unit tests for the Sugarkube status parser."""

   from __future__ import annotations

   import pathlib

   import pytest

   from scripts.sk_status import parse_status_file, validate_metrics


   def test_parse_status_file(tmp_path: pathlib.Path) -> None:
       sample = tmp_path / "status.log"
       sample.write_text("hostname=pi\nload_average=0.01, 0.02, 0.03\n")
       result = parse_status_file(sample)
       assert result == {
           "hostname": "pi",
           "load_average": "0.01, 0.02, 0.03",
       }


   def test_validate_metrics_passes_with_required_keys() -> None:
       data = {
           "timestamp": "2024-01-01T00:00:00Z",
           "hostname": "pi",
           "disk_usage": "42%",
           "memory_usage": "512M/1G",
       }
       validate_metrics(data)


   def test_validate_metrics_raises_when_missing() -> None:
       data = {"hostname": "pi"}
       with pytest.raises(Exception) as excinfo:
           validate_metrics(data)
       assert "missing required keys" in str(excinfo.value)
   TESTS
   ```

3. Run tests and hooks:

   ```bash
   source .venv/bin/activate
   pytest
   pre-commit run --all-files
   ```

4. Stage and commit:

   ```bash
   git add tests/
   git commit -m "Add pytest coverage for status parser"
   ```

> [!TIP]
> If `pytest` or `pre-commit` fails, read the error carefully. Fix the root cause before re-running.
> Document the troubleshooting steps in `README.md` or a `transcripts/` entry for future reference.

### 7. Share results and clean up
1. Generate a final status report and archive evidence:

   ```bash
   scripts/sk-status.sh | tee transcripts/final-status.txt
   latest_log=$(ls logs/status-*.log | sort | tail -n 1)
   scripts/sk_status.py "$latest_log" --json-output reports/final-status.json
   ```

2. Run `pytest` and `pre-commit run --all-files` one last time. Capture the output to
   `transcripts/final-tests.txt` using `tee`.
3. Push the repository to GitHub or attach it to your learning journal so mentors can review.
4. Deactivate the virtual environment when finished: `deactivate`.

> [!WARNING]
> Before deleting the workspace, copy your `logs/`, `reports/`, and `transcripts/` directories to
> backup storage. They prove you completed each milestone.

## Milestone Checklist
Use this list to confirm you met the roadmap goals. Mark each item with `[x]` when complete.

- [ ] Instrumented the Bash status collector with logging and saved at least two log files.
- [ ] Captured a `rich` table screenshot from the Python parser and archived the JSON output.
- [ ] Achieved clean `pytest` and `pre-commit` runs recorded in `transcripts/final-tests.txt`.
- [ ] Documented troubleshooting steps or environment adjustments in `README.md`.
- [ ] Shared the lab repository or exported evidence for mentor review.

## Next Steps
Proceed to [Tutorial 6: Raspberry Pi Hardware and Power Design](./index.md#tutorial-6-raspberry-pi-hardware-and-power-design).
The hardware-focused guide is published—review its tool checklist and lab safety reminders so you can
transition smoothly into the next build. Regression coverage lives in
`tests/test_tutorial_05_next_steps.py` to keep this hand-off accurate as the tutorials evolve.
