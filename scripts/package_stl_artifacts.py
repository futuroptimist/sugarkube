from __future__ import annotations

"""Package grouped STL artifacts for the scad-to-stl workflow."""

import argparse
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/scad-to-stl.yml")
README_WIDTH = 100


@dataclass(frozen=True)
class FileSpec:
    """Describe a file to copy into a packaged artifact."""

    source: str
    description: str


@dataclass(frozen=True)
class ArtifactSpec:
    """Describe a grouped STL artifact."""

    base_name: str
    title: str
    description: str
    doc_links: list[str]
    sections: dict[str, list[FileSpec]]


def _build_specs() -> list[ArtifactSpec]:
    """Return the grouped artifact definitions."""

    return [
        ArtifactSpec(
            base_name="stl-pi_cluster_stack",
            title="Pi carrier stack with fan wall",
            description=" ".join(
                [
                    "Stacked triple-Pi carrier with printed columns, brass-chain columns, and",
                    "perpendicular fan wall. Use the printed/heatset sets for common builds or the",
                    "variants folder for fan-size sweeps.",
                ]
            ),
            doc_links=["docs/pi_cluster_stack.md", "docs/pi_cluster_stack_assembly.md"],
            sections={
                "printed": [
                    FileSpec(
                        "pi_carrier_stack_printed.stl",
                        "Stacked carrier with printed columns",
                    ),
                    FileSpec(
                        "fan_wall_printed.stl",
                        "Fan wall sized for M3 heat-set inserts",
                    ),
                    FileSpec(
                        "pi_carrier_column_printed.stl",
                        "Printed column with embedded heat-set inserts",
                    ),
                ],
                "heatset": [
                    FileSpec(
                        "pi_carrier_stack_heatset.stl",
                        "Stacked carrier with heat-set inserts",
                    ),
                    FileSpec(
                        "fan_wall_heatset.stl",
                        "Fan wall ready for heat-set inserts",
                    ),
                    FileSpec(
                        "pi_carrier_column_heatset.stl",
                        "Heat-set column variant matching the printed carrier",
                    ),
                ],
                "variants": [
                    FileSpec(
                        "pi_cluster/pi_carrier_stack_printed_fan80.stl",
                        "Printed columns with 80 mm fan wall",
                    ),
                    FileSpec(
                        "pi_cluster/pi_carrier_stack_printed_fan92.stl",
                        "Printed columns with 92 mm fan wall",
                    ),
                    FileSpec(
                        "pi_cluster/pi_carrier_stack_printed_fan120.stl",
                        "Printed columns with 120 mm fan wall",
                    ),
                    FileSpec(
                        "pi_cluster/pi_carrier_stack_brass_chain_fan80.stl",
                        "Brass-chain columns with 80 mm fan wall",
                    ),
                    FileSpec(
                        "pi_cluster/pi_carrier_stack_brass_chain_fan92.stl",
                        "Brass-chain columns with 92 mm fan wall",
                    ),
                    FileSpec(
                        "pi_cluster/pi_carrier_stack_brass_chain_fan120.stl",
                        "Brass-chain columns with 120 mm fan wall",
                    ),
                ],
            },
        ),
        ArtifactSpec(
            base_name="stl-pi_cluster_carriers",
            title="Pi carrier plates",
            description=" ".join(
                [
                    "Base triple-Pi carrier plates used by the stacked design.",
                    "Includes rotated Pi 5",
                    "layout and standard carrier in printed and heat-set forms.",
                ]
            ),
            doc_links=["docs/pi_cluster_carrier.md", "docs/pi_carrier_field_guide.md"],
            sections={
                "printed": [
                    FileSpec(
                        "pi_carrier_printed.stl",
                        "Standard carrier plate with printed threads",
                    ),
                    FileSpec(
                        "pi5_triple_carrier_rot45_printed.stl",
                        "Rotated Pi 5 triple carrier with printed threads",
                    ),
                ],
                "heatset": [
                    FileSpec(
                        "pi_carrier_heatset.stl",
                        "Standard carrier plate with heat-set inserts",
                    ),
                    FileSpec(
                        "pi5_triple_carrier_rot45_heatset.stl",
                        "Rotated Pi 5 triple carrier with heat-set inserts",
                    ),
                ],
            },
        ),
        ArtifactSpec(
            base_name="stl-sugarkube-enclosure",
            title="Sugarkube enclosure",
            description=" ".join(
                [
                    "Solar cube enclosure parts: frame, panel brackets, and the Sugarkube shell.",
                    "Choose printed or heat-set variants to match your hardware.",
                ]
            ),
            doc_links=["docs/build_guide.md"],
            sections={
                "printed": [
                    FileSpec(
                        "frame_printed.stl",
                        "Frame with printed threaded pockets",
                    ),
                    FileSpec(
                        "panel_bracket_printed.stl",
                        "Panel bracket for the enclosure",
                    ),
                    FileSpec("sugarkube_printed.stl", "Sugarkube enclosure body"),
                ],
                "heatset": [
                    FileSpec("frame_heatset.stl", "Frame tuned for heat-set inserts"),
                    FileSpec(
                        "panel_bracket_heatset.stl",
                        "Panel bracket with insert seats",
                    ),
                    FileSpec("sugarkube_heatset.stl", "Enclosure body with insert pockets"),
                ],
            },
        ),
    ]


def _format_readme(spec: ArtifactSpec) -> str:
    wrapped_description = textwrap.fill(spec.description, width=README_WIDTH)
    sections: list[str] = ["Contents:"]
    for section, files in spec.sections.items():
        sections.append(f"- {section}/")
        for file_spec in files:
            sections.append(f"  - {file_spec.source}: {file_spec.description}")
    docs_block = ["Docs:"] + [f"- {link}" for link in spec.doc_links]
    docs_block.append(f"- {WORKFLOW_PATH}")
    body = "\n".join(sections + ["", *docs_block])
    return f"{spec.title}\n\n{wrapped_description}\n\n{body}\n"


def _copy_files(stl_dir: Path, artifact_root: Path, sections: dict[str, list[FileSpec]]) -> None:
    for section, files in sections.items():
        destination = artifact_root / section
        destination.mkdir(parents=True, exist_ok=True)
        for file_spec in files:
            source_path = stl_dir / file_spec.source
            if not source_path.exists():
                raise FileNotFoundError(f"Expected STL missing: {source_path}")
            shutil.copy2(source_path, destination / source_path.name)


def stage_artifacts(*, stl_dir: Path, out_dir: Path, sha: str) -> list[Path]:
    if not sha:
        raise ValueError("A commit SHA is required to name the artifacts")
    specs = _build_specs()
    staged_paths: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        artifact_root = out_dir / f"{spec.base_name}-{sha}"
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
        artifact_root.mkdir(parents=True)
        _copy_files(stl_dir, artifact_root, spec.sections)
        readme = artifact_root / "README.txt"
        readme.write_text(_format_readme(spec), encoding="utf-8")
        staged_paths.append(artifact_root)

    return staged_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package grouped STL artifacts for upload.",
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
        help="Directory where grouped artifacts will be staged (default: dist/stl_artifacts).",
    )
    parser.add_argument(
        "--sha",
        default=None,
        help="Commit SHA used to suffix artifact names (default: $GITHUB_SHA).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sha = args.sha or os.environ.get("GITHUB_SHA")  # type: ignore[attr-defined]
    try:
        staged = stage_artifacts(stl_dir=args.stl_dir, out_dir=args.out_dir, sha=sha or "")
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    for path in staged:
        print(f"Staged: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
