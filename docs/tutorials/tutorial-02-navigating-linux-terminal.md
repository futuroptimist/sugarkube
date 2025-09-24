# Tutorial 2: Navigating Linux and the Terminal

## Overview
This tutorial builds practical Linux terminal skills so you can move through the filesystem,
inspect running programs, and automate routine status checks with confidence. It extends the roadmap
goals from the [Sugarkube Tutorial Roadmap](./index.md#tutorial-2-navigating-linux-and-the-terminal)
by translating each milestone into a guided lab you can complete on any Ubuntu- or Debian-based
sandbox.

By the end you will have a personal "day in the life" command map, a repeatable permissions
troubleshooting checklist, and a reusable shell script that reports key system information for future
Sugarkube work.

## Prerequisites
* Complete [Tutorial 1](./tutorial-01-computing-foundations.md) and bring the terminal transcript you
  saved.
* Access to a Linux shell with Bash, `sudo`, and `nano` or `vim`. Free options include
  [CoderPad Sandbox](https://coderpad.io/sandbox/),
  [KataCoda playgrounds](https://www.katacoda.com/), or
  [Google Cloud Shell](https://shell.cloud.google.com/).
* A GitHub or GitLab account (or local notes app) to publish your command map once the lab ends.
* At least 90 minutes of focused time—you will run several commands and capture screenshots.

If your environment does not grant `sudo`, note it in your lab log and perform the commands that do
not require elevated privileges. You will still complete the tutorial by documenting what changed.

## Lab: Master Day-to-Day Terminal Tasks
Work through each section in order. Copy every command you run into a text file or Markdown note
named `tutorial-02-terminal-log.md` so you can reference it later.

### 1. Create a dedicated workspace and start logging
1. Launch your Linux environment and confirm you see a shell prompt ending in `$` or `#`.
2. Start an automatic session log so you do not miss any output:

   ```bash
   mkdir -p ~/sugarkube-tutorials/tutorial-02
   cd ~/sugarkube-tutorials/tutorial-02
   script --quiet day-in-the-life.log
   ```

3. Leave the `script` session running; everything you type until you exit will be recorded.
4. Create a Markdown note to collect summaries for the milestone checklist:

   ```bash
   cat <<'EOF_NOTE' > milestone-notes.md
   # Tutorial 2 Notes

   ## Command Map Ideas

   ## Permissions Lab Findings

   ## Status Script Output
   EOF_NOTE
   ```

> [!TIP]
> The `script` command writes a literal transcript to `day-in-the-life.log`. If you make a mistake,
> type it again—having the correction in the log mirrors real troubleshooting.

### 2. Map the filesystem hierarchy
1. Print your current directory and capture the structure around it:

   ```bash
   pwd
   ls -al
   ls -al /
   ```

2. Investigate key locations and note their purpose in `milestone-notes.md` under **Command Map Ideas**:

   ```bash
   ls -al /etc
   ls -al /var
   ls -al /home
   ```

3. Generate a compact directory tree for your workspace (install `tree` if necessary):

   ```bash
   sudo apt-get update && sudo apt-get install -y tree
   tree -L 2 ~
   ```

> [!WARNING]
> Running `sudo apt-get update` modifies package caches. Only run it in disposable sandboxes or
> systems you administer. Skip the command if `sudo` is unavailable; instead, run `find ~ -maxdepth 2
> -type d` to list directories.

4. Append a short explanation for `/etc`, `/var`, `/home`, and `~/sugarkube-tutorials` to your
   milestone notes. Mention at least one command you would use in each location.

### 3. Explore help systems and package managers
1. Open a manual page and record what each section means:

   ```bash
   man ls
   ```

   Scroll with <kbd>Space</kbd>, quit with <kbd>q</kbd>, then summarize three useful flags under
   **Command Map Ideas**.

2. Search for a package and inspect its description without installing it:

   ```bash
   apt-cache search htop | head -n 5
   apt-cache show htop | grep -E '^(Package|Description)'
   ```

3. Review command history to reinforce what you have tried so far:

   ```bash
   history | tail -n 20
   ```

> [!NOTE]
> History output includes the commands you are running right now. Copy the relevant entries into
> `tutorial-02-terminal-log.md` with brief annotations so future-you remembers why they mattered.

### 4. Practice with a text editor
1. Use `nano` (or `vim` if you prefer) to describe a "day in the life" workflow:

   ```bash
   nano command-map.md
   ```

2. Write three short sections separated by headings:
   * **Filesystem navigation** – list commands like `pwd`, `ls`, and `tree` with when to use them.
   * **Package management** – note what `sudo`, `apt-get`, and `apt-cache` accomplish.
   * **Editor skills** – mention how to open, save, and exit your chosen editor.

3. Save the file (<kbd>Ctrl</kbd> + <kbd>O</kbd>, <kbd>Enter</kbd>, then <kbd>Ctrl</kbd> + <kbd>X</kbd> in
   `nano`).
4. Show the rendered Markdown to confirm formatting:

   ```bash
   cat command-map.md
   ```

> [!QUESTION]
> **`nano` says the file is modified but will not save. What now?**
>
> Ensure you have write permission to the directory (`ls -ld .`). If the permissions show `r-x`, run
> `chmod u+w .` to grant yourself write access before retrying.

### 5. Complete a permissions troubleshooting lab
1. Create a mock service directory with intentionally restrictive permissions:

   ```bash
   sudo mkdir -p /srv/mock-service
   sudo touch /srv/mock-service/status.txt
   sudo chmod 400 /srv/mock-service/status.txt
   sudo chown root:root /srv/mock-service/status.txt
   ```

2. Attempt to append data as your regular user (it should fail):

   ```bash
   echo "service ok" >> /srv/mock-service/status.txt
   ```

3. Record the error message in `milestone-notes.md` under **Permissions Lab Findings**.
4. Fix the issue by granting group write access and assigning the current user to a dedicated group:

   ```bash
   sudo groupadd --force mocksvc
   sudo usermod -aG mocksvc "$USER"
   sudo chown root:mocksvc /srv/mock-service/status.txt
   sudo chmod 660 /srv/mock-service/status.txt
   ```

5. Open a new terminal tab or run `newgrp mocksvc` so the group change takes effect, then retry the
   append:

   ```bash
   echo "service ok" >> /srv/mock-service/status.txt
   cat /srv/mock-service/status.txt
   ```

6. Document the final permissions with `ls -l /srv/mock-service` and explain in your notes why the fix
   worked.

> [!IMPORTANT]
> Modifying system groups affects the current environment. Perform this step only on a disposable VM
> or sandbox account. If you cannot add groups, mimic the exercise inside `~/mock-service` and adjust
> ownership with `chown "$USER":"$USER"` instead of `root:mocksvc`.

### 6. Write a reusable status script
1. Create a Bash script that gathers system information:

   ```bash
   cat <<'EOF_SCRIPT' > status-report.sh
   #!/usr/bin/env bash
   set -euo pipefail

   printf "Sugarkube Status Report\n"
   printf "Generated: %s\n\n" "$(date -Is)"

  printf "## System Identity\n"
  if command -v hostnamectl >/dev/null 2>&1; then
    if ! hostnamectl; then
      printf "hostnamectl unavailable (non-systemd environment)\n"
      hostname
    fi
  else
    hostname
  fi
   printf "\n## Uptime\n"
   uptime
   printf "\n## Disk Usage (/)\n"
   df -h /
   printf "\n## Top Processes\n"
   ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -n 6
   EOF_SCRIPT
   ```

2. Make it executable and run it:

   ```bash
   chmod +x status-report.sh
   ./status-report.sh | tee latest-status.txt
   ```

> [!NOTE]
> In container-based labs without `systemd`, `hostnamectl` exits with an error. The script detects
> this and falls back to `hostname` while printing a reminder that `hostnamectl` was unavailable.

3. Copy the command output into `milestone-notes.md` under **Status Script Output**.
4. Exit the `script` session so `day-in-the-life.log` saves cleanly:

   ```bash
   exit
   ```

5. Confirm the transcript exists and view the final lines:

   ```bash
   ls
   tail -n 20 day-in-the-life.log
   ```

> [!TIP]
> Store `status-report.sh` in a version control repository once you learn Git in a later tutorial.
> Having a history of edits makes it easier to share improvements with teammates.

### 7. Publish or archive your work
1. Zip your tutorial folder so you can upload it or store it safely:

   ```bash
   cd ~
   zip -r tutorial-02-artifacts.zip sugarkube-tutorials/tutorial-02
   ```

2. Post `command-map.md` to a private gist or save it in your knowledge base.
3. Take a screenshot showing `status-report.sh` running and attach it to the notes repository or gist.
4. Record the storage location (URL or folder path) in `milestone-notes.md`.

## Milestone Checklist
Complete each item before moving on.

- [ ] **Build a "day in the life" command map:** `command-map.md` saved, plus bullet summaries for
      `/etc`, `/var`, `/home`, and your workspace in `milestone-notes.md`.
- [ ] **Permissions troubleshooting lab:** `day-in-the-life.log` contains the failed append, the group
      fix commands, and `ls -l /srv/mock-service` output showing `root mocksvc` (or your equivalent
      sandbox user) with `rw-rw----` permissions.
- [ ] **Status script ready for review:** `status-report.sh` executes without error, `latest-status.txt`
      captures the output, and your notes reference where collaborators can download or view it.

## Troubleshooting
> [!QUESTION]
> **`sudo apt-get install -y tree` fails with a lock error. What should I do?**
>
> Another package process might be running. Wait a minute and rerun the command. If it still fails,
> run `sudo lsof /var/lib/dpkg/lock-frontend` to identify the blocking process and terminate it with
> `sudo kill <PID>` when safe. In locked-down sandboxes, skip the install and use `find` as suggested
> earlier.

> [!QUESTION]
> **I cannot run `newgrp mocksvc` because the command is missing.**
>
> Some minimal images omit `newgrp`. Log out and back in, or open a fresh terminal window so your group
> membership refreshes. If that is impossible, recreate the lab inside your home directory and adjust
> ownership with `chown "$USER":"$USER"`.

## Next Steps
When you are ready, continue the roadmap with
[Tutorial 3: Networking and the Internet Basics](./index.md#tutorial-3-networking-and-the-internet-basics)
once it is published. Bring `latest-status.txt` and your permissions notes—they will help you
understand how network services surface in real system reports.
