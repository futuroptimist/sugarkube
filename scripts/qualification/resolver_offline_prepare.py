#!/usr/bin/env python3
"""Verify the reviewed bundle and unpack pure wheels locally; never run tests/installers."""

import hashlib
import json
from pathlib import Path
import sys
import zipfile

if sys.flags.optimize:
    raise SystemExit(
        "Offline verification requires assertions enabled; unset PYTHONOPTIMIZE and -O."
    )


def prepare(bundle, destination):
    assert not destination.exists()
    manifest = json.loads((bundle / "python-dependencies.json").read_text(encoding="utf-8"))
    wheels = []
    for item in manifest["packages"]:
        wheel = bundle / item["file"]
        assert wheel.parent == bundle / "wheels"
        assert hashlib.sha256(wheel.read_bytes()).hexdigest() == item["sha256"]
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                path = Path(name)
                assert not path.is_absolute() and ".." not in path.parts
                assert ".data" not in path.parts[0]  # Pure wheels only; no installer hooks.
            metadata = archive.read(next(n for n in archive.namelist() if n.endswith("/WHEEL")))
            assert b"Root-Is-Purelib: true" in metadata
        wheels.append(wheel)
    destination.mkdir(mode=0o755)
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(destination)
    print(f"Prepared dependencies only: {destination}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: resolver_offline_prepare.py BUNDLE NEW_DEPENDENCY_DIRECTORY")
    prepare(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve())
