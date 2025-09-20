# Pi Carrier QR Labels

Quick-response stickers turn the physical pi_carrier into a living manual. Scan a label and jump straight to the guide you need without digging through bookmarks or the GitHub repo.

## What's included

Running the generator creates two SVG assets sized for 50 mm (2 in) square stickers:

- **Pi Image Quickstart** – Launch pad for flashing and first boot.
- **Pi Boot Troubleshooting** – Matrix of LED cues, journal commands, and recovery steps.

Both codes resolve to the canonical docs in this repository so they stay fresh as the content evolves.

## Generate the stickers

```bash
python3 scripts/generate_qr_codes.py
```

The script writes SVGs and a `manifest.json` under `docs/images/qr/`. Customize the output directory, quiet zone, or module size when you need different print dimensions:

```bash
python3 scripts/generate_qr_codes.py \
  --output-dir ~/sugarkube/qr-labels \
  --border 3 \
  --module-size 16
```

Every run refreshes existing files so the assets never drift from the latest URLs.

Prefer Make or `just`? Use the helper targets that wrap the script:

```bash
make qr-codes
# or
just qr-codes
```

## Print & apply

1. Import the SVGs into your label workflow. A 50 mm square fits most 2×2 in sticker sheets; scale evenly when adjusting the size.
2. Print on matte vinyl or laminated paper for outdoor deployments. Waterproof stock survives condensation inside the enclosure.
3. Place the **Quickstart** sticker on the enclosure lid and the **Troubleshooting** sticker near the USB-C/power header so they stay visible when the carrier is open.
4. Optional: add clear tape over paper labels for abrasion resistance.

## Keep the codes current

Because the QR payloads target the GitHub docs, they automatically pick up new instructions as the guides evolve. When we add more hardware cheat sheets, append additional `QrLabel` entries in `scripts/generate_qr_codes.py` and rerun the generator.

For field deployments without internet access, print the docs referenced by each code and bundle them with the hardware so the QR labels still map to a paper backup.
