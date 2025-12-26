"""Render the modular pi_carrier_stack STL set via OpenSCAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_STANDOFF_MODES = ("printed", "heatset")
DEFAULT_FAN_SIZES = (80, 92, 120)
DEFAULT_STACK_PLATE_THICKNESS = 3.0
DEFAULT_STACK_EDGE_MARGIN = 15


def render_variants(
    *,
    openscad: str,
    scad_path: Path,
    output_dir: Path,
    standoff_modes: tuple[str, ...] = DEFAULT_STANDOFF_MODES,
    fan_sizes: tuple[int, ...] = DEFAULT_FAN_SIZES,
    stack_plate_thickness: float = DEFAULT_STACK_PLATE_THICKNESS,
    stack_edge_margin: float = DEFAULT_STACK_EDGE_MARGIN,
) -> None:
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    carrier_scad_path = scad_path.parent / "pi_carrier.scad"
    if not carrier_scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {carrier_scad_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for mode in standoff_modes:
        stack_carrier_output = output_dir / "carriers" / mode / f"pi_carrier_stack_{mode}.stl"
        stack_carrier_output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                openscad,
                "-o",
                str(stack_carrier_output),
                "--export-format",
                "binstl",
                "-D",
                f'standoff_mode="{mode}"',
                "-D",
                "include_stack_mounts=true",
                "-D",
                f"plate_thickness={stack_plate_thickness}",
                "-D",
                f"stack_edge_margin={stack_edge_margin}",
                "-D",
                f"edge_margin={stack_edge_margin}",
                "--",
                str(carrier_scad_path),
            ],
            check=True,
        )

        carrier_level_output = (
            output_dir / "preview" / f"pi_carrier_stack_carrier_level_{mode}.stl"
        )
        carrier_level_output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                openscad,
                "-o",
                str(carrier_level_output),
                "--export-format",
                "binstl",
                "-D",
                'export_part="carrier_level"',
                "-D",
                f'standoff_mode="{mode}"',
                "-D",
                f"stack_edge_margin={stack_edge_margin}",
                "--",
                str(scad_path),
            ],
            check=True,
        )

    for subdir, part in (("posts", "post"), ("fan_adapters", "fan_adapter")):
        output_path = output_dir / subdir / f"pi_carrier_stack_{part}.stl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            openscad,
            "-o",
            str(output_path),
            "--export-format",
            "binstl",
            "-D",
            f'export_part="{part}"',
            "-D",
            "stack_edge_margin=15",
            "--",
            str(scad_path),
        ]
        subprocess.run(command, check=True)

    for fan_size in fan_sizes:
        output_path = output_dir / "fan_walls" / f"pi_carrier_stack_fan_wall_fan{fan_size}.stl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            openscad,
            "-o",
            str(output_path),
            "--export-format",
            "binstl",
            "-D",
            "export_part=\"fan_wall\"",
            "-D",
            f"fan_size={fan_size}",
            "-D",
            "stack_edge_margin=15",
            "--",
            str(scad_path),
        ]
        subprocess.run(command, check=True)

    preview_path = output_dir / "preview" / "pi_carrier_stack_preview.stl"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            openscad,
            "-o",
            str(preview_path),
            "--export-format",
            "binstl",
            "-D",
            "export_part=\"assembly\"",
            "-D",
            "stack_edge_margin=15",
            "--",
            str(scad_path),
        ],
        check=True,
    )


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
