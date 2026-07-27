#!/usr/bin/env python3
"""Manage Sugarkube app Helm chart pins and deploy guardrails."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_CONTAINER_NAMES = {"tokenplace": {"tokenplace", "relay"}}
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
    command = ["helm", "show", "chart", chart]
    if "@sha256:" not in chart:
        command += ["--version", version]
    return run(command)


@dataclass(frozen=True)
class ReleaseInputs:
    app: str
    env: str
    release: str
    namespace: str
    chart: str
    version: str
    values: tuple[str, ...]
    tag: str
    host: str = ""
    pull_policy: str = "Always"

    def helm_template_command(self) -> list[str]:
        command = ["helm", "template", self.release, self.chart, "--namespace", self.namespace]
        if "@sha256:" not in self.chart:
            command += ["--version", self.version]
        for value_file in self.values:
            command += ["-f", value_file]
        if self.host:
            command += ["--set", f"ingress.host={self.host}"]
        command += ["--set", f"image.tag={self.tag}"]
        if self.pull_policy:
            command += ["--set", f"image.pullPolicy={self.pull_policy}"]
        return command


def _scalar(value: str) -> str:
    return value.split(" #", 1)[0].strip().strip("\"'")


def _document_field(document: str, field: str) -> str:
    match = re.search(rf"(?m)^{re.escape(field)}:\s*(.*?)\s*$", document)
    return _scalar(match.group(1)) if match else ""


def _metadata(document: str) -> tuple[str, dict[str, str], dict[str, str]]:
    """Read the small metadata subset used by the release contract."""
    lines = document.splitlines()
    metadata_index = next((i for i, line in enumerate(lines) if line == "metadata:"), -1)
    if metadata_index < 0:
        return "", {}, {}
    name = ""
    maps: dict[str, dict[str, str]] = {"labels": {}, "annotations": {}}
    section = ""
    for line in lines[metadata_index + 1 :]:
        if line and not line.startswith(" "):
            break
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 2 and stripped.startswith("name:"):
            name = _scalar(stripped.split(":", 1)[1])
        elif indent == 2 and stripped.rstrip(":") in maps:
            section = stripped.rstrip(":")
        elif indent == 4 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            maps[section][_scalar(key)] = _scalar(value)
        elif indent <= 2 and stripped:
            section = ""
    return name, maps["labels"], maps["annotations"]


def _containers(document: str) -> list[tuple[str, str]]:
    """Return regular (never init) container names and images."""
    lines = document.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "containers:"), -1)
    if start < 0:
        return []
    base = len(lines[start]) - len(lines[start].lstrip())
    result: list[tuple[str, str]] = []
    current: dict[str, str] | None = None
    item_indent = -1
    for line in lines[start + 1 :]:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped and indent <= base:
            break
        if re.match(r"^-\s+", stripped) and (item_indent < 0 or indent == item_indent):
            if current:
                result.append((current.get("name", ""), current.get("image", "")))
            current = {}
            item_indent = indent
            stripped = stripped[1:].strip()
        if current is not None and indent <= item_indent + 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key in {"name", "image"}:
                current[key] = _scalar(value)
    if current:
        result.append((current.get("name", ""), current.get("image", "")))
    return result


def _nested_scalar(document: str, path: tuple[str, ...]) -> str:
    lines = document.splitlines()
    position = 0
    minimum_indent = -1
    for component in path:
        found = False
        for index in range(position, len(lines)):
            line = lines[index]
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if minimum_indent >= 0 and stripped and indent <= minimum_indent:
                break
            if re.match(rf"^{re.escape(component)}:\s*", stripped):
                value = stripped.split(":", 1)[1]
                if component == path[-1]:
                    return _scalar(value)
                position = index + 1
                minimum_indent = indent
                found = True
                break
        if not found and component != path[-1]:
            return ""
    return ""


def validate_rendered_manifest(manifest: str, inputs: ReleaseInputs) -> list[str]:
    documents = [doc for doc in re.split(r"(?m)^---\s*$", manifest) if doc.strip()]
    workloads: list[tuple[str, str]] = []
    kinds: set[str] = set()
    ingress_hosts: set[str] = set()
    service_monitors: list[str] = []
    candidates = {inputs.app, inputs.release, *APP_CONTAINER_NAMES.get(inputs.app, set())}
    expected_suffix = f":{inputs.tag}"
    errors: list[str] = []
    coherent_workload = False
    correct_image = False
    for document in documents:
        kind = _document_field(document, "kind")
        kinds.add(kind)
        name, labels, annotations = _metadata(document)
        namespace = _document_field(document, "  namespace")
        if namespace and namespace != inputs.namespace:
            errors.append(
                f"rendered {kind or 'resource'} {name or '<unnamed>'} has namespace {namespace!r}"
            )
        if kind in {"Deployment", "StatefulSet", "DaemonSet"}:
            workloads.append((kind, name))
            coherent = (
                labels.get("app.kubernetes.io/instance") == inputs.release
                or labels.get("release") == inputs.release
                or annotations.get("meta.helm.sh/release-name") == inputs.release
            )
            coherent_workload = coherent_workload or coherent
            if coherent:
                for container_name, image in _containers(document):
                    if container_name in candidates and image.endswith(expected_suffix):
                        correct_image = True
        if kind == "Ingress":
            ingress_hosts.update(re.findall(r"(?m)^\s+(?:-\s+)?host:\s*([^\s#]+)", document))
        if kind == "ServiceMonitor":
            service_monitors.append(document)
    if not workloads:
        errors.append("no rollout-capable application workload rendered")
    elif not coherent_workload:
        errors.append("no workload has a supported label or annotation for the requested release")
    if workloads and not correct_image:
        errors.append("intended application container does not use the exact requested image tag")
    if inputs.host and inputs.host not in ingress_hosts:
        errors.append(f"no Ingress rule exactly matches expected host {inputs.host!r}")
    if inputs.app == "dspace":
        for required in ("Deployment", "Service"):
            if required not in kinds:
                errors.append(f"DSPACE intended {required} did not render")
        if inputs.host and "Ingress" not in kinds:
            errors.append("DSPACE intended Ingress did not render")
        for monitor in service_monitors:
            secret_name = _nested_scalar(monitor, ("endpoints", "bearerTokenSecret", "name"))
            secret_key = _nested_scalar(monitor, ("endpoints", "bearerTokenSecret", "key"))
            # Lists make a fully generic YAML path reader disproportionate; match the chart's
            # actual endpoint schema while still requiring structured, nonempty fields.
            bearer = re.search(
                r"(?ms)^\s+bearerTokenSecret:\s*\n(?P<body>(?:\s{8,}.+\n?)*)", monitor
            )
            body = bearer.group("body") if bearer else ""
            secret_name = secret_name or _document_field(body, "        name")
            secret_key = secret_key or _document_field(body, "        key")
            if not secret_name or not secret_key:
                errors.append(
                    "DSPACE ServiceMonitor bearerTokenSecret name and key must be nonempty"
                )
        if inputs.env == "prod" and (
            service_monitors
            or "dspace-staging-metrics-token" in manifest
            or "sugarkube-int" in manifest
        ):
            errors.append("DSPACE production rendered staging-only metrics configuration")
    return errors


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


def is_prerelease(v: str) -> bool:
    m = SEMVER_RE.match(v)
    return bool(m and m.group(4))


def deployment_app_container_env_sets(
    manifest: str, app: str, release: str
) -> list[tuple[str, set[str]]]:
    """Return env var names for each candidate Deployment application container."""
    candidates = {app, release, *APP_CONTAINER_NAMES.get(app, set())}
    found: list[tuple[str, set[str]]] = []

    def scalar_value(value: str) -> str:
        return value.split("#", 1)[0].strip().strip("\"'")

    def parse_container_block(block: list[str]) -> tuple[str, set[str]]:
        container_name = ""
        envs: set[str] = set()
        in_env = False
        env_indent = -1
        item_indent = len(block[0]) - len(block[0].lstrip(" ")) if block else -1
        field_indent = item_indent + 2
        for line in block:
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))
            if in_env and indent <= env_indent and stripped:
                in_env = False
            if in_env and indent == field_indent and re.match(r"^[A-Za-z0-9_.-]+:\s*", stripped):
                in_env = False
            item_name_match = re.match(r"^\s*-\s*name:\s*(.+)$", line)
            field_name_match = re.match(r"^\s*name:\s*(.+)$", line)
            if not in_env and not container_name:
                if item_name_match and indent == item_indent:
                    container_name = scalar_value(item_name_match.group(1))
                    continue
                if field_name_match and indent == field_indent:
                    container_name = scalar_value(field_name_match.group(1))
                    continue
            if (stripped == "env:" and indent == field_indent) or (
                stripped == "- env:" and indent == item_indent
            ):
                in_env = True
                env_indent = indent
                continue
            if in_env:
                env_match = re.match(r"^\s*-\s*name:\s*(.+)$", line)
                if env_match and indent > env_indent:
                    envs.add(scalar_value(env_match.group(1)))
        return container_name, envs

    def flush_block(block: list[str]) -> None:
        container_name, envs = parse_container_block(block)
        if container_name in candidates:
            found.append((container_name, envs))

    for doc in re.split(r"(?m)^---\s*$", manifest):
        if not re.search(r"(?m)^kind:\s*Deployment\s*$", doc):
            continue
        in_containers = False
        containers_indent = -1
        container_item_indent = -1
        current_block: list[str] = []
        for line in doc.splitlines():
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))
            if not in_containers:
                if stripped == "containers:":
                    in_containers = True
                    containers_indent = indent
                continue
            if indent <= containers_indent and stripped:
                if current_block:
                    flush_block(current_block)
                break
            item_match = re.match(r"^\s*-\s+", line)
            if item_match and indent > containers_indent:
                if container_item_indent == -1:
                    container_item_indent = indent
                if indent == container_item_indent:
                    if current_block:
                        flush_block(current_block)
                    current_block = [line]
                    continue
            if current_block:
                current_block.append(line)
        else:
            if current_block:
                flush_block(current_block)
    return found


def deployment_app_container_envs(manifest: str, app: str, release: str) -> set[str]:
    """Return the union of env var names rendered on candidate app containers."""
    merged: set[str] = set()
    for _container_name, envs in deployment_app_container_env_sets(manifest, app, release):
        merged.update(envs)
    return merged


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
    unique_versions = sorted(set(versions), key=semver_key)
    stable_versions = [version for version in unique_versions if not is_prerelease(version)]
    production_safe_versions = stable_versions or unique_versions
    return (
        (production_safe_versions[-1], "GitHub/GHCR API")
        if production_safe_versions
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


def expected_ingress_host(values: tuple[str, ...], explicit: str) -> str:
    if explicit:
        return explicit
    host = ""
    enabled = ""
    for value_file in values:
        path = Path(value_file)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue  # Helm reports missing/unreadable values files with the authoritative error.
        resolved = _nested_scalar(text, ("ingress", "host"))
        if resolved:
            host = resolved
        resolved_enabled = _nested_scalar(text, ("ingress", "enabled"))
        if resolved_enabled:
            enabled = resolved_enabled.lower()
    return host if enabled != "false" else ""


def resolved_values_scalar(values: tuple[str, ...], path_parts: tuple[str, ...]) -> str:
    resolved = ""
    for value_file in values:
        path = Path(value_file)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            candidate = _nested_scalar(path.read_text(encoding="utf-8"), path_parts)
        except OSError:
            continue
        if candidate:
            resolved = candidate
    return resolved


def validate_dspace_values(manifest: str, inputs: ReleaseInputs) -> list[str]:
    metrics_enabled = (
        resolved_values_scalar(inputs.values, ("metrics", "enabled")).lower() == "true"
    )
    monitor_enabled = (
        resolved_values_scalar(inputs.values, ("serviceMonitor", "enabled")).lower() == "true"
    )
    secret = resolved_values_scalar(inputs.values, ("metrics", "auth", "existingSecret"))
    secret_key = resolved_values_scalar(inputs.values, ("metrics", "auth", "secretKey"))
    rendered_monitor = bool(re.search(r"(?m)^kind:\s*ServiceMonitor\s*$", manifest))
    errors: list[str] = []
    if rendered_monitor and not metrics_enabled:
        errors.append("DSPACE ServiceMonitor rendered while metrics.enabled is not true")
    if rendered_monitor and (not secret or not secret_key):
        errors.append(
            "DSPACE ServiceMonitor rendered without complete configured metrics authentication"
        )
    if monitor_enabled and metrics_enabled and secret and secret_key and not rendered_monitor:
        errors.append("DSPACE configured ServiceMonitor did not render")
    return errors


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
    values = tuple(filter(None, (value.strip() for value in args.values.split(","))))
    inputs = ReleaseInputs(
        app=args.app,
        env=args.env,
        release=args.release,
        namespace=args.namespace,
        chart=args.chart,
        version=version,
        values=values,
        tag=args.tag,
        host=expected_ingress_host(values, getattr(args, "host", "")),
        pull_policy=getattr(args, "pull_policy", "Always"),
    )
    tmpl = run(inputs.helm_template_command())
    if tmpl.returncode != 0:
        print(tmpl.stderr or tmpl.stdout, file=sys.stderr)
        return tmpl.returncode or 1
    errors = validate_rendered_manifest(tmpl.stdout, inputs)
    if inputs.app == "dspace":
        errors += validate_dspace_values(tmpl.stdout, inputs)
    if errors:
        context = (
            f"app={inputs.app} env={inputs.env} release={inputs.release} "
            f"namespace={inputs.namespace} chart={inputs.chart} version={inputs.version} "
            f"tag={inputs.tag}"
        )
        for error in errors:
            print(f"ERROR: render contract failed: {error}; {context}", file=sys.stderr)
        return 1
    req = REQUIRED_ENVS.get(args.app, [])
    if not req:
        return 0
    app_container_env_sets = deployment_app_container_env_sets(tmpl.stdout, args.app, args.release)
    complete_envs = next(
        (
            envs
            for _container_name, envs in app_container_env_sets
            if all(name in envs for name in req)
        ),
        None,
    )
    merged_envs: set[str] = set()
    for _container_name, envs in app_container_env_sets:
        merged_envs.update(envs)
    missing = [name for name in req if name not in (complete_envs or merged_envs)]
    if complete_envs is None:
        print(
            "ERROR: rendered token.place manifest is missing required metadata env vars: "
            + ", ".join(missing or req),
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
            s.add_argument("--host", default="")
            s.add_argument("--pull-policy", default="Always")
    a = p.parse_args()
    return {"status": cmd_status, "bump": cmd_bump, "preflight": cmd_preflight}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
