#!/usr/bin/env python3
"""Rebuild review artifacts from one exact git commit and official pinned wheels.

Run on a connected preparation machine, never on the NIC-less proof guest.
No installer, test, VM, service or credential operation is performed.
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen

FILES = (
    "scripts/ethernet_mdns_resolver.py",
    "tests/test_ethernet_mdns_resolver.py",
    "tests/test_ethernet_resolver_namespace.py",
    "tests/test_resolver_qualification.py",
    "scripts/qualification/resolver_lifecycle.py",
    "scripts/qualification/resolver_oneshot.py",
    "scripts/qualification/resolver_offline_prepare.py",
    "scripts/qualification/build_resolver_bundle.py",
    "scripts/qualification/resolver-lifecycle.md",
    "scripts/qualification/resolver-offline-requirements.txt",
    "scripts/qualification/resolver-python-dependencies.json",
    "scripts/qualification/sugarkube-lifecycle-proof.service",
)


def relative_name(path, root):
    """Use Linux-compatible names even when the preparation host is Windows."""
    return path.relative_to(root).as_posix()


def checksum_record(path, root, digest):
    return f"{digest}  {relative_name(path, root)}\n"


def write_utf8(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def build(repo, commit, output):
    if sys.version_info < (3, 11):
        raise RuntimeError("bundle preparation requires Python 3.11 or newer")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or output.exists():
        raise ValueError("full commit SHA and a new output path required")
    resolved = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", commit + "^{commit}"], text=True
    ).strip()
    if resolved != commit:
        raise ValueError("commit mismatch")
    with tempfile.TemporaryDirectory(prefix="resolver-bundle-build-") as temporary:
        root = Path(temporary) / "resolver-lifecycle-bundle"
        root.mkdir()
        for name in FILES:
            path = root / "source" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{name}"])
            )
        manifest = json.loads(
            (root / "source/scripts/qualification/resolver-python-dependencies.json").read_text(
                encoding="utf-8"
            )
        )
        write_utf8(
            root / "python-dependencies.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        for item in manifest["packages"]:
            parsed = urlparse(item["url"])
            if parsed.scheme != "https" or parsed.hostname != "files.pythonhosted.org":
                raise ValueError("only official PyPI wheel URLs permitted")
            path = root / item["file"]
            if path.parent != root / "wheels":
                raise ValueError("invalid wheel path")
            with urlopen(item["url"], timeout=30) as response:
                if urlparse(response.url).hostname != "files.pythonhosted.org":
                    raise ValueError("unexpected download redirect")
                content = response.read()
            if (
                len(content) != item["bytes"]
                or hashlib.sha256(content).hexdigest() != item["sha256"]
            ):
                raise ValueError("wheel checksum/size mismatch")
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
        helper = root / "source/scripts/qualification/resolver_offline_prepare.py"
        spec = importlib.util.spec_from_file_location("offline_prepare", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.prepare(root, root / "deps")
        write_utf8(
            root / "bundle-manifest.json",
            json.dumps(
                {
                    "source_commit": commit,
                    "status": "REVIEW ONLY; NO VM EXECUTION",
                    "native_image_lock": "PENDING lab image hash and native package versions",
                    "python_target": "CPython 3.12 Linux",
                    "dependency_installation": "pure wheel extraction only",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        # Importing the preparation helper may create bytecode: exclude it explicitly.
        import shutil

        for directory in root.rglob("__pycache__"):
            shutil.rmtree(directory)
        entries = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: relative_name(path, root),
        )
        write_utf8(
            root / "SHA256SUMS",
            "".join(
                checksum_record(path, root, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in entries
            ),
        )
        with output.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
                ) as archive:
                    for path in [
                        root,
                        *sorted(root.rglob("*"), key=lambda path: relative_name(path, root)),
                    ]:
                        info = archive.gettarinfo(
                            str(path), arcname=relative_name(path, root.parent)
                        )
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        info.mode = 0o755 if path.is_dir() else 0o644
                        if path.is_file():
                            with path.open("rb") as source:
                                archive.addfile(info, source)
                        else:
                            archive.addfile(info)
    print(f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.repo.resolve(strict=True), args.commit, args.output.resolve())
