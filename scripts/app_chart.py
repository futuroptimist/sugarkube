#!/usr/bin/env python3
"""Inspect, bump, and preflight pinned Sugarkube app Helm charts."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from scripts import app_config

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")
TOKENPLACE_REQUIRED_ENV = [
    "TOKENPLACE_IMAGE_TAG",
    "TOKENPLACE_RELEASE_VERSION",
    "TOKENPLACE_CHART_VERSION",
    "TOKENPLACE_DEPLOY_ENV",
]


def clean_pin(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            return value
    return ""


def resolve_pin(config: dict[str, str]) -> tuple[str, Path]:
    if config.get("SUGARKUBE_VERSION"):
        return config["SUGARKUBE_VERSION"], Path("<config:SUGARKUBE_VERSION>")
    rel = config.get("SUGARKUBE_VERSION_FILE", "")
    if not rel:
        raise SystemExit(
            "ERROR: app config does not define SUGARKUBE_VERSION_FILE or "
            "SUGARKUBE_VERSION."
        )
    path = Path(rel)
    abs_path = path if path.is_absolute() else REPO_ROOT / path
    version = clean_pin(abs_path) if abs_path.is_file() else ""
    if not version:
        raise SystemExit(f"ERROR: unable to resolve chart version from {rel}.")
    return version, path


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def helm_show(chart: str, version: str) -> subprocess.CompletedProcess[str]:
    return run(["helm", "show", "chart", chart, "--version", version])


def parse_field(raw: str, name: str) -> str:
    for line in raw.splitlines():
        if line.lower().startswith(f"{name.lower()}:"):
            return line.split(":", 1)[1].strip()
    return ""


def semver_key(value: str) -> tuple[int, int, int, int, str] | None:
    match = SEMVER.match(value.strip())
    if not match:
        return None
    major, minor, patch, prerelease, _build = match.groups()
    return (int(major), int(minor), int(patch), 0 if prerelease else 1, prerelease or "")


def detect_latest(chart: str) -> tuple[str, str]:
    forced = os.environ.get("SUGARKUBE_APP_CHART_LATEST", "").strip()
    if forced:
        return forced, "SUGARKUBE_APP_CHART_LATEST"
    if not chart.startswith("oci://ghcr.io/"):
        return "", "latest unknown: only GHCR OCI best-effort detection is implemented"
    package = chart.removeprefix("oci://ghcr.io/")
    owner, _, name = package.partition("/")
    if not owner or not name:
        return "", "latest unknown: could not parse GHCR chart ref"
    api_name = name.replace("/", "%2F")
    gh = run([
        "gh", "api", f"/users/{owner}/packages/container/{api_name}/versions",
        "--jq", ".[].[.metadata.container.tags[]?] | .[]",
    ])
    if gh.returncode != 0:
        return (
            "",
            "latest unknown: run gh api "
            f"/users/{owner}/packages/container/{api_name}/versions "
            f"or open https://github.com/{owner}?tab=packages",
        )
    versions = [line.strip() for line in gh.stdout.splitlines() if semver_key(line.strip())]
    if not versions:
        return "", "latest unknown: no semver chart tags found in GHCR response"
    return sorted(versions, key=lambda item: semver_key(item) or (0, 0, 0, 0, ""))[-1], "GHCR"


def load(app: str, env: str = "staging", config_path: str = "") -> dict[str, str]:
    return app_config.load_config(
        app_config.normalize_named(app, "app"),
        app_config.normalize_named(env, "env"),
        app_config.normalize_named(config_path or "", "config") or None,
    )


def print_preflight(config: dict[str, str], tag: str, version: str, pin: Path) -> None:
    print(f"app: {config['SUGARKUBE_APP']}")
    print(f"env: {config['SUGARKUBE_ENV']}")
    print(f"image tag: {tag}")
    print(f"chart ref: {config['SUGARKUBE_CHART']}")
    print(f"chart version: {version}")
    print(f"chart pin: {pin}")


def cmd_status(args: argparse.Namespace) -> int:
    config = load(args.app, "staging", args.config)
    version, pin = resolve_pin(config)
    shown = helm_show(config["SUGARKUBE_CHART"], version)
    if shown.returncode != 0:
        sys.stderr.write(shown.stderr)
        return shown.returncode or 1
    print(f"app: {config['SUGARKUBE_APP']}")
    print(f"chart ref: {config['SUGARKUBE_CHART']}")
    print(f"pinned version: {version}")
    print(f"chart appVersion: {parse_field(shown.stdout, 'appVersion') or 'unknown'}")
    print(f"chart digest: {parse_field(shown.stdout, 'digest') or 'unknown'}")
    print(f"pin file: {pin}")
    latest, source = detect_latest(config["SUGARKUBE_CHART"])
    if not latest:
        print(source)
        return 0
    print(f"latest version: {latest} ({source})")
    if (
        semver_key(version)
        and semver_key(latest)
        and semver_key(version) < semver_key(latest)
    ):
        print(f"WARNING: Pinned chart appears stale: {version} < {latest}")
        print(f"Run: just app-chart-bump app={config['SUGARKUBE_APP']} version={latest}")
    return 0


def rewrite_pin(path: Path, version: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = False
    out = []
    for line in lines:
        if not changed and line.split("#", 1)[0].strip():
            suffix = ""
            if "#" in line:
                suffix = "  #" + line.split("#", 1)[1]
            out.append(f"{version}{suffix}")
            changed = True
        else:
            out.append(line)
    if not changed:
        out.append(version)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def cmd_bump(args: argparse.Namespace) -> int:
    version = app_config.normalize_named(args.version or "", "version")
    if not version:
        print("ERROR: version must not be empty. Use version=<chart-version>.", file=sys.stderr)
        return 2
    config = load(args.app, "staging", args.config)
    _old, pin = resolve_pin(config)
    if str(pin).startswith("<"):
        print("ERROR: app uses inline SUGARKUBE_VERSION; cannot bump a pin file.", file=sys.stderr)
        return 2
    shown = helm_show(config["SUGARKUBE_CHART"], version)
    if shown.returncode != 0:
        sys.stderr.write(shown.stderr)
        return shown.returncode or 1
    path = pin if pin.is_absolute() else REPO_ROOT / pin
    rewrite_pin(path, version)
    diff = run(["git", "diff", "--", str(pin)])
    print(diff.stdout, end="")
    print("Next steps:")
    print(f"git add {pin}")
    print(f"git commit -m \"Bump {config['SUGARKUBE_APP']} chart pin to {version}\"")
    print("git push")
    print(f"just app-deploy app={config['SUGARKUBE_APP']} env=staging tag=<APP_TAG>")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    config = load(args.app, args.env, args.config)
    version, pin = resolve_pin(config)
    print_preflight(config, args.tag, version, pin)
    shown = helm_show(config["SUGARKUBE_CHART"], version)
    if shown.returncode != 0:
        sys.stderr.write(shown.stderr)
        return shown.returncode or 1
    if (
        config["SUGARKUBE_APP"] != "tokenplace"
        or config["SUGARKUBE_ENV"] not in {"staging", "prod"}
    ):
        return 0
    cmd = [
        "helm",
        "template",
        config["SUGARKUBE_RELEASE"],
        config["SUGARKUBE_CHART"],
        "--namespace",
        config["SUGARKUBE_NAMESPACE"],
        "--version",
        version,
    ]
    for value in config["SUGARKUBE_VALUES"].split(","):
        if value.strip():
            cmd.extend(["-f", value.strip()])
    cmd.extend(["--set", f"image.tag={args.tag}"])
    templated = run(cmd)
    if templated.returncode != 0:
        sys.stderr.write(templated.stderr)
        return templated.returncode or 1
    missing = [name for name in TOKENPLACE_REQUIRED_ENV if name not in templated.stdout]
    if missing:
        print(
            "ERROR: token.place rendered manifest is missing required metadata env vars: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        print(f"Pinned chart version: {version} ({pin})", file=sys.stderr)
        print("Run: just app-chart-status app=tokenplace", file=sys.stderr)
        print(
            "Then bump intentionally, for example: "
            "just app-chart-bump app=tokenplace version=<published-version>",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--app", required=True)
    status.add_argument("--config", default="")
    bump = sub.add_parser("bump")
    bump.add_argument("--app", required=True)
    bump.add_argument("--version", required=True)
    bump.add_argument("--config", default="")
    pre = sub.add_parser("preflight")
    pre.add_argument("--app", required=True)
    pre.add_argument("--env", required=True)
    pre.add_argument("--tag", required=True)
    pre.add_argument("--config", default="")
    args = parser.parse_args(argv)
    funcs = {"status": cmd_status, "bump": cmd_bump, "preflight": cmd_preflight}
    return funcs[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
