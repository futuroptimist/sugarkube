#!/usr/bin/env python3
"""Generate release manifest, notes, and metadata outputs for sugarkube images."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
from typing import Any, Dict, Iterable, Tuple


def _load_metadata(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"metadata file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_now() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        now = dt.datetime.utcfromtimestamp(int(epoch))
    else:
        now = dt.datetime.utcnow()
    return now.replace(microsecond=0).isoformat() + "Z"


def _human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or (hours and secs):
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _version_for_channel(channel: str, commit: str, build_end: str) -> Tuple[str, bool, str]:
    # Stable releases follow vYYYY.MM.DD+g<sha>. Nightlies use nightly-YYYYMMDD.
    end_date = dt.datetime.fromisoformat(build_end.replace("Z", "+00:00"))
    if channel == "nightly":
        tag = f"nightly-{end_date:%Y%m%d}"
        name = f"Sugarkube Pi Image nightly {end_date:%Y-%m-%d}"
        return tag, True, name
    tag = f"v{end_date:%Y.%m.%d}+g{commit[:7]}"
    name = f"Sugarkube Pi Image {end_date:%Y-%m-%d}"
    return tag, False, name


def _render_stage_table(stage_durations: Dict[str, Any]) -> str:
    if not stage_durations:
        return "No stage timing data was captured."
    header = "| Stage | Duration |\n| --- | --- |"
    rows = [
        f"| `{stage}` | `{_human_duration(duration)}` |"
        for stage, duration in stage_durations.items()
    ]
    return "\n".join([header, *rows])


def _render_checksum_table(artifacts: Iterable[Dict[str, Any]]) -> str:
    header = "| Artifact | SHA-256 | Size |\n| --- | --- | --- |"
    rows = []
    for artifact in artifacts:
        size = artifact.get("size_bytes")
        size_str = f"{size / (1024 * 1024):.1f} MiB" if size else "?"
        digest = artifact.get("contains_sha256") or artifact.get("sha256")
        rows.append(f"| `{artifact['name']}` | `{digest}` | {size_str} |")
    return "\n".join([header, *rows])


def _build_manifest(
    metadata: Dict[str, Any],
    channel: str,
    repo: str,
    run: Dict[str, Any],
) -> Dict[str, Any]:
    image_path = pathlib.Path(metadata["image"]["path"]).name
    checksum_path = pathlib.Path(metadata["checksum_path"]).name
    checksum_file_hash = hashlib.sha256(
        pathlib.Path(metadata["checksum_path"]).read_bytes()
    ).hexdigest()
    manifest = {
        "version": None,  # populated later once tag computed
        "channel": channel,
        "generated_at": _iso_now(),
        "source": {
            "repository": repo,
            "commit": metadata["repository"].get("commit"),
            "ref": metadata["repository"].get("ref"),
            "workflow": run,
        },
        "build": {
            "start": metadata["build"]["start"],
            "end": metadata["build"]["end"],
            "duration_seconds": metadata["build"]["duration_seconds"],
            "stage_durations": metadata["build"].get("stage_durations", {}),
            "pi_gen": metadata["build"].get("pi_gen", {}),
            "runner": metadata["build"].get("runner", {}),
        },
        "artifacts": [
            {
                "name": image_path,
                "sha256": metadata["image"]["sha256"],
                "size_bytes": metadata["image"].get("size_bytes"),
                "path": image_path,
            },
            {
                "name": checksum_path,
                "sha256": checksum_file_hash,
                "size_bytes": pathlib.Path(metadata["checksum_path"]).stat().st_size,
                "path": checksum_path,
                "contains_sha256": metadata["image"]["sha256"],
            },
        ],
        "verifier": metadata.get("verifier", {}),
        "options": metadata.get("options", {}),
        "build_log": pathlib.Path(metadata.get("build_log_path") or "").name or None,
    }
    return manifest


def _write_manifest(path: pathlib.Path, manifest: Dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_notes(
    path: pathlib.Path,
    manifest: Dict[str, Any],
    repo: str,
    version: str,
) -> None:
    commit = manifest["source"].get("commit")
    commit_link = (
        f"[`{commit[:7]}`](https://github.com/{repo}/commit/{commit})" if commit else "(unknown)"
    )
    pi_gen = manifest["build"].get("pi_gen", {})
    pi_gen_commit = pi_gen.get("commit")
    if pi_gen_commit:
        base_url = pi_gen.get("url", "https://github.com/RPi-Distro/pi-gen")
        pi_gen_link = f"[`{pi_gen_commit[:7]}`]({base_url}/commit/{pi_gen_commit})"
    else:
        pi_gen_link = "(unknown)"
    stage_table = _render_stage_table(manifest["build"].get("stage_durations", {}))
    artifact_table = _render_checksum_table(manifest["artifacts"])
    lines = [
        f"# Sugarkube Pi Image {version}",
        "",
        f"- Source commit: {commit_link}",
        f"- pi-gen: branch `{pi_gen.get('branch', '?')}` @ {pi_gen_link}",
        f"- Build duration: `{_human_duration(manifest['build'].get('duration_seconds', 0))}`",
        "",
        "## Stage timings",
        stage_table,
        "",
        "## Artifact checksums",
        artifact_table,
        "",
        "The attached manifest (`sugarkube.img.xz.manifest.json`) contains the",
        "full provenance record including options and workflow metadata.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_outputs(path: pathlib.Path, **outputs: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, help="Path to build metadata JSON")
    parser.add_argument(
        "--manifest-output",
        required=True,
        help="Where to write the release manifest JSON",
    )
    parser.add_argument(
        "--notes-output",
        required=True,
        help="Release notes markdown destination",
    )
    parser.add_argument(
        "--release-channel",
        default="stable",
        choices=["stable", "nightly"],
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="<owner>/<repo> slug for commit links",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--workflow", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    metadata_path = pathlib.Path(args.metadata)
    manifest_path = pathlib.Path(args.manifest_output)
    notes_path = pathlib.Path(args.notes_output)

    metadata = _load_metadata(metadata_path)
    manifest = _build_manifest(
        metadata,
        args.release_channel,
        args.repo,
        {
            "run_id": args.run_id,
            "run_attempt": args.run_attempt,
            "workflow": args.workflow,
        },
    )

    commit = manifest["source"].get("commit", "")
    version, prerelease, release_name = _version_for_channel(
        args.release_channel,
        commit,
        manifest["build"].get("end"),
    )
    manifest["version"] = version

    _write_manifest(manifest_path, manifest)
    _write_notes(notes_path, manifest, args.repo, version)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        _write_outputs(
            pathlib.Path(github_output),
            tag=version,
            name=release_name,
            prerelease=str(prerelease).lower(),
            make_latest=str(not prerelease).lower(),
            manifest_path=str(manifest_path),
            notes_path=str(notes_path),
        )

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via unit tests
    raise SystemExit(main())
