#!/usr/bin/env python3
"""Manage Sugarkube app Helm chart pins and deploy guardrails."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENVS = {
    "tokenplace": [
        "TOKENPLACE_IMAGE_TAG",
        "TOKENPLACE_RELEASE_VERSION",
        "TOKENPLACE_CHART_VERSION",
        "TOKENPLACE_DEPLOY_ENV",
    ]
}
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([^+]+))?(?:\+.*)?$")


def version_file_path(path: str) -> Path:
    if not path or not path.strip():
        raise SystemExit("ERROR: --version-file must not be empty.")
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def read_pin(path: str) -> str:
    p = version_file_path(path)
    for line in p.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            return value
    raise SystemExit(f"ERROR: chart pin file {path} does not contain a version.")


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def helm_show(chart: str, version: str) -> subprocess.CompletedProcess[str]:
    return run(["helm", "show", "chart", chart, "--version", version])


def parse_chart_yaml(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip("\"'")
    return out


def semver_key(v: str) -> tuple[int, int, int, int, tuple[object, ...]]:
    """Return a SemVer precedence key where prereleases sort below final releases."""
    m = SEMVER_RE.match(v)
    if not m:
        return (-1, -1, -1, 0, (v,))
    prerelease = m.group(4)
    if not prerelease:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 1, ())
    parts: list[object] = []
    for part in prerelease.split("."):
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, tuple(parts))


def ghcr_versions_from_api(owner: str, name: str, owner_type: str) -> tuple[list[str], str]:
    url = (
        f"https://api.github.com/{owner_type}/{owner}/packages/container/"
        f"charts%2F{name}/versions?per_page=100"
    )
    curl = run(["curl", "-fsS", url])
    if curl.returncode != 0:
        return [], curl.stderr or curl.stdout
    try:
        payload = json.loads(curl.stdout)
    except json.JSONDecodeError:
        return [], "could not parse GitHub/GHCR API response"
    versions: list[str] = []
    for item in payload if isinstance(payload, list) else []:
        meta = item.get("metadata", {}) if isinstance(item, dict) else {}
        tags = meta.get("container", {}).get("tags", []) if isinstance(meta, dict) else []
        versions.extend(t for t in tags if SEMVER_RE.match(str(t)))
    return versions, ""


def latest_version(chart: str) -> tuple[str, str]:
    forced = os.environ.get("SUGARKUBE_APP_CHART_LATEST_STUB", "").strip()
    if forced:
        return forced, "SUGARKUBE_APP_CHART_LATEST_STUB"
    # Best-effort GHCR OCI discovery via GitHub API for oci://ghcr.io/owner/charts/name.
    m = re.match(r"^oci://ghcr\.io/([^/]+)/charts/([^/]+)$", chart)
    if not m:
        return "", "latest unknown: unsupported chart registry; inspect the chart registry manually"
    owner, name = m.groups()
    versions: list[str] = []
    for owner_type in ("orgs", "users"):
        found, error = ghcr_versions_from_api(owner, name, owner_type)
        versions.extend(found)
        if found:
            break
    versions = sorted(set(versions), key=semver_key)
    return (
        (versions[-1], "GitHub/GHCR API")
        if versions
        else (
            "",
            f"latest unknown: no semver tags found; run: helm show chart {chart} --version <version>",
        )
    )


def print_summary(app: str, env: str, tag: str, chart: str, version: str, pin: str) -> None:
    print(f"app: {app}")
    print(f"env: {env}")
    print(f"image tag: {tag}")
    print(f"chart ref: {chart}")
    print(f"chart version: {version}")
    print(f"chart pin: {pin}")


def cmd_status(args: argparse.Namespace) -> int:
    version = read_pin(args.version_file)
    show = helm_show(args.chart, version)
    if show.returncode != 0:
        print(show.stderr or show.stdout, file=sys.stderr)
        return show.returncode or 1
    meta = parse_chart_yaml(show.stdout)
    print(f"app: {args.app}")
    print(f"chart ref: {args.chart}")
    print(f"pinned version: {version}")
    print(f"chart appVersion: {meta.get('appVersion', 'unknown')}")
    print(f"chart digest: {meta.get('digest', 'unknown')}")
    print(f"pin file: {args.version_file}")
    latest, source = latest_version(args.chart)
    if latest:
        print(f"latest version: {latest} ({source})")
        if semver_key(version) < semver_key(latest):
            print(f"WARNING: Pinned chart appears stale: {version} < {latest}")
            print(f"Run: just app-chart-bump app={args.app} version={latest}")
    else:
        print(source)
    return 0


def cmd_bump(args: argparse.Namespace) -> int:
    if not args.version.strip():
        print("ERROR: version must not be empty.", file=sys.stderr)
        return 2
    show = helm_show(args.chart, args.version)
    if show.returncode != 0:
        print(show.stderr or show.stdout, file=sys.stderr)
        return show.returncode or 1
    path = version_file_path(args.version_file)
    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    new = []
    for line in lines:
        if not replaced and line.split("#", 1)[0].strip():
            suffix = ""
            if "#" in line:
                suffix = "  #" + line.split("#", 1)[1]
            new.append(args.version + suffix)
            replaced = True
        else:
            new.append(line)
    if not replaced:
        new.append(args.version)
    path.write_text("\n".join(new) + "\n", encoding="utf-8")
    subprocess.run(["git", "diff", "--", str(path)], cwd=REPO_ROOT, check=False)
    print("Next steps:")
    print(f"git add {args.version_file}")
    print(f'git commit -m "Bump {args.app} chart pin to {args.version}"')
    print("git push")
    print(f"just app-deploy app={args.app} env=staging tag=<APP_TAG>")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    version = args.version or read_pin(args.version_file)
    print_summary(args.app, args.env, args.tag, args.chart, version, args.version_file)
    show = helm_show(args.chart, version)
    if show.returncode != 0:
        print(show.stderr or show.stdout, file=sys.stderr)
        return show.returncode or 1
    req = REQUIRED_ENVS.get(args.app, [])
    if not req:
        return 0
    cmd = [
        "helm",
        "template",
        args.release,
        args.chart,
        "--namespace",
        args.namespace,
        "--version",
        version,
    ]
    for vf in filter(None, (v.strip() for v in args.values.split(","))):
        cmd += ["-f", vf]
    if args.tag:
        cmd += ["--set", f"image.tag={args.tag}", "--set", "image.pullPolicy=Always"]
    tmpl = run(cmd)
    if tmpl.returncode != 0:
        print(tmpl.stderr or tmpl.stdout, file=sys.stderr)
        return tmpl.returncode or 1
    missing = [
        name
        for name in req
        if not re.search(rf"(?m)^\s*-\s*name:\s*{re.escape(name)}\s*$", tmpl.stdout)
    ]
    if missing:
        print(
            "ERROR: rendered token.place manifest is missing required metadata env vars: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        print(f"Pinned chart version: {version} ({args.version_file})", file=sys.stderr)
        print(f"Run: just app-chart-status app={args.app}", file=sys.stderr)
        print(
            f"Run: just app-chart-bump app={args.app} version=<published-version>", file=sys.stderr
        )
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "bump", "preflight"):
        s = sub.add_parser(name)
        s.add_argument("--app", required=True)
        s.add_argument("--chart", required=True)
        s.add_argument("--version-file", required=True)
        if name == "bump":
            s.add_argument("--version", required=True)
        if name == "preflight":
            s.add_argument("--env", required=True)
            s.add_argument("--tag", required=True)
            s.add_argument("--values", required=True)
            s.add_argument("--release", required=True)
            s.add_argument("--namespace", required=True)
            s.add_argument("--version", default="")
    a = p.parse_args()
    return {"status": cmd_status, "bump": cmd_bump, "preflight": cmd_preflight}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
