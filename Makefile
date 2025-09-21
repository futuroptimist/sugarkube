SHELL := /bin/bash

IMAGE_DIR ?= $(HOME)/sugarkube/images
IMAGE_NAME ?= sugarkube.img
IMAGE_PATH := $(IMAGE_DIR)/$(IMAGE_NAME)
INSTALL_CMD ?= $(CURDIR)/scripts/install_sugarkube_image.sh
FLASH_CMD ?= $(CURDIR)/scripts/flash_pi_media.sh
FLASH_REPORT_CMD ?= $(CURDIR)/scripts/flash_pi_media_report.py
DOWNLOAD_CMD ?= $(CURDIR)/scripts/download_pi_image.sh
ROLLBACK_CMD ?= $(CURDIR)/scripts/rollback_to_sd.sh
DOWNLOAD_ARGS ?=
FLASH_ARGS ?= --assume-yes
FLASH_REPORT_ARGS ?=
ROLLBACK_ARGS ?=
VALIDATE_CMD ?= $(CURDIR)/scripts/ssd_post_clone_validate.py
VALIDATE_ARGS ?=
QR_CMD ?= $(CURDIR)/scripts/generate_qr_codes.py
QR_ARGS ?=
HEALTH_CMD ?= $(CURDIR)/scripts/ssd_health_monitor.py
HEALTH_ARGS ?=
SMOKE_CMD ?= $(CURDIR)/scripts/pi_smoke_test.py
SMOKE_ARGS ?=

.PHONY: install-pi-image download-pi-image flash-pi flash-pi-report doctor rollback-to-sd \
        docs-verify qr-codes monitor-ssd-health smoke-test-pi

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

rollback-to-sd:
	$(ROLLBACK_CMD) $(ROLLBACK_ARGS)

docs-verify:
	pyspelling -c .spellcheck.yaml
	linkchecker --no-warnings README.md docs/

qr-codes:
        $(QR_CMD) $(QR_ARGS)

monitor-ssd-health:
        $(HEALTH_CMD) $(HEALTH_ARGS)

smoke-test-pi:
        $(SMOKE_CMD) $(SMOKE_ARGS)
