SHELL := /bin/bash

IMAGE_DIR ?= $(HOME)/sugarkube/images
IMAGE_NAME ?= sugarkube.img
IMAGE_PATH := $(IMAGE_DIR)/$(IMAGE_NAME)
INSTALL_CMD ?= $(CURDIR)/scripts/install_sugarkube_image.sh
FLASH_CMD ?= $(CURDIR)/scripts/flash_pi_media.sh
FLASH_REPORT_CMD ?= $(CURDIR)/scripts/flash_pi_media_report.py
DOWNLOAD_CMD ?= $(CURDIR)/scripts/download_pi_image.sh
ROLLBACK_CMD ?= $(CURDIR)/scripts/rollback_to_sd.sh
CLONE_CMD ?= $(CURDIR)/scripts/ssd_clone.py
DOWNLOAD_ARGS ?=
FLASH_ARGS ?= --assume-yes
FLASH_REPORT_ARGS ?=
ROLLBACK_ARGS ?=
CLONE_ARGS ?=
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
WORKFLOW_NOTIFY_CMD ?= $(CURDIR)/scripts/workflow_artifact_notifier.py
WORKFLOW_NOTIFY_ARGS ?=
BADGE_CMD ?= $(CURDIR)/scripts/update_hardware_boot_badge.py
BADGE_ARGS ?=
REHEARSAL_CMD ?= $(CURDIR)/scripts/pi_multi_node_join_rehearsal.py
REHEARSAL_ARGS ?=
CLUSTER_CMD ?= $(CURDIR)/scripts/pi_multi_node_join_rehearsal.py
CLUSTER_ARGS ?=
TOKEN_PLACE_SAMPLE_CMD ?= $(CURDIR)/scripts/token_place_replay_samples.py
TOKEN_PLACE_SAMPLE_ARGS ?= --samples-dir $(CURDIR)/samples/token_place
SUPPORT_BUNDLE_CMD ?= $(CURDIR)/scripts/collect_support_bundle.py
SUPPORT_BUNDLE_ARGS ?=
SUPPORT_BUNDLE_HOST ?=
FIELD_GUIDE_CMD ?= $(CURDIR)/scripts/render_field_guide_pdf.py
FIELD_GUIDE_ARGS ?=
MAC_SETUP_CMD ?= $(CURDIR)/scripts/sugarkube_setup.py
MAC_SETUP_ARGS ?=
START_HERE_CMD ?= $(CURDIR)/scripts/start_here.py
START_HERE_ARGS ?=

.PHONY: install-pi-image download-pi-image flash-pi flash-pi-report doctor start-here rollback-to-sd \
        clone-ssd docs-verify docs-simplify qr-codes monitor-ssd-health smoke-test-pi qemu-smoke field-guide \
        publish-telemetry notify-teams notify-workflow update-hardware-badge rehearse-join \
        token-place-samples support-bundle mac-setup cluster-up codespaces-bootstrap

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
	$(START_HERE_CMD) $(START_HERE_ARGS)

rollback-to-sd:
	$(ROLLBACK_CMD) $(ROLLBACK_ARGS)

clone-ssd:
	@if [ -z "$(CLONE_TARGET)" ]; then \
		echo "Set CLONE_TARGET to the target device (e.g. /dev/sda)." >&2; \
		exit 1; \
	fi
	$(CLONE_CMD) --target "$(CLONE_TARGET)" $(CLONE_ARGS)

docs-verify:
	pyspelling -c .spellcheck.yaml
	linkchecker --no-warnings README.md docs/

docs-simplify:
	$(CURDIR)/scripts/checks.sh --docs-only

codespaces-bootstrap:
	sudo apt-get update
	sudo apt-get install -y curl gh jq pv unzip xz-utils aspell aspell-en python3 python3-pip python3-venv
	python3 -m pip install --user --upgrade pip pre-commit pyspelling linkchecker

qr-codes:
	$(QR_CMD) $(QR_ARGS)

monitor-ssd-health:
	$(HEALTH_CMD) $(HEALTH_ARGS)

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
        $(WORKFLOW_NOTIFY_CMD) $(WORKFLOW_NOTIFY_ARGS)

update-hardware-badge:
        $(BADGE_CMD) $(BADGE_ARGS)

rehearse-join:
	$(REHEARSAL_CMD) $(REHEARSAL_ARGS)

cluster-up:
	$(CLUSTER_CMD) $(CLUSTER_ARGS)

token-place-samples:
	$(TOKEN_PLACE_SAMPLE_CMD) $(TOKEN_PLACE_SAMPLE_ARGS)

support-bundle:
        @if [ -z "$(SUPPORT_BUNDLE_HOST)" ]; then \
        echo "Set SUPPORT_BUNDLE_HOST to the target host (e.g. pi.local) before running support-bundle." >&2; \
        exit 1; \
        fi
        $(SUPPORT_BUNDLE_CMD) "$(SUPPORT_BUNDLE_HOST)" $(SUPPORT_BUNDLE_ARGS)

mac-setup:
        $(MAC_SETUP_CMD) $(MAC_SETUP_ARGS)
