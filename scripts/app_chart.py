#!/usr/bin/env python3
"""Inspect and bump pinned Sugarkube app Helm chart versions."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from scripts.app_config import AppConfigError, load_config, normalize_env, normalize_named

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
REQUIRED = {
    "tokenplace": [
        "TOKENPLACE_IMAGE_TAG",
        "TOKENPLACE_RELEASE_VERSION",
        "TOKENPLACE_CHART_VERSION",
        "TOKENPLACE_DEPLOY_ENV",
    ]
}


def root():
    return Path(os.environ.get("SUGARKUBE_REPO_ROOT", Path(__file__).resolve().parents[1]))


def pin_version(path: Path):
    for line in path.read_text().splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            return s
    raise SystemExit(f"ERROR: chart pin file {path} has no version")


def cfg(app, env="staging"):
    return load_config(app, env, None)


def pin_path(c):
    p = Path(c.get("SUGARKUBE_VERSION_FILE", ""))
    return p if p.is_absolute() else root() / p


def rel(p):
    try:
        return str(p.relative_to(root()))
    except ValueError:
        return str(p)


def helm_show(chart, version):
    r = subprocess.run(
        ["helm", "show", "chart", chart, "--version", version],
        text=True,
        capture_output=True,
        check=False,
    )
    if r.returncode:
        raise RuntimeError(r.stderr or r.stdout)
    return r.stdout


def parse_show(out):
    data = {}
    for line in out.splitlines():
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def latest(chart):
    env = os.environ.get("SUGARKUBE_APP_CHART_LATEST")
    if env:
        return env
    if not chart.startswith("oci://ghcr.io/"):
        return ""
    pkg = chart.removeprefix("oci://ghcr.io/")
    if "/charts/" in pkg:
        owner, name = pkg.split("/charts/", 1)
        package = f"charts%2F{name}"
    else:
        return ""
    url = f"https://api.github.com/users/{owner}/packages/container/{package}/versions?per_page=100"
    r = subprocess.run(["curl", "-fsS", url], text=True, capture_output=True, check=False)
    if r.returncode:
        return ""
    import json

    try:
        arr = json.loads(r.stdout)
    except Exception:
        return ""
    versions = []
    for item in arr:
        for tag in item.get("metadata", {}).get("container", {}).get("tags", []) or []:
            if SEMVER.match(tag):
                versions.append(tag.lstrip("v"))
    return (
        max(versions, key=lambda v: tuple(map(int, SEMVER.match(v).groups()))) if versions else ""
    )


def status(args):
    args.app = normalize_named(args.app, "app")
    c = cfg(args.app)
    chart = c["SUGARKUBE_CHART"]
    pp = pin_path(c)
    ver = pin_version(pp)
    out = helm_show(chart, ver)
    data = parse_show(out)
    lat = latest(chart)
    print(
        f"app: {args.app}\nchart ref: {chart}\npinned version: {ver}\nchart appVersion: {data.get('appVersion','unknown')}\nchart digest: {data.get('digest','unknown')}\npin file: {rel(pp)}"
    )
    if lat:
        print(f"latest version: {lat}")
        if tuple(map(int, SEMVER.match(ver).groups())) < tuple(
            map(int, SEMVER.match(lat).groups())
        ):
            print(f"WARNING: Pinned chart appears stale: {ver} < {lat}")
            print(f"Run: just app-chart-bump app={args.app} version={lat}")
    else:
        print("latest unknown: unable to query published chart versions automatically.")
        print(f"Manual: helm show chart {chart} --version <version>")


def bump(args):
    args.app = normalize_named(args.app, "app")
    version = normalize_named(args.version or "", "version")
    if not version:
        raise SystemExit("ERROR: version must not be empty")
    c = cfg(args.app)
    chart = c["SUGARKUBE_CHART"]
    pp = pin_path(c)
    helm_show(chart, version)
    lines = pp.read_text().splitlines()
    done = False
    new = []
    for line in lines:
        if not done and line.split("#", 1)[0].strip():
            suffix = (" #" + line.split("#", 1)[1]) if "#" in line else ""
            new.append(version + suffix)
            done = True
        else:
            new.append(line)
    if not done:
        new.append(version)
    pp.write_text("\n".join(new) + "\n")
    subprocess.run(["git", "diff", "--", rel(pp)], cwd=root(), check=False)
    print("\nNext steps:")
    print(f"git add {rel(pp)}")
    print(f'git commit -m "Bump {args.app} chart pin to {version}"')
    print("git push")
    print(f"just app-deploy app={args.app} env=staging tag=<APP_TAG>")


def preflight(args):
    args.app = normalize_named(args.app, "app")
    args.env = normalize_env(args.env)
    args.tag = normalize_named(args.tag, "tag")
    c = cfg(args.app, args.env)
    chart = c["SUGARKUBE_CHART"]
    pp = pin_path(c)
    ver = pin_version(pp)
    tag = args.tag
    print(
        f"app: {args.app}\nenv: {args.env}\nimage tag: {tag}\nchart ref: {chart}\nchart version: {ver}\nchart pin: {rel(pp)}"
    )
    helm_show(chart, ver)
    req = REQUIRED.get(args.app, [])
    if req and args.env in {"staging", "prod"}:
        cmd = [
            "helm",
            "template",
            c["SUGARKUBE_RELEASE"],
            chart,
            "--namespace",
            c["SUGARKUBE_NAMESPACE"],
            "--version",
            ver,
            "--set",
            f"image.tag={tag}",
        ]
        for vf in c["SUGARKUBE_VALUES"].split(","):
            cmd += ["-f", vf.strip()]
        r = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if r.returncode:
            raise RuntimeError(r.stderr or r.stdout)
        missing = [x for x in req if x not in r.stdout]
        if missing:
            raise SystemExit(
                "ERROR: rendered token.place manifest is missing required env vars: "
                + ", ".join(missing)
                + f"\nPinned chart version: {ver}\nRun: just app-chart-status app={args.app}\nRun: just app-chart-bump app={args.app} version=<published-version>"
            )


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for n in ("status", "bump", "preflight"):
        s = sub.add_parser(n)
        s.add_argument("--app", required=True)
    sub.choices["bump"].add_argument("--version", required=True)
    sub.choices["preflight"].add_argument("--env", required=True)
    sub.choices["preflight"].add_argument("--tag", required=True)
    a = p.parse_args(argv)
    try:
        globals()[a.cmd](a)
        return 0
    except (AppConfigError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
