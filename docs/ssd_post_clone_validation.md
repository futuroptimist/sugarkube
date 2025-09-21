# SSD Post-Clone Validation

When the Raspberry Pi boots from a newly cloned SSD, run the validation helper to confirm
firmware, bootloaders, and filesystems agree on the new storage layout. The script also performs a
lightweight read/write stress test so you can catch failing drives before trusting them with k3s
state.

## What the helper covers

`scripts/ssd_post_clone_validate.py` inspects several layers of the system:

- Resolves the devices mounted at `/` and `/boot`, then records their `PARTUUID`s.
- Compares `/etc/fstab` entries for `/` and `/boot` against the live mounts.
- Reads `/boot/cmdline.txt` to ensure `root=PARTUUID=` points at the new SSD.
- Invokes `rpi-eeprom-config --summary` (when available) and confirms USB boot options appear
  before the SD card in the EEPROM boot order.
- Writes and reads a temporary file (default 128 MiB) to gauge SSD throughput and flush out obvious
  I/O errors.

Each run emits a concise console summary plus Markdown and JSON reports under
`~/sugarkube/reports/ssd-validation/<timestamp>/`.

## Quick start

Run the helper after completing your SSD clone (for example via
`scripts/ssd_clone.py`) and before unplugging the SD card:

```bash
sudo ./scripts/ssd_post_clone_validate.py
```

The defaults suit most setups:

- Reports land in `~/sugarkube/reports/ssd-validation/`.
- The stress test reads and writes 128 MiB under `/var/log/sugarkube/`.
- Failures exit with status code `1`, warnings exit `0` but highlight potential follow-up actions.

Prefer the wrappers? They call the same script and forward environment overrides:

- GNU Make:
  ```bash
  sudo make validate-ssd-clone
  ```
- `just`:
  ```bash
  sudo just validate-ssd-clone
  ```

Both respect `VALIDATE_ARGS`. For example, to raise the stress workload to 512 MiB and store
reports elsewhere:

```bash
sudo VALIDATE_ARGS='--stress-mb 512 --report-dir /mnt/ssd-reports' make validate-ssd-clone
```

## Customize the run

Key flags exposed by `ssd_post_clone_validate.py`:

| Flag | Purpose |
| --- | --- |
| `--stress-mb` | Megabytes written and read during the stress test (default `128`). |
| `--skip-stress` | Skip the I/O stress test when you only need configuration checks. |
| `--report-dir` | Base directory for Markdown/JSON output (default `~/sugarkube/reports`). |
| `--stress-path` | Directory for the temporary stress-test file (default `/var/log/sugarkube`). |
| `--cmdline` / `--fstab` / `--boot-mount` | Override path discovery on non-standard images. |

The helper trims leading/trailing slashes from `--report-prefix` before creating
`<report-dir>/<report-prefix>/<timestamp>/`.

## Interpreting results

- **✅ PASS** — configuration matches and the stress test completed. Review the Markdown report for
  detailed JSON payloads before archiving.
- **⚠️ WARN** — data was missing (for example, `rpi-eeprom-config` unavailable) or the boot order
  favours the SD card. Resolve the issue and rerun the validator to confirm.
- **❌ FAIL** — `/etc/fstab`, `/boot/cmdline.txt`, or the stress test exposed a mismatch. Revisit the
  clone procedure or fall back to the SD card using `scripts/rollback_to_sd.sh` until the SSD is
  healthy.
- **⏭️ SKIP** — you asked the script to skip the stress test; all other checks still execute.

If failures persist, capture the JSON report and add it to your incident notes (or a future
`outages/` entry) alongside the SSD's SMART data.
