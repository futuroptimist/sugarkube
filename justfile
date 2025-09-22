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
telemetry_cmd := env_var_or_default(
    "TELEMETRY_CMD",
    justfile_directory() + "/scripts/publish_telemetry.py",
)
telemetry_args := env_var_or_default("TELEMETRY_ARGS", "")
badge_cmd := env_var_or_default(
    "BADGE_CMD",
    justfile_directory() + "/scripts/update_hardware_boot_badge.py",
)
badge_args := env_var_or_default("BADGE_ARGS", "")

_default:
    @just --list

help:
    @just --list

# Download the latest release or a specific asset into IMAGE_DIR
# Usage: just download-pi-image DOWNLOAD_ARGS="--release v1.2.3"
download-pi-image:
    "{{download_cmd}}" --dir "{{image_dir}}" {{download_args}}

# Expand an image into IMAGE_PATH, downloading releases when missing
# Usage: just install-pi-image DOWNLOAD_ARGS="--release v1.2.3"
install-pi-image:
    "{{install_cmd}}" --dir "{{image_dir}}" --image "{{image_path}}" {{download_args}}

# Download (via install-pi-image) and flash to FLASH_DEVICE. Run with sudo.
# Usage: sudo just flash-pi FLASH_DEVICE=/dev/sdX
flash-pi: install-pi-image
    if [ -z "{{flash_device}}" ]; then
        echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi." >&2
        exit 1
    fi
    "{{flash_cmd}}" --image "{{image_path}}" --device "{{flash_device}}" {{flash_args}}

# Download (via install-pi-image) and flash while generating Markdown/HTML reports.
# Usage: sudo just flash-pi-report FLASH_DEVICE=/dev/sdX FLASH_REPORT_ARGS="--cloud-init ~/user-data"
flash-pi-report: install-pi-image
    if [ -z "{{flash_device}}" ]; then
        echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX) before running flash-pi-report." >&2
        exit 1
    fi
    "{{flash_report_cmd}}" --image "{{image_path}}" --device "{{flash_device}}" {{flash_args}} {{flash_report_args}}

# Run the end-to-end readiness checks
# Usage: just doctor
doctor:
    "{{justfile_directory()}}/scripts/sugarkube_doctor.sh"

# Revert cmdline.txt and fstab entries back to the SD card defaults
# Usage: sudo just rollback-to-sd
rollback-to-sd:
    "{{rollback_cmd}}" {{rollback_args}}

# Clone the active SD card to an attached SSD with resume/dry-run helpers
# Usage: sudo just clone-ssd CLONE_TARGET=/dev/sda CLONE_ARGS="--dry-run"
clone-ssd:
    if [ -z "{{clone_target}}" ]; then
        echo "Set CLONE_TARGET to the target device (e.g. /dev/sda) before running clone-ssd." >&2
        exit 1
    fi
    "{{clone_cmd}}" --target "{{clone_target}}" {{clone_args}}

# Run post-clone validation against the active root filesystem
# Usage: sudo just validate-ssd-clone VALIDATE_ARGS="--stress-mb 256"
validate-ssd-clone:
    "{{validate_cmd}}" {{validate_args}}

# Collect SMART metrics and wear indicators for the active SSD
# Usage: sudo just monitor-ssd-health HEALTH_ARGS="--tag weekly"
monitor-ssd-health:
    "{{health_cmd}}" {{health_args}}

# Run pi_node_verifier remotely over SSH
# Usage: just smoke-test-pi SMOKE_ARGS="pi-a.local --reboot"
smoke-test-pi:
    "{{smoke_cmd}}" {{smoke_args}}

# Publish anonymized telemetry payloads once.
publish-telemetry:
    "{{telemetry_cmd}}" {{telemetry_args}}

# Update the hardware boot conformance badge JSON
# Usage: just update-hardware-badge BADGE_ARGS="--status warn --notes 'pi-b'"
update-hardware-badge:
    "{{badge_cmd}}" {{badge_args}}

# Install CLI dependencies inside GitHub Codespaces or fresh containers
# Usage: just codespaces-bootstrap
codespaces-bootstrap:
    sudo apt-get update
    sudo apt-get install -y curl gh jq pv unzip xz-utils

# Run spellcheck and linkcheck to keep docs automation aligned
# Usage: just docs-verify
docs-verify:
    pyspelling -c "{{justfile_directory()}}/.spellcheck.yaml"
    linkchecker --no-warnings "{{justfile_directory()}}/README.md" \
        "{{justfile_directory()}}/docs/"

# Generate printable QR codes that link to the quickstart and troubleshooting docs
# Usage: just qr-codes QR_ARGS="--output-dir ~/qr"
qr-codes:
    "{{qr_cmd}}" {{qr_args}}
