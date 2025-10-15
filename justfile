set shell := ["bash", "-euo", "pipefail", "-c"]

image_dir := env_var_or_default("IMAGE_DIR", env_var("HOME") + "/sugarkube/images")
image_name := env_var_or_default("IMAGE_NAME", "sugarkube.img")
image_path := image_dir + "/" + image_name
install_cmd := env_var_or_default("INSTALL_CMD", justfile_directory() + "/scripts/install_sugarkube_image.sh")
flash_cmd := env_var_or_default("FLASH_CMD", justfile_directory() + "/scripts/flash_pi_media.sh")
flash_report_cmd := env_var_or_default("FLASH_REPORT_CMD", justfile_directory() + "/scripts/flash_pi_media_report.py")
download_cmd := env_var_or_default("DOWNLOAD_CMD", justfile_directory() + "/scripts/download_pi_image.sh")
download_args := env_var_or_default("DOWNLOAD_ARGS", "")
flash_args := env_var_or_default("FLASH_ARGS", "--assume-yes")
flash_report_args := env_var_or_default("FLASH_REPORT_ARGS", "")
flash_device := env_var_or_default("FLASH_DEVICE", "")
rollback_cmd := env_var_or_default("ROLLBACK_CMD", justfile_directory() + "/scripts/rollback_to_sd.sh")
rollback_args := env_var_or_default("ROLLBACK_ARGS", "")
clone_cmd := env_var_or_default("CLONE_CMD", justfile_directory() + "/scripts/ssd_clone.py")
clone_args := env_var_or_default("CLONE_ARGS", "")
clone_target := env_var_or_default("CLONE_TARGET", "")
validate_cmd := env_var_or_default("VALIDATE_CMD", justfile_directory() + "/scripts/ssd_post_clone_validate.py")
validate_args := env_var_or_default("VALIDATE_ARGS", "")
qr_cmd := env_var_or_default("QR_CMD", justfile_directory() + "/scripts/generate_qr_codes.py")
qr_args := env_var_or_default("QR_ARGS", "")
health_cmd := env_var_or_default("HEALTH_CMD", justfile_directory() + "/scripts/ssd_health_monitor.py")
health_args := env_var_or_default("HEALTH_ARGS", "")
smoke_cmd := env_var_or_default("SMOKE_CMD", justfile_directory() + "/scripts/pi_smoke_test.py")
smoke_args := env_var_or_default("SMOKE_ARGS", "")
qemu_smoke_cmd := env_var_or_default("QEMU_SMOKE_CMD", justfile_directory() + "/scripts/qemu_pi_smoke_test.py")
qemu_smoke_args := env_var_or_default("QEMU_SMOKE_ARGS", "")
qemu_smoke_image := env_var_or_default("QEMU_SMOKE_IMAGE", "")
qemu_smoke_artifacts := env_var_or_default("QEMU_SMOKE_ARTIFACTS", justfile_directory() + "/artifacts/qemu-smoke")
support_bundle_cmd := env_var_or_default("SUPPORT_BUNDLE_CMD", justfile_directory() + "/scripts/collect_support_bundle.py")
support_bundle_args := env_var_or_default("SUPPORT_BUNDLE_ARGS", "")
support_bundle_host := env_var_or_default("SUPPORT_BUNDLE_HOST", "")
field_guide_cmd := env_var_or_default("FIELD_GUIDE_CMD", justfile_directory() + "/scripts/render_field_guide_pdf.py")
field_guide_args := env_var_or_default("FIELD_GUIDE_ARGS", "")
telemetry_cmd := env_var_or_default("TELEMETRY_CMD", justfile_directory() + "/scripts/publish_telemetry.py")
telemetry_args := env_var_or_default("TELEMETRY_ARGS", "")
teams_cmd := env_var_or_default("TEAMS_CMD", justfile_directory() + "/scripts/sugarkube_teams.py")
teams_args := env_var_or_default("TEAMS_ARGS", "")
workflow_notify_cmd := env_var_or_default("WORKFLOW_NOTIFY_CMD", justfile_directory() + "/scripts/workflow_artifact_notifier.py")
workflow_notify_args := env_var_or_default("WORKFLOW_NOTIFY_ARGS", "")
badge_cmd := env_var_or_default("BADGE_CMD", justfile_directory() + "/scripts/update_hardware_boot_badge.py")
badge_args := env_var_or_default("BADGE_ARGS", "")
rehearsal_cmd := env_var_or_default("REHEARSAL_CMD", justfile_directory() + "/scripts/pi_multi_node_join_rehearsal.py")
rehearsal_args := env_var_or_default("REHEARSAL_ARGS", "")
cluster_cmd := env_var_or_default("CLUSTER_CMD", justfile_directory() + "/scripts/pi_multi_node_join_rehearsal.py")
cluster_args := env_var_or_default("CLUSTER_ARGS", "")
cluster_bootstrap_args := env_var_or_default("CLUSTER_BOOTSTRAP_ARGS", "")
token_place_sample_cmd := env_var_or_default("TOKEN_PLACE_SAMPLE_CMD", justfile_directory() + "/scripts/token_place_replay_samples.py")
token_place_sample_args := env_var_or_default("TOKEN_PLACE_SAMPLE_ARGS", "--samples-dir " + justfile_directory() + "/samples/token_place")
mac_setup_cmd := env_var_or_default("MAC_SETUP_CMD", justfile_directory() + "/scripts/sugarkube_setup.py")
mac_setup_args := env_var_or_default("MAC_SETUP_ARGS", "")
start_here_args := env_var_or_default("START_HERE_ARGS", "")
sugarkube_cli := env_var_or_default("SUGARKUBE_CLI", justfile_directory() + "/scripts/sugarkube")
docs_verify_args := env_var_or_default("DOCS_VERIFY_ARGS", "")
simplify_docs_args := env_var_or_default("SIMPLIFY_DOCS_ARGS", "")

_default:
    @just --list

help:
    @just --list

# Download the latest release or a specific asset into IMAGE_DIR

# Usage: just download-pi-image DOWNLOAD_ARGS="--release v1.2.3"
download-pi-image:
    "{{ download_cmd }}" --dir "{{ image_dir }}" {{ download_args }}

# Expand an image into IMAGE_PATH, downloading releases when missing

# Usage: just install-pi-image DOWNLOAD_ARGS="--release v1.2.3"
install-pi-image:
    "{{ install_cmd }}" --dir "{{ image_dir }}" --image "{{ image_path }}" {{ download_args }}

# Download (via install-pi-image) and flash to FLASH_DEVICE. Run with sudo.

# Usage: sudo just flash-pi FLASH_DEVICE=/dev/sdX
flash-pi: install-pi-image
    if [ -z "{{ flash_device }}" ]; then echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi." >&2; exit 1; fi
    "{{ flash_cmd }}" --image "{{ image_path }}" --device "{{ flash_device }}" {{ flash_args }}

# Download (via install-pi-image) and flash while generating Markdown/HTML reports.

# Usage: sudo just flash-pi-report FLASH_DEVICE=/dev/sdX FLASH_REPORT_ARGS="--cloud-init ~/user-data"
flash-pi-report: install-pi-image
    if [ -z "{{ flash_device }}" ]; then echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi-report." >&2; exit 1; fi
    "{{ flash_report_cmd }}" --image "{{ image_path }}" --device "{{ flash_device }}" {{ flash_args }} {{ flash_report_args }}

# Run the end-to-end readiness checks

# Usage: just doctor
doctor:
    "{{ justfile_directory() }}/scripts/sugarkube_doctor.sh"

# Surface the Start Here handbook in the terminal

# Usage: just start-here START_HERE_ARGS="--path-only"
start-here:
    "{{ sugarkube_cli }}" docs start-here {{ start_here_args }}

# Revert cmdline.txt and fstab entries back to the SD card defaults

# Usage: sudo just rollback-to-sd
rollback-to-sd:
    "{{ rollback_cmd }}" {{ rollback_args }}

# Clone the active SD card to an attached SSD with resume/dry-run helpers
# Usage: sudo just clone-ssd CLONE_TARGET=/dev/sda CLONE_ARGS="--dry-run"
# Note: On Raspberry Pi OS Bookworm, /boot is mounted at /boot/firmware.
#       Run this first to ensure compatibility:

# sudo mkdir -p /boot && sudo mount --bind /boot/firmware /boot
clone-ssd:
    if [ -z "{{ clone_target }}" ]; then echo "Set CLONE_TARGET to the target device (e.g. /dev/sda) before running clone-ssd." >&2; exit 1; fi
    "{{ clone_cmd }}" --target "{{ clone_target }}" {{ clone_args }}

# Run post-clone validation against the active root filesystem

# Usage: sudo just validate-ssd-clone VALIDATE_ARGS="--stress-mb 256"
validate-ssd-clone:
    "{{ validate_cmd }}" {{ validate_args }}

# Collect SMART metrics and wear indicators for the active SSD

# Usage: sudo just monitor-ssd-health HEALTH_ARGS="--tag weekly"
monitor-ssd-health:
    "{{ health_cmd }}" {{ health_args }}

# Run pi_node_verifier remotely over SSH

# Usage: just smoke-test-pi SMOKE_ARGS="pi-a.local --reboot"
smoke-test-pi:
    "{{ smoke_cmd }}" {{ smoke_args }}

# Boot a built sugarkube image inside QEMU and collect first-boot reports

# Usage: sudo just qemu-smoke QEMU_SMOKE_IMAGE=deploy/sugarkube.img
qemu-smoke:
    if [ -z "{{ qemu_smoke_image }}" ]; then echo "Set QEMU_SMOKE_IMAGE to the built image (sugarkube.img or .img.xz)." >&2; exit 1; fi
    sudo "{{ qemu_smoke_cmd }}" --image "{{ qemu_smoke_image }}" --artifacts-dir "{{ qemu_smoke_artifacts }}" {{ qemu_smoke_args }}

# Render the printable Pi carrier field guide PDF

# Usage: just field-guide FIELD_GUIDE_ARGS="--wrap 70"
field-guide:
    "{{ field_guide_cmd }}" {{ field_guide_args }}

# Publish anonymized telemetry payloads once.
publish-telemetry:
    "{{ telemetry_cmd }}" {{ telemetry_args }}

# Send a manual Slack/Matrix notification using sugarkube-teams
notify-teams:
    "{{ teams_cmd }}" {{ teams_args }}

# Watch a workflow run and raise desktop notifications when artifacts are ready

# Usage: just notify-workflow WORKFLOW_NOTIFY_ARGS="--run-url https://github.com/..."
notify-workflow:
    "{{ workflow_notify_cmd }}" {{ workflow_notify_args }}

# Update the hardware boot conformance badge JSON

# Usage: just update-hardware-badge BADGE_ARGS="--status warn --notes 'pi-b'"
update-hardware-badge:
    "{{ badge_cmd }}" {{ badge_args }}

# Run multi-node join rehearsals against control-plane and candidate agents

# Usage: just rehearse-join REHEARSAL_ARGS="controller.local --agents pi-a.local"
rehearse-join:
    "{{ rehearsal_cmd }}" {{ rehearsal_args }}

# Apply the k3s join command to each agent and optionally wait for readiness

# Usage: just cluster-up CLUSTER_ARGS="control.local --agents worker-a worker-b --apply --apply-wait"
cluster-up:
    "{{ cluster_cmd }}" {{ cluster_args }}

# Usage: just cluster-bootstrap CLUSTER_BOOTSTRAP_ARGS="--config cluster.toml"
cluster-bootstrap:
    "{{ sugarkube_cli }}" pi cluster {{ cluster_bootstrap_args }}

# Install CLI dependencies inside GitHub Codespaces or fresh containers

# Usage: just codespaces-bootstrap
codespaces-bootstrap:
    sudo apt-get update
    sudo apt-get install -y \
        aspell \
        aspell-en \
        curl \
        gh \
        jq \
        pv \
        python3 \
        python3-pip \
        python3-venv \
        unzip \
        xz-utils
    python3 -m pip install --user --upgrade pip pre-commit pyspelling linkchecker

# Run spellcheck and linkcheck to keep docs automation aligned

# Usage: just docs-verify
docs-verify:
    "{{ sugarkube_cli }}" docs verify {{ docs_verify_args }}

# Install documentation prerequisites and run spell/link checks without touching

# code linters. Usage: just simplify-docs (forwards to sugarkube docs simplify)
simplify-docs:
    "{{ sugarkube_cli }}" docs simplify {{ simplify_docs_args }}

# Generate printable QR codes that link to the quickstart and troubleshooting docs

# Usage: just qr-codes QR_ARGS="--output-dir ~/qr"
qr-codes:
    "{{ qr_cmd }}" {{ qr_args }}

# Replay bundled token.place sample payloads and write reports

# Usage: just token-place-samples TOKEN_PLACE_SAMPLE_ARGS="--dry-run"
token-place-samples:
    "{{ sugarkube_cli }}" token-place samples {{ token_place_sample_args }}

# Run the macOS setup wizard to install brew formulas and scaffold directories

# Usage: just mac-setup MAC_SETUP_ARGS="--apply"
mac-setup:
    "{{ mac_setup_cmd }}" {{ mac_setup_args }}

# Collect Kubernetes, systemd, and compose diagnostics from a running Pi

# Usage: just support-bundle SUPPORT_BUNDLE_HOST=pi.local
support-bundle:
    if [ -z "{{ support_bundle_host }}" ]; then echo "Set SUPPORT_BUNDLE_HOST to the target host before running support-bundle." >&2; exit 1; fi
    "{{ support_bundle_cmd }}" "{{ support_bundle_host }}" {{ support_bundle_args }}
