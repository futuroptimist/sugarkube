"""Package STL outputs into grouped artifact directories for CI uploads."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WORKFLOW_PATH = Path(".github/workflows/scad-to-stl.yml")


@dataclass(frozen=True)
class FileEntry:
    source: Path
    description: str


@dataclass(frozen=True)
class GroupSpec:
    name: str
    files: tuple[FileEntry, ...]


@dataclass(frozen=True)
class ArtifactSpec:
    dirname: str
    title: str
    summary: str
    docs: tuple[str, ...]
    groups: tuple[GroupSpec, ...]


def _copy_files(stl_root: Path, dest_root: Path, group: GroupSpec) -> None:
    target_dir = dest_root / group.name
    target_dir.mkdir(parents=True, exist_ok=True)
    for entry in group.files:
        source_path = stl_root / entry.source
        if not source_path.exists():
            raise FileNotFoundError(f"Missing expected STL: {source_path}")
        shutil.copy2(source_path, target_dir / source_path.name)


def _write_readme(spec: ArtifactSpec, dest_root: Path) -> None:
    lines = [spec.title, "=" * len(spec.title), "", spec.summary, "", "Contents:"]
    for group in spec.groups:
        lines.append(f"- {group.name}/")
        for entry in group.files:
            lines.append(f"  - {entry.source.name}: {entry.description}")
    lines.extend(
        [
            "",
            "Docs:",
            *[f"- {doc}" for doc in spec.docs],
            "",
            "Workflow:",
            f"- {WORKFLOW_PATH}",
        ]
    )

    readme_path = dest_root / spec.dirname / "README.txt"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stage_artifact(spec: ArtifactSpec, stl_root: Path, output_root: Path) -> None:
    artifact_root = output_root / spec.dirname
    artifact_root.mkdir(parents=True, exist_ok=True)
    for group in spec.groups:
        _copy_files(stl_root, artifact_root, group)
    _write_readme(spec, output_root)


def build_specs() -> tuple[ArtifactSpec, ...]:
    return (
        ArtifactSpec(
            dirname="stl-pi_cluster_stack",
            title="Pi cluster stack STLs",
            summary=(
                "Stacked carrier plates, columns, and fan wall grouped by standoff mode with a "
                "rendered fan/column matrix. Use printed/heatset depending on your insert plan "
                "and pick a fan size from variants/."
            ),
            docs=("docs/pi_cluster_stack.md", "docs/pi_cluster_carrier.md"),
            groups=(
                GroupSpec(
                    name="printed",
                    files=(
                        FileEntry(
                            Path("pi_carrier_stack_printed.stl"),
                            "Stack body for printed columns",
                        ),
                        FileEntry(
                            Path("fan_wall_printed.stl"),
                            "Perpendicular fan plate for printed threads",
                        ),
                        FileEntry(
                            Path("pi_carrier_column_printed.stl"),
                            "Printed column with threads",
                        ),
                    ),
                ),
                GroupSpec(
                    name="heatset",
                    files=(
                        FileEntry(
                            Path("pi_carrier_stack_heatset.stl"),
                            "Stack body with heat-set pockets",
                        ),
                        FileEntry(
                            Path("fan_wall_heatset.stl"),
                            "Fan plate with heat-set insert bosses",
                        ),
                        FileEntry(
                            Path("pi_carrier_column_heatset.stl"),
                            "Column sized for heat-set inserts",
                        ),
                    ),
                ),
                GroupSpec(
                    name="variants",
                    files=(
                        FileEntry(
                            Path("pi_cluster/pi_carrier_stack_printed_fan80.stl"),
                            "Printed columns, 80 mm fan",
                        ),
                        FileEntry(
                            Path("pi_cluster/pi_carrier_stack_printed_fan92.stl"),
                            "Printed columns, 92 mm fan",
                        ),
                        FileEntry(
                            Path("pi_cluster/pi_carrier_stack_printed_fan120.stl"),
                            "Printed columns, 120 mm fan",
                        ),
                        FileEntry(
                            Path("pi_cluster/pi_carrier_stack_brass_chain_fan80.stl"),
                            "Brass-chain columns, 80 mm fan",
                        ),
                        FileEntry(
                            Path("pi_cluster/pi_carrier_stack_brass_chain_fan92.stl"),
                            "Brass-chain columns, 92 mm fan",
                        ),
                        FileEntry(
                            Path("pi_cluster/pi_carrier_stack_brass_chain_fan120.stl"),
                            "Brass-chain columns, 120 mm fan",
                        ),
                    ),
                ),
            ),
        ),
        ArtifactSpec(
            dirname="stl-pi_cluster_carriers",
            title="Pi cluster carrier STLs",
            summary=(
                "Base Raspberry Pi carrier plates in printed and heat-set modes, including the "
                "rotated triple-Pi carrier for Pi 5." 
            ),
            docs=("docs/pi_cluster_carrier.md", "docs/pi_cluster_stack.md"),
            groups=(
                GroupSpec(
                    name="printed",
                    files=(
                        FileEntry(
                            Path("pi_carrier_printed.stl"),
                            "Triple-Pi carrier with printed threads",
                        ),
                        FileEntry(
                            Path("pi5_triple_carrier_rot45_printed.stl"),
                            "Pi 5 rotated carrier with printed threads",
                        ),
                    ),
                ),
                GroupSpec(
                    name="heatset",
                    files=(
                        FileEntry(
                            Path("pi_carrier_heatset.stl"),
                            "Triple-Pi carrier with heat-set pockets",
                        ),
                        FileEntry(
                            Path("pi5_triple_carrier_rot45_heatset.stl"),
                            "Pi 5 rotated carrier with heat-set pockets",
                        ),
                    ),
                ),
            ),
        ),
        ArtifactSpec(
            dirname="stl-sugarkube-enclosure",
            title="Sugarkube enclosure STLs",
            summary=(
                "Solar cube enclosure parts grouped by standoff mode: frame, panel bracket, and "
                "core enclosure body." 
            ),
            docs=("docs/index.md",),
            groups=(
                GroupSpec(
                    name="printed",
                    files=(
                        FileEntry(
                            Path("frame_printed.stl"),
                            "Frame printed with threaded standoffs",
                        ),
                        FileEntry(
                            Path("panel_bracket_printed.stl"),
                            "Solar panel bracket for printed threads",
                        ),
                        FileEntry(
                            Path("sugarkube_printed.stl"),
                            "Main enclosure body with printed threads",
                        ),
                    ),
                ),
                GroupSpec(
                    name="heatset",
                    files=(
                        FileEntry(Path("frame_heatset.stl"), "Frame sized for heat-set inserts"),
                        FileEntry(
                            Path("panel_bracket_heatset.stl"),
                            "Panel bracket sized for inserts",
                        ),
                        FileEntry(
                            Path("sugarkube_heatset.stl"),
                            "Enclosure body sized for inserts",
                        ),
                    ),
                ),
            ),
        ),
    )


def package_artifacts(stl_root: Path, output_root: Path, specs: Iterable[ArtifactSpec]) -> None:
    stl_root = stl_root.resolve()
    output_root = output_root.resolve()
    for spec in specs:
        _stage_artifact(spec, stl_root, output_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage grouped STL artifacts for workflow uploads.",
    )
    parser.add_argument(
        "--stl-dir",
        type=Path,
        default=Path("stl"),
        help="Directory containing rendered STL outputs (default: stl).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("dist/stl_artifacts"),
        help="Directory where grouped artifact trees will be staged (default: dist/stl_artifacts).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    specs = build_specs()
    try:
        package_artifacts(args.stl_dir, args.out_dir, specs)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
