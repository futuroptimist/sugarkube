# Tutorial 1: Computing Foundations Without Jargon

## Overview
This beginner-friendly tutorial introduces the physical and conceptual building blocks of computing that power Sugarkube. You will handle real hardware (or high-fidelity stand-ins), learn what each component does, and build a safe workspace before touching any electronics. You will also take your first steps in a Linux shell using a browser-based sandbox so future exercises in the roadmap feel familiar. Review the full series in the [tutorial roadmap](./index.md) to understand how this lesson anchors everything that follows.

By the end, you will be able to describe the purpose of a CPU, memory, and storage, explain why Sugarkube standardizes on Linux, and capture your first command-line transcript for reference.

## Prerequisites
- A computer with a modern web browser (Chrome, Firefox, Edge, or Safari).
- Optional but recommended: access to a Raspberry Pi or printed diagram of its board. Download the latest model diagram from the [Raspberry Pi documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
- No prior technical experience is required.

## Hands-On Lab: From Hardware Tour to Linux Sandbox
Follow each step in order. Do not skip ahead; later tutorials will assume you completed and saved the artifacts produced here.

### 1. Prepare a Static-Safe Workspace (20 minutes)
1. Choose a flat surface with good lighting and minimal clutter.
2. Place a non-conductive mat (cardboard, wooden board, or an anti-static mat) on the surface.
3. Gather the following items:
   - Raspberry Pi board (or printed diagram if you are working remotely).
   - Anti-static wrist strap (optional but encouraged).
   - Small containers for screws and cables.
   - Notebook or digital document titled `sugarkube-lab-notes.md`.
4. Wash and dry your hands to remove oils and static.
5. Clip the anti-static strap to a grounded object (e.g., the metal part of a computer case).

> **Safety Note:** Never work on powered hardware while the power supply is connected. Always unplug cables before touching components.

Capture a photo of your workspace and label it `workspace-setup.jpg`. Store it alongside your lab notes.

### 2. Identify Raspberry Pi Components (25 minutes)
1. Place the Raspberry Pi board (or diagram) on the workspace.
2. Open your lab notes and create a table with two columns: `Component` and `Purpose`.
3. Identify and record the following components:
   - USB ports
   - Ethernet port
   - HDMI ports
   - GPIO header
   - Camera/display connectors
   - Power input
   - MicroSD card slot or onboard storage
   - CPU (usually under a heat spreader)
   - RAM package
4. For each item, write a one-sentence description explaining what it does in everyday language.
5. Add a final row titled `Handling Tips` with bullet points reminding you how to avoid bending pins, applying pressure evenly, and storing the board safely.

> **Troubleshooting:** If you cannot identify a component, search the Raspberry Pi documentation for annotated board diagrams. Double-check you are looking at the correct model revision.

### 3. Understand the Computing Stack (15 minutes)
1. In your lab notes, create a section titled `Computing Stack Overview`.
2. Write three short paragraphs:
   - **Hardware:** Summarize what physical components you inspected above.
   - **Operating System:** Define the role of an OS and why Sugarkube favors Linux.
   - **Applications:** Describe examples of the software you expect Sugarkube to run (e.g., Kubernetes workloads, dashboards).
3. End the section with a bulleted list of new vocabulary terms and definitions. Include at least `CPU`, `RAM`, `Storage`, `Operating System`, and `Command Line`.

### 4. Launch a Browser-Based Linux Terminal (10 minutes)
1. Visit [https://bellard.org/jslinux/](https://bellard.org/jslinux/) in your browser.
2. Select the "Console" option for a lightweight Linux environment.
3. Wait for the boot message `login:` to appear, then enter the default superuser account name
   (spelled `r o o t`) and press **Enter**. The sandbox does not prompt for any credentials.
4. Type `pwd` and press **Enter** to display the current directory.
5. Run `ls` to list files, then `mkdir demo` to create a directory, and `cd demo` to enter it.
6. Create a note by running `cat <<'EOF' > hello.txt` followed by:
   ```
   Sugarkube hello from Tutorial 1!
   EOF
   ```
7. Display the contents with `cat hello.txt`.
8. Type `history` to show the commands you ran.

> **Tip:** If your browser freezes, refresh the page and repeat the commands. Save a screenshot of the terminal showing your command history as `jslinux-history.png`.

### 5. Save Your Transcript Locally (10 minutes)
1. Highlight the entire terminal session output, copy it, and paste it into your lab notes under a heading `Linux Sandbox Transcript`.
2. Add a short reflection (2–3 sentences) describing what felt familiar or surprising.
3. Store the screenshot (`jslinux-history.png`) and transcript in a folder named `tutorial-01-artifacts` alongside `workspace-setup.jpg`.

### 6. Summarize Key Terms in a Shared Glossary (15 minutes)
1. Open your lab notes and add a section titled `Glossary Contributions`.
2. For each vocabulary term from Step 3, rewrite the definition in your own words.
3. Include one additional term you encountered (e.g., `root user`, `directory`).
4. Save the file and back it up to a cloud storage folder or version control system for future reference.

> **Next Tutorial Prep:** Keep your artifacts handy. Tutorial 2 will ask you to revisit the sandbox and extend the glossary.

## Milestone Checklist
Use this checklist to confirm you met the roadmap goals. Mark each item as you complete it.

- [ ] **Hardware tour completed:** Workspace photo saved, Raspberry Pi components labeled with purposes, handling tips recorded.
- [ ] **Sandbox practice captured:** Browser-based Linux session transcript and screenshot saved in `tutorial-01-artifacts/`.
- [ ] **Glossary initialized:** Key terms documented and shared location noted for future tutorials.

## Next Steps
Continue building your skills in [Tutorial 2: Navigating Linux and the Terminal](./tutorial-02-navigating-linux-and-the-terminal.md) once it becomes available. In the meantime, review your lab notes weekly and keep the workspace tidy so you can dive straight into the next exercises.
