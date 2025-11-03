"""Render the documented pi_carrier_stack STL matrix via OpenSCAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_COLUMN_MODES = ("printed", "brass_chain")
DEFAULT_FAN_SIZES = (80, 92, 120)


def render_variants(
    *,
    openscad: str,
    scad_path: Path,
    output_dir: Path,
    column_modes: tuple[str, ...] = DEFAULT_COLUMN_MODES,
    fan_sizes: tuple[int, ...] = DEFAULT_FAN_SIZES,
) -> None:
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for column_mode in column_modes:
        for fan_size in fan_sizes:
            output_path = output_dir / f"pi_carrier_stack_{column_mode}_fan{fan_size}.stl"
            command = [
                openscad,
                "-o",
                str(output_path),
                "--export-format",
                "binstl",
                "-D",
                f'column_mode="{column_mode}"',
                "-D",
                f"fan_size={fan_size}",
                "--",
                str(scad_path),
            ]
            subprocess.run(command, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render pi_carrier_stack STL variants for documented fan/column combinations.",
    )
    parser.add_argument(
        "--openscad",
        default="openscad",
        help="Path to the OpenSCAD binary (default: %(default)s).",
    )
    parser.add_argument(
        "--scad-path",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1] / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
        ),
        help="Path to pi_carrier_stack.scad (default: repository copy).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("stl/pi_cluster"),
        help="Directory where STL outputs will be written (default: stl/pi_cluster).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        render_variants(
            openscad=args.openscad,
            scad_path=args.scad_path,
            output_dir=args.output_dir,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        parser.error(str(exc))
    except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaces command failure
        return exc.returncode
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
