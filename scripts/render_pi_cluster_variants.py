"""Render modular pi_carrier_stack parts and documented fan sizes via OpenSCAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_FAN_SIZES = (80, 92, 120)
STACK_MODES = ("heatset", "printed")


def _run_openscad(openscad: str, scad_path: Path, output: Path, definitions: list[str]) -> None:
    command = [
        openscad,
        "-o",
        str(output),
        "--export-format",
        "binstl",
        *[item for definition in definitions for item in ("-D", definition)],
        "--",
        str(scad_path),
    ]
    subprocess.run(command, check=True)


def render_variants(
    *,
    openscad: str,
    scad_path: Path,
    output_dir: Path,
    fan_sizes: tuple[int, ...] = DEFAULT_FAN_SIZES,
) -> None:
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for mode in STACK_MODES:
        output_path = output_dir / f"pi_carrier_stack_carrier_level_{mode}.stl"
        _run_openscad(
            openscad,
            scad_path,
            output_path,
            [
                f'export_part="carrier_level"',
                f'standoff_mode="{mode}"',
                "stack_edge_margin=15",
            ],
        )

    _run_openscad(
        openscad,
        scad_path,
        output_dir / "pi_carrier_stack_post.stl",
        ['export_part="post"'],
    )

    _run_openscad(
        openscad,
        scad_path,
        output_dir / "pi_carrier_stack_fan_adapter.stl",
        ['export_part="fan_adapter"'],
    )

    for fan_size in fan_sizes:
        _run_openscad(
            openscad,
            scad_path,
            output_dir / f"pi_carrier_stack_fan_wall_fan{fan_size}.stl",
            [
                f'export_part="fan_wall"',
                f"fan_size={fan_size}",
            ],
        )

    _run_openscad(
        openscad,
        scad_path,
        output_dir / "pi_carrier_stack_preview_assembly.stl",
        ['export_part="assembly"'],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render pi_carrier_stack modular parts and fan-wall sizes.",
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
