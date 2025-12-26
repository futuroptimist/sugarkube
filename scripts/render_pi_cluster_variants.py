"""Render the modular pi_carrier_stack STL set via OpenSCAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_STANDOFF_MODES = ("printed", "heatset")
DEFAULT_FAN_SIZES = (80, 92, 120)


def render_variants(
    *,
    openscad: str,
    scad_path: Path,
    carrier_scad_path: Path | None = None,
    output_dir: Path,
    standoff_modes: tuple[str, ...] = DEFAULT_STANDOFF_MODES,
    fan_sizes: tuple[int, ...] = DEFAULT_FAN_SIZES,
) -> None:
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    carrier_scad = carrier_scad_path or scad_path.parent / "pi_carrier.scad"
    if not carrier_scad.exists():
        raise FileNotFoundError(f"SCAD file not found: {carrier_scad}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for mode in standoff_modes:
        carrier_output = output_dir / "carriers" / f"pi_carrier_stack_mounts_{mode}.stl"
        carrier_output.parent.mkdir(parents=True, exist_ok=True)
        carrier_cmd = [
            openscad,
            "-o",
            str(carrier_output),
            "--export-format",
            "binstl",
            "-D",
            "include_stack_mounts=true",
            "-D",
            f'standoff_mode="{mode}"',
            "-D",
            "plate_thickness=3",
            "-D",
            "stack_edge_margin=15",
            "-D",
            "stack_pocket_d=9",
            "-D",
            "stack_pocket_depth=1.2",
            "--",
            str(carrier_scad),
        ]
        subprocess.run(carrier_cmd, check=True)

        preview_output = (
            output_dir / "preview" / f"pi_carrier_stack_carrier_level_{mode}.stl"
        )
        preview_output.parent.mkdir(parents=True, exist_ok=True)
        preview_cmd = [
            openscad,
            "-o",
            str(preview_output),
            "--export-format",
            "binstl",
            "-D",
            'export_part="carrier_level"',
            "-D",
            f'standoff_mode="{mode}"',
            "-D",
            "stack_edge_margin=15",
            "--",
            str(scad_path),
        ]
        subprocess.run(preview_cmd, check=True)

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
        "--carrier-scad-path",
        type=Path,
        default=None,
        help="Path to pi_carrier.scad (default: sibling next to pi_carrier_stack.scad).",
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
            carrier_scad_path=args.carrier_scad_path,
            output_dir=args.output_dir,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        parser.error(str(exc))
    except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaces command failure
        return exc.returncode
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
