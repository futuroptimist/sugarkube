"""Render modular pi_carrier_stack parts via OpenSCAD."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_STANDOFF_MODES = ("heatset", "printed")
DEFAULT_FAN_SIZES = (80, 92, 120)


def _run_openscad(openscad: str, args: list[str]) -> None:
    command = [openscad, *args]
    subprocess.run(command, check=True)


def render_variants(
    *,
    openscad: str,
    scad_path: Path,
    output_dir: Path,
    standoff_modes: tuple[str, ...] = DEFAULT_STANDOFF_MODES,
    fan_sizes: tuple[int, ...] = DEFAULT_FAN_SIZES,
) -> None:
    if not scad_path.exists():
        raise FileNotFoundError(f"SCAD file not found: {scad_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for mode in standoff_modes:
        output_path = output_dir / f"pi_carrier_stack_carrier_level_{mode}.stl"
        _run_openscad(
            openscad,
            [
                "-o",
                str(output_path),
                "--export-format",
                "binstl",
                "-D",
                f'export_part="carrier_level"',
                "-D",
                f'standoff_mode="{mode}"',
                "--",
                str(scad_path),
            ],
        )

    # Single-mode parts (do not vary with standoff type)
    _run_openscad(
        openscad,
        [
            "-o",
            str(output_dir / "pi_stack_post.stl"),
            "--export-format",
            "binstl",
            "-D",
            'export_part="post"',
            "--",
            str(scad_path),
        ],
    )

    _run_openscad(
        openscad,
        [
            "-o",
            str(output_dir / "pi_stack_fan_adapter.stl"),
            "--export-format",
            "binstl",
            "-D",
            'export_part="fan_adapter"',
            "--",
            str(scad_path),
        ],
    )

    for fan_size in fan_sizes:
        _run_openscad(
            openscad,
            [
                "-o",
                str(output_dir / f"fan_wall_fan{fan_size}.stl"),
                "--export-format",
                "binstl",
                "-D",
                f'export_part="fan_wall"',
                "-D",
                f"fan_size={fan_size}",
                "--",
                str(scad_path),
            ],
        )

    # Optional preview assembly using the largest fan
    _run_openscad(
        openscad,
        [
            "-o",
            str(output_dir / "pi_carrier_stack_preview.stl"),
            "--export-format",
            "binstl",
            "-D",
            f'export_part="assembly"',
            "-D",
            f"fan_size={max(fan_sizes)}",
            "--",
            str(scad_path),
        ],
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
