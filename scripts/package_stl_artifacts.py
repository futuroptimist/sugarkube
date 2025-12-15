"""Package STL outputs into grouped artifact directories with READMEs."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

REPO_WORKFLOW_PATH = ".github/workflows/scad-to-stl.yml"


@dataclass(frozen=True)
class ArtifactFile:
    source: Path
    dest_subdir: str
    description: str


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    summary: str
    files: tuple[ArtifactFile, ...]
    doc_paths: tuple[str, ...]


def _build_artifacts() -> tuple[ArtifactSpec, ...]:
    return (
        ArtifactSpec(
            name="stl-pi_cluster_stack",
            summary="Pi carrier stack bundle (stack, columns, and fan wall variants).",
            files=(
                ArtifactFile(Path("pi_carrier_stack_printed.stl"), "printed", "Stack body"),
                ArtifactFile(Path("fan_wall_printed.stl"), "printed", "Perpendicular fan wall"),
                ArtifactFile(Path("pi_carrier_column_printed.stl"), "printed", "Stack columns"),
                ArtifactFile(Path("pi_carrier_stack_heatset.stl"), "heatset", "Stack body"),
                ArtifactFile(Path("fan_wall_heatset.stl"), "heatset", "Perpendicular fan wall"),
                ArtifactFile(Path("pi_carrier_column_heatset.stl"), "heatset", "Stack columns"),
                ArtifactFile(
                    Path("pi_cluster/pi_carrier_stack_printed_fan80.stl"),
                    "variants",
                    "Printed columns + 80 mm fan wall",
                ),
                ArtifactFile(
                    Path("pi_cluster/pi_carrier_stack_printed_fan92.stl"),
                    "variants",
                    "Printed columns + 92 mm fan wall",
                ),
                ArtifactFile(
                    Path("pi_cluster/pi_carrier_stack_printed_fan120.stl"),
                    "variants",
                    "Printed columns + 120 mm fan wall",
                ),
                ArtifactFile(
                    Path("pi_cluster/pi_carrier_stack_brass_chain_fan80.stl"),
                    "variants",
                    "Brass-chain columns + 80 mm fan wall",
                ),
                ArtifactFile(
                    Path("pi_cluster/pi_carrier_stack_brass_chain_fan92.stl"),
                    "variants",
                    "Brass-chain columns + 92 mm fan wall",
                ),
                ArtifactFile(
                    Path("pi_cluster/pi_carrier_stack_brass_chain_fan120.stl"),
                    "variants",
                    "Brass-chain columns + 120 mm fan wall",
                ),
            ),
            doc_paths=(
                "docs/pi_cluster_stack.md",
                "docs/pi_cluster_carrier.md",
            ),
        ),
        ArtifactSpec(
            name="stl-pi_cluster_carriers",
            summary="Triple-Pi carrier plates for standalone or stacked builds.",
            files=(
                ArtifactFile(Path("pi_carrier_printed.stl"), "printed", "Triple carrier plate"),
                ArtifactFile(
                    Path("pi5_triple_carrier_rot45_printed.stl"),
                    "printed",
                    "Pi 5 carrier rotated 45 degrees",
                ),
                ArtifactFile(Path("pi_carrier_heatset.stl"), "heatset", "Triple carrier plate"),
                ArtifactFile(
                    Path("pi5_triple_carrier_rot45_heatset.stl"),
                    "heatset",
                    "Pi 5 carrier rotated 45 degrees",
                ),
            ),
            doc_paths=(
                "docs/pi_cluster_carrier.md",
                "docs/pi_cluster_stack.md",
            ),
        ),
        ArtifactSpec(
            name="stl-sugarkube-enclosure",
            summary="Sugarkube enclosure parts (frame, panel brackets, enclosure shell).",
            files=(
                ArtifactFile(
                    Path("frame_printed.stl"),
                    "printed",
                    "Frame for printed standoffs",
                ),
                ArtifactFile(
                    Path("panel_bracket_printed.stl"),
                    "printed",
                    "Panel mounting brackets",
                ),
                ArtifactFile(
                    Path("sugarkube_printed.stl"),
                    "printed",
                    "Sugarkube enclosure shell",
                ),
                ArtifactFile(
                    Path("frame_heatset.stl"),
                    "heatset",
                    "Frame for heat-set inserts",
                ),
                ArtifactFile(
                    Path("panel_bracket_heatset.stl"),
                    "heatset",
                    "Panel mounting brackets",
                ),
                ArtifactFile(
                    Path("sugarkube_heatset.stl"),
                    "heatset",
                    "Sugarkube enclosure shell",
                ),
            ),
            doc_paths=(
                "docs/build_guide.md",
                "docs/pi_cluster_stack.md",
            ),
        ),
    )


def _copy_file(stl_dir: Path, stage_dir: Path, artifact_file: ArtifactFile) -> Path:
    source_path = stl_dir / artifact_file.source
    if not source_path.exists():
        raise FileNotFoundError(f"Expected STL missing: {source_path}")

    target_dir = stage_dir / artifact_file.dest_subdir if artifact_file.dest_subdir else stage_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / source_path.name
    shutil.copy2(source_path, target_path)
    return target_path


def _write_readme(stage_dir: Path, spec: ArtifactSpec) -> None:
    lines = [
        spec.summary,
        "",
        "Contents:",
    ]

    for artifact_file in spec.files:
        relative_dir = artifact_file.dest_subdir or "."
        lines.append(
            f"- {relative_dir}/{artifact_file.source.name} — {artifact_file.description}"
        )

    lines.extend(
        [
            "",
            "Docs:",
            *[f"- {path}" for path in spec.doc_paths],
            "",
            "Build workflow:",
            f"- {REPO_WORKFLOW_PATH}",
        ]
    )

    readme_path = stage_dir / "README.txt"
    readme_path.write_text(dedent("\n".join(lines)).strip() + "\n", encoding="utf-8")


def stage_artifacts(*, stl_dir: Path, out_dir: Path, sha: str | None) -> tuple[Path, ...]:
    artifacts: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in _build_artifacts():
        artifact_dir_name = f"{spec.name}-{sha}" if sha else spec.name
        stage_dir = out_dir / artifact_dir_name
        stage_dir.mkdir(parents=True, exist_ok=True)

        for artifact_file in spec.files:
            _copy_file(stl_dir, stage_dir, artifact_file)

        _write_readme(stage_dir, spec)
        artifacts.append(stage_dir)

    return tuple(artifacts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Group STL outputs into uploadable artifact directories with READMEs.",
    )
    parser.add_argument("--stl-dir", type=Path, default=Path("stl"), help="Source STL directory.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("dist/stl_artifacts"),
        help="Where grouped artifact directories will be written.",
    )
    parser.add_argument(
        "--sha",
        help="Optional commit SHA appended to artifact directory names for upload clarity.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    stage_artifacts(stl_dir=args.stl_dir, out_dir=args.out_dir, sha=args.sha)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
