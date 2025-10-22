set shell := ["bash", "-euo", "pipefail", "-c"]
set export := true

export SUGARKUBE_CLUSTER := env('SUGARKUBE_CLUSTER', 'sugar')
export SUGARKUBE_SERVERS := env('SUGARKUBE_SERVERS', '1')
export K3S_CHANNEL := env('K3S_CHANNEL', 'stable')

default: up
    @true

up env='dev': prereqs
    # Select per-environment token if available
    if [ "{{ env }}" = "dev" ] && [ -n "${SUGARKUBE_TOKEN_DEV:-}" ]; then export SUGARKUBE_TOKEN="$SUGARKUBE_TOKEN_DEV"; fi
    if [ "{{ env }}" = "int" ] && [ -n "${SUGARKUBE_TOKEN_INT:-}" ]; then export SUGARKUBE_TOKEN="$SUGARKUBE_TOKEN_INT"; fi
    if [ "{{ env }}" = "prod" ] && [ -n "${SUGARKUBE_TOKEN_PROD:-}" ]; then export SUGARKUBE_TOKEN="$SUGARKUBE_TOKEN_PROD"; fi

    export SUGARKUBE_ENV="{{ env }}"
    export SUGARKUBE_SERVERS="{{ SUGARKUBE_SERVERS }}"

    "{{ scripts_dir }}/check_memory_cgroup.sh"

    # Proceed with discovery/join for subsequent nodes
    sudo -E bash scripts/k3s-discover.sh

prereqs:
    sudo apt-get update
    sudo apt-get install -y avahi-daemon avahi-utils libnss-mdns curl jq
    sudo systemctl enable --now avahi-daemon
    if ! grep -q 'mdns4_minimal' /etc/nsswitch.conf; then sudo sed -i 's/^hosts:.*/hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4/' /etc/nsswitch.conf; fi

status:
    if ! command -v k3s >/dev/null 2>&1; then
        printf '%s\n' \
            'k3s is not installed yet.' \
            'Visit https://github.com/futuroptimist/sugarkube/blob/main/docs/raspi_cluster_setup.md.' \
            'Follow the instructions in that guide before rerunning this command.'
        exit 0
    fi
    sudo k3s kubectl get nodes -o wide

kubeconfig env='dev':
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown "$USER":"$USER" ~/.kube/config
    python3 scripts/update_kubeconfig_scope.py "${HOME}/.kube/config" "sugar-{{ env }}"

wipe:
    if command -v k3s-uninstall.sh >/dev/null; then sudo k3s-uninstall.sh; fi
    if command -v k3s-agent-uninstall.sh >/dev/null; then sudo k3s-agent-uninstall.sh; fi
    cluster="${SUGARKUBE_CLUSTER:-sugar}"
    env="${SUGARKUBE_ENV:-dev}"
    sudo rm -f "/etc/avahi/services/k3s-${cluster}-${env}.service" || true
    sudo systemctl restart avahi-daemon || true

scripts_dir := justfile_directory() + "/scripts"
image_dir := env_var_or_default("IMAGE_DIR", env_var("HOME") + "/sugarkube/images")
image_name := env_var_or_default("IMAGE_NAME", "sugarkube.img")
image_path := image_dir + "/" + image_name
install_cmd := env_var_or_default("INSTALL_CMD", scripts_dir + "/install_sugarkube_image.sh")
flash_cmd := env_var_or_default("FLASH_CMD", scripts_dir + "/flash_pi_media.sh")
flash_report_cmd := env_var_or_default("FLASH_REPORT_CMD", scripts_dir + "/flash_pi_media_report.py")
download_cmd := env_var_or_default("DOWNLOAD_CMD", scripts_dir + "/download_pi_image.sh")
download_args := env_var_or_default("DOWNLOAD_ARGS", "")
flash_args := env_var_or_default("FLASH_ARGS", "--assume-yes")
flash_report_args := env_var_or_default("FLASH_REPORT_ARGS", "")
flash_device := env_var_or_default("FLASH_DEVICE", "")
spot_check_cmd := env_var_or_default("SPOT_CHECK_CMD", scripts_dir + "/spot_check.sh")
spot_check_args := env_var_or_default("SPOT_CHECK_ARGS", "")
eeprom_cmd := env_var_or_default("EEPROM_CMD", scripts_dir + "/eeprom_nvme_first.sh")
boot_order_cmd := env_var_or_default("BOOT_ORDER_CMD", scripts_dir + "/boot_order.sh")
eeprom_args := env_var_or_default("EEPROM_ARGS", "")
clone_cmd := env_var_or_default("CLONE_CMD", scripts_dir + "/clone_to_nvme.sh")
clone_args := env_var_or_default("CLONE_ARGS", "")
clone_target := env_var_or_default("TARGET", "")
clone_wipe := env_var_or_default("WIPE", "0")
clean_mounts_cmd := env_var_or_default("CLEAN_MOUNTS_CMD", scripts_dir + "/cleanup_clone_mounts.sh")
preflight_cmd := env_var_or_default("PREFLIGHT_CMD", scripts_dir + "/preflight_clone.sh")
verify_clone_cmd := env_var_or_default("VERIFY_CLONE_CMD", scripts_dir + "/verify_clone.sh")
finalize_nvme_cmd := env_var_or_default("FINALIZE_NVME_CMD", scripts_dir + "/finalize_nvme.sh")
rollback_helper_cmd := env_var_or_default("ROLLBACK_HELPER_CMD", scripts_dir + "/rollback_to_sd_helper.sh")
validate_cmd := env_var_or_default("VALIDATE_CMD", scripts_dir + "/ssd_post_clone_validate.py")
validate_args := env_var_or_default("VALIDATE_ARGS", "")
post_clone_cmd := env_var_or_default("POST_CLONE_CMD", scripts_dir + "/post_clone_verify.sh")
post_clone_args := env_var_or_default("POST_CLONE_ARGS", "")
migrate_artifacts := env_var_or_default("MIGRATE_ARTIFACTS", justfile_directory() + "/artifacts/migrate-to-nvme")
migrate_skip_eeprom := env_var_or_default("SKIP_EEPROM", "0")
migrate_no_reboot := env_var_or_default("NO_REBOOT", "0")
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
nvme_health_args := env_var_or_default("NVME_HEALTH_ARGS", "")

_default:
    @just default

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
# Run the Raspberry Pi spot check and capture artifacts

# Usage: sudo just spot-check
spot-check:
    "{{ spot_check_cmd }}" {{ spot_check_args }}

# Inspect or align the EEPROM boot order

# Usage: sudo just boot-order sd-nvme-usb
boot-order preset:
    "{{ boot_order_cmd }}" preset "{{ preset }}"

# Deprecated wrapper retained for one release; prefer `just boot-order nvme-first`

# Usage: sudo just eeprom-nvme-first
eeprom-nvme-first:
    @echo "[deprecated] 'just eeprom-nvme-first' will be removed in a future release." >&2
    @echo "[deprecated] Use 'just boot-order nvme-first' next time." >&2
    @echo "[deprecated] Applying BOOT_ORDER=0xF416 (NVMe → SD → USB → repeat)." >&2
    just --justfile "{{ justfile_directory() }}/justfile" boot-order nvme-first

# Clone the active SD card to the preferred NVMe/USB target

# Usage: sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
clone-ssd:
    if [ -z "{{ clone_target }}" ]; then echo "Set TARGET to the destination device (e.g. /dev/nvme0n1) before running clone-ssd." >&2; exit 1; fi
    sudo --preserve-env=TARGET,WIPE,ALLOW_NON_ROOT,ALLOW_FAKE_BLOCK \
        "{{ clone_cmd }}" --target "{{ clone_target }}" {{ clone_args }}

show-disks:
    lsblk -e7 -o NAME,MAJ:MIN,SIZE,TYPE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS

preflight:
    if [ -z "{{ clone_target }}" ]; then echo "Set TARGET to the destination device (e.g. /dev/nvme0n1) before running preflight." >&2; exit 1; fi
    sudo --preserve-env=TARGET,WIPE \
        "{{ preflight_cmd }}"

verify-clone:
    if [ -z "{{ clone_target }}" ]; then echo "Set TARGET to the destination device (e.g. /dev/nvme0n1) before running verify-clone." >&2; exit 1; fi
    sudo --preserve-env=TARGET,MOUNT_BASE \
        env MOUNT_BASE={{ env_var_or_default("MOUNT_BASE", "/mnt/clone") }} \
        "{{ verify_clone_cmd }}"

finalize-nvme:
    sudo --preserve-env=EDITOR,FINALIZE_NVME_EDIT \
        "{{ finalize_nvme_cmd }}"

rollback-to-sd:
    "{{ rollback_helper_cmd }}"

# Clean up residual clone mounts and automounts.
# Usage:
#   just clean-mounts
#   TARGET=/dev/nvme1n1 MOUNT_BASE=/mnt/clone just clean-mounts
#   just clean-mounts -- --verbose --dry-run
#
# Notes:
# - Pass additional flags after `--`.
# - Defaults: TARGET=/dev/nvme0n1, MOUNT_BASE=/mnt/clone

clean-mounts args='':
    sudo --preserve-env=TARGET,MOUNT_BASE \
      env TARGET={{ env_var_or_default("TARGET", "/dev/nvme0n1") }} \
          MOUNT_BASE={{ env_var_or_default("MOUNT_BASE", "/mnt/clone") }} \
      "{{ clean_mounts_cmd }}" {{ args }}

clean-mounts-hard:
    sudo --preserve-env=TARGET,MOUNT_BASE \
      env TARGET={{ env_var_or_default("TARGET", "/dev/nvme0n1") }} \
          MOUNT_BASE={{ env_var_or_default("MOUNT_BASE", "/mnt/clone") }} \
      "{{ clean_mounts_cmd }}" --force

# One-command happy path: spot-check → EEPROM (optional) → clone → reboot

# Usage: sudo just migrate-to-nvme SKIP_EEPROM=1 NO_REBOOT=1
migrate-to-nvme:
    "{{ justfile_directory() }}/scripts/migrate_to_nvme.sh"

# Post-migration verification ensuring both partitions boot from NVMe

# Usage: sudo just post-clone-verify
post-clone-verify:
    "{{ post_clone_cmd }}" {{ post_clone_args }}

# Run post-clone validation against the active root filesystem

# Usage: sudo just validate-ssd-clone VALIDATE_ARGS="--stress-mb 256"
validate-ssd-clone:
    "{{ validate_cmd }}" {{ validate_args }}

# Collect SMART metrics and wear indicators for the active SSD

# Usage: sudo just monitor-ssd-health HEALTH_ARGS="--tag weekly"
monitor-ssd-health:
    "{{ health_cmd }}" {{ health_args }}

# Invoke the NVMe health helper shipped with the repository.
#

# Usage: sudo NVME_HEALTH_ARGS="--device /dev/nvme1n1" just nvme-health
nvme-health:
    "{{ sugarkube_cli }}" nvme health {{ nvme_health_args }}

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

# Bootstrap Flux controllers and sync manifests for an environment
flux-bootstrap env='dev':
    "{{ scripts_dir }}/flux-bootstrap.sh" "{{ env }}"

# Reconcile the platform Kustomization via Flux
platform-apply env='dev':
    flux reconcile kustomization platform \
        --namespace flux-system \
        --with-source

# Reseal SOPS secrets for an environment
seal-secrets env='dev':
    "{{ scripts_dir }}/seal-secrets.sh" "{{ env }}"

# Backwards-compatible alias that calls flux-bootstrap
platform-bootstrap env='dev':
    just flux-bootstrap env={{ env }}
