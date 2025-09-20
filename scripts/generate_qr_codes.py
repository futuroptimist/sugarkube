#!/usr/bin/env python3
"""Generate printable QR codes for sugarkube Pi carrier labels."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from qrcodegen import QrCode


@dataclass(frozen=True)
class QrLabel:
    slug: str
    title: str
    url: str
    note: str

    def svg_filename(self) -> str:
        return f"{self.slug}.svg"


DEFAULT_LABELS: List[QrLabel] = [
    QrLabel(
        slug="pi-image-quickstart",
        title="Pi Image Quickstart",
        url="https://github.com/sugarkube/sugarkube/blob/main/docs/pi_image_quickstart.md",
        note="Scan to open the Pi image quickstart guide",
    ),
    QrLabel(
        slug="pi-boot-troubleshooting",
        title="Pi Boot Troubleshooting",
        url="https://github.com/sugarkube/sugarkube/blob/main/docs/pi_boot_troubleshooting.md",
        note="Scan if the node fails to reach k3s or token.place",
    ),
]


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate SVG QR codes that can be printed and attached to the pi_carrier enclosure."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "images" / "qr",
        help="Directory where the SVG assets and manifest.json will be written.",
    )
    parser.add_argument(
        "--border",
        type=int,
        default=2,
        help="Quiet-zone border to include around the QR code (in modules).",
    )
    parser.add_argument(
        "--module-size",
        type=int,
        default=12,
        help="Module size multiplier applied when exporting to SVG.",
    )
    parser.add_argument(
        "--manifest-name",
        default="manifest.json",
        help="Filename for the JSON manifest written alongside the SVG assets.",
    )
    return parser.parse_args(argv)


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def qr_to_svg(qr: QrCode, border: int, module_size: int) -> str:
    if border < 0:
        raise ValueError("Border must be non-negative")
    if module_size <= 0:
        raise ValueError("Module size must be positive")

    size = qr.get_size()
    viewbox_size = size + border * 2
    pixel_size = viewbox_size * module_size

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"',
        f'     viewBox="0 0 {viewbox_size} {viewbox_size}"',
        f'     width="{pixel_size}" height="{pixel_size}"',
        '     shape-rendering="crispEdges">',
        '  <rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    for y in range(size):
        for x in range(size):
            if qr.get_module(x, y):
                parts.append(
                    (
                        f'  <rect x="{x + border}" y="{y + border}" width="1" height="1"'
                        ' fill="#000000"/>'
                    )
                )

    parts.append("</svg>")
    return "\n".join(parts)


def generate_svg(label: QrLabel, border: int, module_size: int) -> str:
    qr = QrCode.encode_text(label.url, QrCode.Ecc.QUARTILE)
    return qr_to_svg(qr, border=border, module_size=module_size)


def write_assets(labels: List[QrLabel], args: argparse.Namespace) -> None:
    ensure_output_dir(args.output_dir)
    manifest = []
    for label in labels:
        svg_path = args.output_dir / label.svg_filename()
        svg = generate_svg(label, border=args.border, module_size=args.module_size)
        svg_path.write_text(svg, encoding="utf-8")
        manifest.append(
            {
                "slug": label.slug,
                "title": label.title,
                "url": label.url,
                "note": label.note,
                "file": svg_path.name,
            }
        )
    manifest_path = args.output_dir / args.manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    write_assets(DEFAULT_LABELS, args)
    print(f"Wrote {len(DEFAULT_LABELS)} QR labels to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
