# Tutorial 1: Computing Foundations Without Jargon

## Overview
This tutorial introduces the core ideas behind computers using plain language and hands-on practice.
You'll learn how hardware pieces like the CPU, memory, and storage collaborate, and why operating
systems make that hardware useful. We restate and expand on the roadmap goals from the
[Sugarkube Tutorial Roadmap](./index.md#tutorial-1-computing-foundations-without-jargon) so you can
move forward with confidence.

By the end you will be able to identify Raspberry Pi components safely, explain what the command line
is for, and capture a transcript of your first terminal session to use as reference material for later
lessons.

## Prerequisites
* A Raspberry Pi (or printed diagram) you can inspect without powering on.
* Anti-static work surface or mat, plus an optional wrist strap.
* Internet access to launch a browser-based Linux sandbox such as
  [CoderPad Sandbox](https://coderpad.io/sandbox/) or [KataCoda playgrounds](https://www.katacoda.com/).
* A notes app or paper notebook to record observations for future tutorials.

If you have never seen a Raspberry Pi before, skim the official
[Raspberry Pi safety guidelines](https://www.raspberrypi.com/documentation/computers/getting-started.html#safety)
before continuing.

## Lab: Meet the Hardware and Explore Linux
Follow the numbered steps in order. Each milestone builds on earlier observations, so take photos or
recordings when prompted.

### 1. Prepare a static-safe workstation
1. Clear a flat surface and lay down your anti-static mat.
2. Place the Raspberry Pi (still unpowered) in front of you alongside a pen and notebook.
3. Put on the wrist strap if you have one and clip it to the mat.

> [!WARNING]
> Always handle exposed circuit boards by the edges. Static discharge can permanently damage chips.
> If you do not have a wrist strap, briefly touch a grounded metal object before picking up the board.

### 2. Identify Raspberry Pi components
1. Use the official [Raspberry Pi 4 diagram](https://datasheets.raspberrypi.com/pi4/raspberry-pi-4-diagram.pdf)
   (or print it) to label each major component.
2. In your notebook, draw a quick sketch of the board. Label the CPU, RAM, USB ports, Ethernet jack,
   power input, microSD slot, and GPIO header.
3. Take a photo of your sketch or the annotated board. Save it as `tutorial-01-hardware.jpg` for the
   milestone checklist.

> [!TIP]
> If you are working with a different Pi model, note any extra components (camera connectors, Wi-Fi
> chips) and jot down their purpose using the datasheet or product page for reference.

### 3. Establish baseline safety notes
1. Note at least three handling rules in your notebook (e.g., "always power down before removing the
   SD card").
2. Highlight any tools you still need to acquire (small screwdriver, spare microSD cards, etc.).
3. Write one question you still have about the hardware so you can research it later.

### 4. Launch a browser-based Linux shell
1. Open your chosen sandbox provider. Create a new shell session running Ubuntu or Debian when
   prompted.
2. Wait for the terminal prompt (it usually ends with `$`).
3. Type `pwd` and press <kbd>Enter</kbd> to confirm you start in your home directory.

```
pwd
```

4. Run the following commands one by one. After each command, copy the output into your notebook or a
   text document labeled `tutorial-01-terminal-log.txt`.

```
uname -a
ls
mkdir first-tutorial
cd first-tutorial
ls -a
cat <<'LOG' > session-notes.txt
My first Sugarkube terminal session
------------------------------
I can create files, list directories, and record logs.
LOG
cat session-notes.txt
```

> [!NOTE]
> If the sandbox disconnects or times out, reconnect and repeat the commands. Many free playgrounds
> recycle terminals after a few idle minutes.

### 5. Document your discoveries
1. Copy the full terminal transcript into your notebook or knowledge base.
2. Summarize what `pwd`, `ls`, and `mkdir` do in your own words.
3. Save a screenshot of the terminal showing the `session-notes.txt` contents as `tutorial-01-terminal.png`.
4. Add both the photo and screenshot to a folder named `sugarkube-tutorial-01` on your computer or
   cloud drive.

## Milestone Checklist
Check off each task when you have evidence stored in your notes folder.

- [ ] **Tour real hardware:** Photo of the Raspberry Pi or sketch with all major components labeled.
- [ ] **Practice in a browser sandbox:** Saved transcript (`tutorial-01-terminal-log.txt`) showing the
      commands listed in Step 4 and the resulting output.
- [ ] **Summarize key terms:** Written definitions of `CPU`, `memory`, `storage`, `operating system`,
      `pwd`, `ls`, and `mkdir` in your notes or knowledge base.

## Troubleshooting
> [!QUESTION]
> **The sandbox terminal will not start. What should I do?**
>
> Try a different provider (CoderPad, KataCoda, or [Google Cloud Shell](https://shell.cloud.google.com/)).
> Check that your browser allows pop-ups and third-party cookies for the site. If problems persist,
> capture a screenshot of the error and search the provider's status page for outages.

> [!QUESTION]
> **I am unsure whether a component on the board is safe to touch.**
>
> Cross-reference the board diagram. If the component is metallic and near the GPIO header or power
> circuitry, assume it may carry voltage. Wait until the Pi is completely powered off and disconnected
> before touching it. When in doubt, ask in the Raspberry Pi forums with a photo attached.

## Next Steps
Continue with the roadmap by reading
[Tutorial 2: Navigating Linux and the Terminal](./index.md#tutorial-2-navigating-linux-and-the-terminal)
once it is published. Bring your terminal transcript and safety notes—they will inform the follow-up
lessons on permissions, editors, and scripting.
