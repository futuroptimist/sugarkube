# Tutorial 9: Building and Flashing the Sugarkube Pi Image

## Overview
This guide continues the
[Sugarkube Tutorial Roadmap](./index.md#tutorial-9-building-and-flashing-the-sugarkube-pi-image)
by walking you through the entire image lifecycle. You will run the pi-gen based
builder, normalize the resulting artifacts, capture provenance metadata, and
flash the image onto removable media. The lab mirrors what the automation bots do
so you can rehearse the process locally and understand every safety check.

By the end you will have:
* Confirmed your workstation meets the disk space, Docker, and network
  prerequisites for pi-gen.
* Generated a fresh `sugarkube.img.xz`, checksum, build log, and metadata bundle.
* Practiced flashing the image safely—either in dry-run mode or to a real SD
  card/SSD—with transcripts and screenshots captured for review.

## Prerequisites
* Completed artefacts from [Tutorial 1](./tutorial-01-computing-foundations.md)
  through [Tutorial 8](./tutorial-08-preparing-development-environment.md),
  including your lab journal, network diagrams, Kubernetes sandbox, and local
  clone of the Sugarkube repository.
* A workstation with administrative access, Docker Desktop or Docker Engine
  running, and at least **20 GB** of free disk space.
* Optional but recommended: a spare SD card, USB SSD, or a blank image file to
  practice flashing without risking production media.

> [!WARNING]
> Building and flashing images will erase the target media. Double-check device
> names before running destructive commands. Unplug any drives you do not intend
> to re-image to avoid surprises.

## Lab: Build, Collect, and Flash the Sugarkube Image
Create a new evidence directory `~/sugarkube-labs/tutorial-09/` for this lab. All
logs, screenshots, and transcripts should live under that path so reviewers can
trace your work.

### 1. Prepare the build workspace
1. Open a terminal and create dedicated folders for notes, logs, images, and
   reports:

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-09/{notes,logs,images,reports}
   cd ~/sugarkube-labs/tutorial-09
   ```

2. Record your starting system state for provenance:

   ```bash
   {
     echo "# Tutorial 9 System Snapshot"
     date --iso-8601=seconds
     uname -a
     docker --version
     df -h .
   } > logs/system-snapshot.txt
   ```

3. Verify Docker can run privileged containers (pi-gen needs binfmt):

   ```bash
   docker info --format '{{.ServerVersion}}'
   ```

   If this command fails, restart Docker Desktop or the Docker daemon before
   continuing.

> [!TIP]
> Capture a screenshot of Docker Desktop (or `systemctl status docker`) showing
> it is running. Store the file in `screenshots/` or note its path inside
> `notes/README.md`.

### 2. Sync the Sugarkube sources and stage output directories
1. Reuse the repository clone from Tutorial 8 or clone it again into the lab
   workspace:

   ```bash
   cd ~/sugarkube-labs/tutorial-09
   git clone https://github.com/futuroptimist/sugarkube.git workspace
   cd workspace
   ```

   If you already have a clone elsewhere, document the path in
   `../notes/README.md` and ensure it is up to date (`git pull origin main`).

2. Create a directory to hold build artifacts outside the repository checkout so
   large files do not pollute your Git working tree:

   ```bash
   mkdir -p ../images/build-output
   export OUTPUT_DIR="$(pwd)/../images/build-output"
   ```

3. Examine the available pi-image helper scripts so you know what will run:

   ```bash
   ls scripts | grep pi_image
   ```

   Skim `scripts/build_pi_image.sh` and `docs/pi_image_builder_design.md` to see
   the stages and safety checks the builder performs.

### 3. Run the pi-gen build
1. Start a transcript using `script` so you have a full log later:

   ```bash
   cd ~/sugarkube-labs/tutorial-09/workspace
   script ../logs/build-session.txt
   ```

   The shell prompt will change to indicate logging is active.

2. Launch the build. Set `OUTPUT_DIR` so logs, metadata, and the compressed image
   land in `~/sugarkube-labs/tutorial-09/images/build-output/`:

   ```bash
   OUTPUT_DIR="$OUTPUT_DIR" ./scripts/build_pi_image.sh | tee ../logs/pi-gen-live.log
   ```

   Expect the build to run 30–90 minutes depending on your machine and network.
   The `tee` command mirrors stdout into `../logs/pi-gen-live.log` while still
   displaying progress in the terminal.

> [!NOTE]
> The builder installs ARM binfmt handlers inside Docker. If you are on macOS
> with Colima or Lima, ensure the VM is started and `docker context use default`
> points at the correct daemon.

3. When the build completes, exit the `script` session to finalize the transcript:

   ```bash
   exit
   ```

   Confirm that the following files exist in `../images/build-output/`:

   * `sugarkube.img.xz`
   * `sugarkube.img.xz.sha256`
   * `sugarkube.img.xz.metadata.json`
   * `build.log`

### 4. Review and archive build artifacts
1. Copy a summary of the output directory into your notes:

   ```bash
   ls -lh ../images/build-output > ../notes/artifacts-summary.txt
   ```

2. Inspect the metadata JSON to understand what was captured:

   ```bash
   jq '. | {pi_gen_commit, duration_seconds, options}' \
     ../images/build-output/sugarkube.img.xz.metadata.json
   ```

   Record key values (pi-gen commit, duration, token.place branch) in your lab
   journal so future builds can be compared.

3. Validate the checksum matches the compressed image:

   ```bash
   cd ../images/build-output
   sha256sum --check sugarkube.img.xz.sha256
   cd -
   ```

   Save the command output to `../logs/checksum-verify.txt` using redirection or
   by copying the terminal transcript.

> [!WARNING]
> If the checksum verification fails, do **not** flash the image. Rerun the build
> or investigate disk space, network interruptions, and the pi-gen logs before
> proceeding.

### 5. Practice flashing the image
1. List removable devices detected on your system. This is safe to run without
   sudo and helps you identify the correct path:

   ```bash
   python3 scripts/flash_pi_media.py --list
   ```

   If you are rehearsing without hardware, create a sparse file to act as a fake
   device:

   ```bash
   truncate -s 8G ~/sugarkube-labs/tutorial-09/images/fake-device.img
   ```

2. Perform a dry run first to understand the workflow without touching disks:

   ```bash
   sudo python3 scripts/flash_pi_media.py \
     --image ~/sugarkube-labs/tutorial-09/images/build-output/sugarkube.img.xz \
     --device ~/sugarkube-labs/tutorial-09/images/fake-device.img \
     --dry-run --assume-yes
   ```

   Review the output and save it to `../logs/flash-dry-run.txt`.

3. When you are ready to flash real media, repeat the command **without**
   `--dry-run` and with the correct `/dev/sdX` (Linux), `/dev/diskN` (macOS), or
   `\\.\PhysicalDriveN` (Windows, run from PowerShell). Keep `--assume-yes` so
   the helper prompts for confirmation only when required.

> [!WARNING]
> Triple-check the device path before running the destructive flash step. Use
> `lsblk` (Linux) or `diskutil list` (macOS) to confirm capacity and model. If in
> doubt, stop and re-run the dry-run command while you verify cabling.

4. Generate an HTML evidence report that captures the flashing session, checksum
   validation, and media details:

   ```bash
   python3 scripts/flash_pi_media_report.py \
     --image ~/sugarkube-labs/tutorial-09/images/build-output/sugarkube.img.xz \
     --device <your-device-path-or-fake-file> \
     --output-dir ~/sugarkube-labs/tutorial-09/reports \
     --assume-yes
   ```

   The script will prompt you to confirm the target if it is a real disk. When it
   finishes, open the generated `.html` file in a browser and capture a
   screenshot for your notes.

### 6. Package evidence for reviewers
1. Update `~/sugarkube-labs/tutorial-09/notes/README.md` with:
   * The commands you ran and timestamps.
   * Links to transcripts (`build-session.txt`, `pi-gen-live.log`).
   * Checksums, device identifiers, and any troubleshooting you performed.

2. Create a compressed archive so you can share the lab bundle during reviews:

   ```bash
   cd ~/sugarkube-labs
   tar -czf tutorial-09-evidence.tar.gz tutorial-09
   ```

   Store the archive in a safe location or upload it to your team’s evidence
   storage, following the security practices from earlier tutorials.

## Milestone Checklist
Use this list to confirm you met each objective before moving on. Check off items
as you complete them.

- [ ] Executed a full pi-gen build, archived the compressed image, build log,
      checksum, and metadata in your lab workspace.
- [ ] Flashed the image using two methods (dry-run or fake device counts as one),
      verified checksums, and documented any deviations.
- [ ] Published a reusable flashing checklist or evidence package others can
      follow, including screenshots and transcripts.

## Next Steps
Proceed to [Tutorial 10: First Boot, Verification, and Self-Healing](./index.md#tutorial-10-first-boot-verification-and-self-healing)
once it is published. You will boot the image you created here, run the verifier,
and observe Sugarkube’s self-healing services in action.
