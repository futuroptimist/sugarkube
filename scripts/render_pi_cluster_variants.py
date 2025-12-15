"""Render modular pi_carrier_stack STL parts via OpenSCAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_STANDOFF_MODES = ("heatset", "printed")
DEFAULT_FAN_SIZES = (80, 92, 120)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def render_variants(
    *,
    openscad: str,
    scad_path: Path,
    output_dir: Path,
    standoff_modes: tuple[str, ...] = DEFAULT_STANDOFF_MODES,
    fan_sizes: tuple[int, ...] = DEFAULT_FAN_SIZES,
    render_assembly: bool = True,
) -> None:
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for standoff_mode in standoff_modes:
        output_path = output_dir / f"carrier_level_{standoff_mode}.stl"
        _run(
            [
                openscad,
                "-o",
                str(output_path),
                "--export-format",
                "binstl",
                "-D",
                f'standoff_mode="{standoff_mode}"',
                "-D",
                "stack_edge_margin=15",
                "-D",
                "export_part=\"carrier_level\"",
                "--",
                str(scad_path),
            ]
        )

    _run(
        [
            openscad,
            "-o",
            str(output_dir / "stack_post.stl"),
            "--export-format",
            "binstl",
            "-D",
            "export_part=\"post\"",
            "--",
            str(scad_path),
        ]
    )

    for fan_size in fan_sizes:
        _run(
            [
                openscad,
                "-o",
                str(output_dir / f"fan_wall_fan{fan_size}.stl"),
                "--export-format",
                "binstl",
                "-D",
                f"fan_size={fan_size}",
                "-D",
                "export_part=\"fan_wall\"",
                "--",
                str(scad_path),
            ]
        )

        _run(
            [
                openscad,
                "-o",
                str(output_dir / f"fan_adapter_fan{fan_size}.stl"),
                "--export-format",
                "binstl",
                "-D",
                f"fan_size={fan_size}",
                "-D",
                "export_part=\"fan_adapter\"",
                "--",
                str(scad_path),
            ]
        )

        if render_assembly:
            _run(
                [
                    openscad,
                    "-o",
                    str(output_dir / f"assembly_fan{fan_size}.stl"),
                    "--export-format",
                    "binstl",
                    "-D",
                    f"fan_size={fan_size}",
                    "-D",
                    "export_part=\"assembly\"",
                    "--",
                    str(scad_path),
                ]
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render modular pi_carrier_stack STL parts (carriers, posts, adapters, walls).",
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
