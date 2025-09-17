.PHONY: help download-pi-image install-pi-image flash-pi verify-pi-image

help:
	@echo "Available targets:"
	@echo "  make download-pi-image   # Download latest release artifact"
	@echo "  make install-pi-image    # Download, verify, and expand image"
	@echo "  make flash-pi DEVICE=/dev/sdX [FLASH_ARGS=...] # Flash image to removable media"
	@echo "  make verify-pi-image IMAGE=path     # Run pi_node_verifier on mounted image"

DOWNLOAD_FLAGS ?=
INSTALL_FLAGS ?=
FLASH_ARGS ?=

download-pi-image:
	./scripts/download_pi_image.sh $(DOWNLOAD_FLAGS)

install-pi-image:
	./scripts/install_sugarkube.sh $(INSTALL_FLAGS)

flash-pi:
	@if [ -z "$(DEVICE)" ]; then \
		echo "Set DEVICE=/dev/sdX (or /dev/diskN on macOS)" >&2; \
		exit 1; \
	fi
	./scripts/flash_pi_media.sh --device "$(DEVICE)" $(FLASH_ARGS)

verify-pi-image:
	@if [ -z "$(IMAGE)" ]; then \
		echo "Set IMAGE=/path/to/sugarkube.img" >&2; \
		exit 1; \
	fi
	./scripts/pi_node_verifier.sh "$(IMAGE)"
