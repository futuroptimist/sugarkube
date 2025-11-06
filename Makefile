SHELL := /bin/bash

IMAGE_DIR ?= $(HOME)/sugarkube/images
IMAGE_NAME ?= sugarkube.img
IMAGE_PATH := $(IMAGE_DIR)/$(IMAGE_NAME)
INSTALL_CMD ?= $(CURDIR)/scripts/install_sugarkube_image.sh
FLASH_CMD ?= $(CURDIR)/scripts/flash_pi_media.sh
FLASH_REPORT_CMD ?= $(CURDIR)/scripts/flash_pi_media_report.py
DOWNLOAD_CMD ?= $(CURDIR)/scripts/download_pi_image.sh
PREFLIGHT_CMD ?= $(CURDIR)/scripts/preflight_clone.sh
VERIFY_CLONE_CMD ?= $(CURDIR)/scripts/verify_clone.sh
FINALIZE_NVME_CMD ?= $(CURDIR)/scripts/finalize_nvme.sh
ROLLBACK_HELPER_CMD ?= $(CURDIR)/scripts/rollback_to_sd_helper.sh
CLONE_CMD ?= $(CURDIR)/scripts/ssd_clone.py
DOWNLOAD_ARGS ?=
FLASH_ARGS ?= --assume-yes
FLASH_REPORT_ARGS ?=
CLONE_ARGS ?=
TARGET ?=
MOUNT_BASE ?= /mnt/clone
CLEAN_MOUNTS_CMD ?= $(CURDIR)/scripts/cleanup_clone_mounts.sh
VALIDATE_CMD ?= $(CURDIR)/scripts/ssd_post_clone_validate.py
VALIDATE_ARGS ?=
QR_CMD ?= $(CURDIR)/scripts/generate_qr_codes.py
QR_ARGS ?=
HEALTH_CMD ?= $(CURDIR)/scripts/ssd_health_monitor.py
HEALTH_ARGS ?=
SMOKE_CMD ?= $(CURDIR)/scripts/pi_smoke_test.py
SMOKE_ARGS ?=
QEMU_SMOKE_CMD ?= $(CURDIR)/scripts/qemu_pi_smoke_test.py
QEMU_SMOKE_ARGS ?=
QEMU_SMOKE_IMAGE ?=
QEMU_SMOKE_ARTIFACTS ?= $(CURDIR)/artifacts/qemu-smoke
TELEMETRY_CMD ?= $(CURDIR)/scripts/publish_telemetry.py
TELEMETRY_ARGS ?=
TEAMS_CMD ?= $(CURDIR)/scripts/sugarkube_teams.py
TEAMS_ARGS ?=
WORKFLOW_NOTIFY_ARGS ?=
BADGE_CMD ?= $(CURDIR)/scripts/update_hardware_boot_badge.py
BADGE_ARGS ?=
REHEARSAL_CMD ?= $(CURDIR)/scripts/pi_multi_node_join_rehearsal.py
REHEARSAL_ARGS ?=
CLUSTER_CMD ?= $(CURDIR)/scripts/pi_multi_node_join_rehearsal.py
CLUSTER_ARGS ?=
CLUSTER_BOOTSTRAP_ARGS ?=
TOKEN_PLACE_SAMPLE_CMD ?= $(CURDIR)/scripts/token_place_replay_samples.py
TOKEN_PLACE_SAMPLE_ARGS ?= --samples-dir $(CURDIR)/samples/token_place
SUPPORT_BUNDLE_CMD ?= $(CURDIR)/scripts/collect_support_bundle.py
SUPPORT_BUNDLE_ARGS ?=
SUPPORT_BUNDLE_HOST ?=
FIELD_GUIDE_CMD ?= $(CURDIR)/scripts/render_field_guide_pdf.py
FIELD_GUIDE_ARGS ?=
MAC_SETUP_CMD ?= $(CURDIR)/scripts/sugarkube_setup.py
MAC_SETUP_ARGS ?=
START_HERE_ARGS ?=
SUGARKUBE_CLI ?= $(CURDIR)/scripts/sugarkube
DOCS_VERIFY_ARGS ?=
DOCS_SIMPLIFY_ARGS ?=
NVME_HEALTH_ARGS ?=

.PHONY: install-pi-image download-pi-image flash-pi flash-pi-report doctor start-here rollback-to-sd \
        clone-ssd validate-ssd-clone docs-verify docs-simplify qr-codes monitor-ssd-health nvme-health smoke-test-pi qemu-smoke field-guide \
        publish-telemetry notify-teams notify-workflow update-hardware-badge rehearse-join \
        token-place-samples support-bundle mac-setup cluster-up cluster-bootstrap codespaces-bootstrap \
        show-disks preflight verify-clone finalize-nvme clean-mounts-hard ci-simulate ci-simulate-kcov

install-pi-image:
	$(INSTALL_CMD) --dir '$(IMAGE_DIR)' --image '$(IMAGE_PATH)' $(DOWNLOAD_ARGS)

download-pi-image:
	$(DOWNLOAD_CMD) --dir '$(IMAGE_DIR)' $(DOWNLOAD_ARGS)

flash-pi: install-pi-image
	@if [ -z "$(FLASH_DEVICE)" ]; then \
		echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX)." >&2; \
		exit 1; \
	fi
	$(FLASH_CMD) --image '$(IMAGE_PATH)' --device "$(FLASH_DEVICE)" $(FLASH_ARGS)

flash-pi-report: install-pi-image
	@if [ -z "$(FLASH_DEVICE)" ]; then \
		echo "Set FLASH_DEVICE to the target device (e.g. /dev/sdX)." >&2; \
		exit 1; \
	fi
	$(FLASH_REPORT_CMD) --image '$(IMAGE_PATH)' --device "$(FLASH_DEVICE)" $(FLASH_ARGS) $(FLASH_REPORT_ARGS)

doctor:
	$(CURDIR)/scripts/sugarkube_doctor.sh

start-here:
	$(SUGARKUBE_CLI) docs start-here $(START_HERE_ARGS)

rollback-to-sd:
	$(ROLLBACK_HELPER_CMD)

clone-ssd:
	@if [ -z "$(TARGET)" ]; then \
		echo "Set TARGET to the destination device (e.g. /dev/nvme0n1)." >&2; \
		exit 1; \
	fi
	$(CLONE_CMD) --target "$(TARGET)" $(CLONE_ARGS)

show-disks:
	lsblk -e7 -o NAME,MAJ:MIN,SIZE,TYPE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS

preflight:
	@if [ -z "$(TARGET)" ]; then \
		echo "Set TARGET to the destination device (e.g. /dev/nvme0n1)." >&2; \
		exit 1; \
	fi
	sudo --preserve-env=TARGET,WIPE $(PREFLIGHT_CMD)

verify-clone:
	@if [ -z "$(TARGET)" ]; then \
		echo "Set TARGET to the destination device (e.g. /dev/nvme0n1)." >&2; \
		exit 1; \
	fi
	sudo --preserve-env=TARGET,MOUNT_BASE env MOUNT_BASE=$(MOUNT_BASE) $(VERIFY_CLONE_CMD)

finalize-nvme:
	sudo --preserve-env=EDITOR,FINALIZE_NVME_EDIT $(FINALIZE_NVME_CMD)

clean-mounts-hard:
	sudo --preserve-env=TARGET,MOUNT_BASE env TARGET=$(if $(TARGET),$(TARGET),/dev/nvme0n1) MOUNT_BASE=$(MOUNT_BASE) $(CLEAN_MOUNTS_CMD) --force

validate-ssd-clone:
	$(VALIDATE_CMD) $(VALIDATE_ARGS)

docs-verify:
	$(SUGARKUBE_CLI) docs verify $(DOCS_VERIFY_ARGS)

docs-simplify:
	$(SUGARKUBE_CLI) docs simplify $(DOCS_SIMPLIFY_ARGS)

codespaces-bootstrap:
	sudo apt-get update
	sudo apt-get install -y curl gh jq pv unzip xz-utils aspell aspell-en python3 python3-pip python3-venv
	python3 -m pip install --user --upgrade pip pre-commit pyspelling linkchecker

qr-codes:
	$(QR_CMD) $(QR_ARGS)

monitor-ssd-health:
	$(HEALTH_CMD) $(HEALTH_ARGS)

nvme-health:
	$(SUGARKUBE_CLI) nvme health $(NVME_HEALTH_ARGS)

smoke-test-pi:
	$(SMOKE_CMD) $(SMOKE_ARGS)

qemu-smoke:
	@if [ -z "$(QEMU_SMOKE_IMAGE)" ]; then \
		echo "Set QEMU_SMOKE_IMAGE to the built image (sugarkube.img or .img.xz)." >&2; \
		exit 1; \
	fi
	sudo $(QEMU_SMOKE_CMD) --image "$(QEMU_SMOKE_IMAGE)" --artifacts-dir "$(QEMU_SMOKE_ARTIFACTS)" $(QEMU_SMOKE_ARGS)

field-guide:
	$(FIELD_GUIDE_CMD) $(FIELD_GUIDE_ARGS)

publish-telemetry:
	$(TELEMETRY_CMD) $(TELEMETRY_ARGS)

notify-teams:
	$(TEAMS_CMD) $(TEAMS_ARGS)

notify-workflow:
	$(SUGARKUBE_CLI) notify workflow $(WORKFLOW_NOTIFY_ARGS)

update-hardware-badge:
	$(BADGE_CMD) $(BADGE_ARGS)

rehearse-join:
	$(REHEARSAL_CMD) $(REHEARSAL_ARGS)

cluster-up:
	$(CLUSTER_CMD) $(CLUSTER_ARGS)

cluster-bootstrap:
	$(SUGARKUBE_CLI) pi cluster $(CLUSTER_BOOTSTRAP_ARGS)

token-place-samples:
	$(SUGARKUBE_CLI) token-place samples $(TOKEN_PLACE_SAMPLE_ARGS)

support-bundle:
	@if [ -z "$(SUPPORT_BUNDLE_HOST)" ]; then \
		echo "Set SUPPORT_BUNDLE_HOST to the target host (e.g. pi.local) before running support-bundle." >&2; \
		exit 1; \
	fi
	$(SUPPORT_BUNDLE_CMD) "$(SUPPORT_BUNDLE_HOST)" $(SUPPORT_BUNDLE_ARGS)

mac-setup:
	$(MAC_SETUP_CMD) $(MAC_SETUP_ARGS)

ci-simulate:
	@echo "Simulating CI workflow environment locally..."
	@$(CURDIR)/scripts/ci_simulate.sh

ci-simulate-kcov:
	@echo "Simulating CI workflow with kcov instrumentation..."
	@$(CURDIR)/scripts/ci_simulate.sh --with-kcov
