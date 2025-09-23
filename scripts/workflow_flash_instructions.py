#!/usr/bin/env python3
"""Render OS-specific flashing instructions for GitHub Actions pi-image runs."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from typing import Iterable


class WorkflowFlashError(RuntimeError):
    """Raised when workflow flashing instructions cannot be generated."""


@dataclasses.dataclass(frozen=True)
class WorkflowInfo:
    owner: str
    repo: str
    run_id: str

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def run_url(self) -> str:
        return f"https://github.com/{self.repository}/actions/runs/{self.run_id}"


_RUN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/"
        r"(?P<run_id>\d+)(?:/attempts/\d+)?(?:[/?#].*)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/workflows/[^/]+/runs/"
        r"(?P<run_id>\d+)(?:/attempts/\d+)?(?:[/?#].*)?$",
        re.IGNORECASE,
    ),
)

SUPPORTED_OS: dict[str, str] = {
    "linux": "Linux",
    "mac": "macOS",
    "windows": "Windows",
}

_ARTIFACT_NAME = "sugarkube-pi-image"
_IMAGE_NAME = "sugarkube.img.xz"

_STEP_TEMPLATES: dict[str, tuple[dict[str, Iterable[str]], ...]] = {
    "linux": (
        {
            "title": "Install GitHub CLI and utilities",
            "body": ("Install the GitHub CLI plus tools required to verify and expand the image.",),
            "commands": (
                "sudo apt-get update",
                "sudo apt-get install -y gh xz-utils coreutils",
            ),
        },
        {
            "title": "Authenticate GitHub CLI",
            "body": ('Run the interactive login once so "gh" can download workflow artifacts.',),
            "commands": ("gh auth login --web",),
        },
        {
            "title": "Create an images directory",
            "body": (
                "Store the artifacts in a predictable path. Feel free to reuse an existing folder.",
            ),
            "commands": (
                "mkdir -p {images_dir_unix}",
                "cd {images_dir_unix}",
            ),
        },
        {
            "title": "Download release artifacts",
            "body": (
                "Fetch the {artifact_name} bundle from the workflow run. The helper also works for"
                " private repositories once gh is authenticated.",
            ),
            "commands": (
                "gh run download {run_id} --repo {repository} --name {artifact_name} --dir .",
                "ls -l",
            ),
        },
        {
            "title": "Verify checksum before flashing",
            "body": ("Always confirm the checksum matches to avoid flashing a corrupted image.",),
            "commands": ("sha256sum -c {image_name}.sha256",),
        },
        {
            "title": "Expand the compressed image",
            "body": (
                "Keep the original .xz file for future flashes. The command below expands it to"
                " {expanded_image_path_unix}.",
            ),
            "commands": ("xz -dk {image_name}",),
        },
        {
            "title": "Flash removable media",
            "body": (
                "Clone the repository if you have not already, then run the flashing helper with"
                " sudo. Replace /dev/sdX with your target device.",
            ),
            "commands": (
                "git clone https://github.com/futuroptimist/sugarkube.git  # Skip if cloned",
                "cd sugarkube",
                (
                    "sudo ./scripts/flash_pi_media.sh --image {expanded_image_path_unix} "
                    "--device /dev/sdX --assume-yes"
                ),
            ),
        },
    ),
    "mac": (
        {
            "title": "Install GitHub CLI and dependencies",
            "body": (
                "Use Homebrew to install the tooling required to download, verify, and expand the"
                " image.",
            ),
            "commands": (
                "brew update",
                "brew install gh xz coreutils",
            ),
        },
        {
            "title": "Authenticate GitHub CLI",
            "body": ("Log in once via the browser to access private workflow artifacts.",),
            "commands": ("gh auth login --web",),
        },
        {
            "title": "Prepare the images directory",
            "body": (
                "All artifacts are saved to {images_dir_unix}. Adjust the path if you prefer a"
                " different location.",
            ),
            "commands": (
                "mkdir -p {images_dir_unix}",
                "cd {images_dir_unix}",
            ),
        },
        {
            "title": "Download workflow artifacts",
            "body": (
                "Download the {artifact_name} archive that contains the image, checksums, and"
                " provenance metadata.",
            ),
            "commands": (
                "gh run download {run_id} --repo {repository} --name {artifact_name} --dir .",
                "ls -lh",
            ),
        },
        {
            "title": "Verify checksum before flashing",
            "body": (
                "Confirm the SHA-256 hash matches the published value to guard against corruption.",
            ),
            "commands": ("shasum -a 256 -c {image_name}.sha256",),
        },
        {
            "title": "Expand the compressed image",
            "body": (
                "Retain {image_name} for reuse. The following command expands it into"
                " {expanded_image_path_unix}.",
            ),
            "commands": ("xz -dk {image_name}",),
        },
        {
            "title": "Flash the target disk",
            "body": (
                "Clone the helpers if needed, unmount the removable disk (diskutil list →"
                " diskutil unmountDisk), then flash it with sudo.",
            ),
            "commands": (
                "git clone https://github.com/futuroptimist/sugarkube.git  # Skip if cloned",
                "cd sugarkube",
                (
                    "sudo ./scripts/flash_pi_media.sh --image {expanded_image_path_unix} "
                    "--device /dev/diskX --assume-yes"
                ),
            ),
        },
    ),
    "windows": (
        {
            "title": "Install GitHub CLI and Python",
            "body": (
                "Use winget to install the GitHub CLI plus Python for checksum verification and"
                " decompression.",
            ),
            "commands": (
                "winget install --id GitHub.cli -e",
                "winget install --id Python.Python.3.11 -e",
            ),
        },
        {
            "title": "Authenticate GitHub CLI",
            "body": ("The browser-based login allows gh to download artifacts from private runs.",),
            "commands": ("gh auth login --web",),
        },
        {
            "title": "Create an images directory",
            "body": ("Store downloads in {images_dir_windows}. Adjust the path if necessary.",),
            "commands": (
                "New-Item -ItemType Directory -Path {images_dir_windows} -Force | Out-Null",
            ),
        },
        {
            "title": "Download workflow artifacts",
            "body": ("Download {artifact_name} from the workflow run into the staging directory.",),
            "commands": (
                (
                    "gh run download {run_id} --repo {repository} --name {artifact_name} "
                    "--dir {images_dir_windows}"
                ),
                "Get-ChildItem {images_dir_windows}",
            ),
        },
        {
            "title": "Verify checksum before flashing",
            "body": (
                "Compare the published hash with a freshly computed value before writing media.",
            ),
            "commands": (
                "$expected = (Get-Content {checksum_path_windows}).Split()[0]",
                (
                    "$actual = (Get-FileHash {image_path_windows} "
                    "-Algorithm SHA256).Hash.ToLower()"
                ),
                "if ($actual -ne $expected) {{ throw 'Checksum mismatch' }}",
                "else {{ 'Checksum OK' }}",
            ),
        },
        {
            "title": "Expand the compressed image",
            "body": (
                "Use Python's built-in lzma module to expand {image_name} into"
                " {expanded_image_path_windows}.",
            ),
            "commands": (
                (
                    'python -c "import lzma, pathlib, shutil; '
                    "src = pathlib.Path(r'{image_path_windows_raw}'); "
                    "dst = src.with_suffix(''); "
                    "print(f'Expanding {{src.name}} -> {{dst.name}}'); "
                    "with lzma.open(src, 'rb') as src_f, open(dst, 'wb') as dst_f: "
                    'shutil.copyfileobj(src_f, dst_f)"'
                ),
            ),
        },
        {
            "title": "Flash removable media",
            "body": (
                "Clone helpers if needed, then flash with the PowerShell wrapper."
                " Replace X with the correct disk number from Get-Disk.",
            ),
            "commands": (
                "git clone https://github.com/futuroptimist/sugarkube.git  # Skip if cloned",
                "Set-Location sugarkube",
                (
                    "pwsh -File scripts/flash_pi_media.ps1 --image {expanded_image_path_windows}"
                    " --device \\\\.\\PhysicalDriveX --assume-yes"
                ),
            ),
        },
    ),
}


def parse_workflow_url(url: str) -> WorkflowInfo:
    """Return workflow metadata extracted from a GitHub Actions run URL."""
    if not url or not url.strip():
        raise WorkflowFlashError("Provide a GitHub Actions run URL.")

    trimmed = url.strip()
    for pattern in _RUN_PATTERNS:
        match = pattern.match(trimmed)
        if match:
            owner = match.group("owner")
            repo = match.group("repo")
            run_id = match.group("run_id")
            return WorkflowInfo(owner=owner, repo=repo, run_id=run_id)

    raise WorkflowFlashError(f"Unrecognised workflow run URL: {trimmed}")


def _context_for(info: WorkflowInfo) -> dict[str, str]:
    images_dir_unix = "~/sugarkube/images"
    images_dir_windows = "$env:USERPROFILE\\sugarkube\\images"
    expanded_image_path_unix = f"{images_dir_unix}/sugarkube.img"
    image_path_windows = f"{images_dir_windows}\\sugarkube.img.xz"
    expanded_image_path_windows = f"{images_dir_windows}\\sugarkube.img"

    return {
        "repository": info.repository,
        "run_id": info.run_id,
        "run_url": info.run_url,
        "artifact_name": _ARTIFACT_NAME,
        "image_name": _IMAGE_NAME,
        "images_dir_unix": images_dir_unix,
        "expanded_image_path_unix": expanded_image_path_unix,
        "images_dir_windows": images_dir_windows,
        "image_path_windows": image_path_windows,
        "image_path_windows_raw": image_path_windows,
        "expanded_image_path_windows": expanded_image_path_windows,
        "checksum_path_windows": f"{images_dir_windows}\\{_IMAGE_NAME}.sha256",
    }


def instructions_for(os_key: str, info: WorkflowInfo) -> list[dict[str, list[str]]]:
    """Return rendered instruction steps for the requested OS."""
    if os_key not in SUPPORTED_OS:
        supported = ", ".join(sorted(SUPPORTED_OS))
        raise WorkflowFlashError(f"Unsupported OS '{os_key}'. Supported values: {supported}")

    context = _context_for(info)
    steps: list[dict[str, list[str]]] = []
    for template in _STEP_TEMPLATES[os_key]:
        step = {
            "title": template["title"].format_map(context),
            "body": [segment.format_map(context) for segment in template.get("body", ())],
            "commands": [cmd.format_map(context) for cmd in template.get("commands", ())],
        }
        steps.append(step)
    return steps


def render_text(os_key: str, info: WorkflowInfo) -> str:
    """Render human-readable instructions."""
    steps = instructions_for(os_key, info)
    lines: list[str] = [
        f"Repository : {info.repository}",
        f"Run URL    : {info.run_url}",
        f"Platform   : {SUPPORTED_OS[os_key]}",
        "",
    ]

    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step['title']}")
        for paragraph in step["body"]:
            lines.append(f"   {paragraph}")
        if step["commands"]:
            lines.append("   Commands:")
            for command in step["commands"]:
                lines.append(f"     {command}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate OS-specific flashing instructions for a sugarkube pi-image workflow run."
        )
    )
    parser.add_argument("--url", required=True, help="GitHub Actions run URL")
    parser.add_argument(
        "--os",
        required=True,
        choices=sorted(SUPPORTED_OS),
        help="Target operating system (linux, mac, windows)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (text or json)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        info = parse_workflow_url(args.url)
        if args.format == "json":
            payload = {
                "workflow": dataclasses.asdict(info),
                "platform": {
                    "key": args.os,
                    "label": SUPPORTED_OS[args.os],
                },
                "steps": instructions_for(args.os, info),
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(render_text(args.os, info))
    except WorkflowFlashError as exc:
        parser.print_usage(sys.stderr)
        parser.exit(2, f"{parser.prog}: error: {exc}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
