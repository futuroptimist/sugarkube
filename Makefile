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

.PHONY: install-pi-image download-pi-image flash-pi flash-pi-report doctor rollback-to-sd

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
