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
    try:
        return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    except OSError as error:
        return subprocess.CompletedProcess(args, 127, "", f"failed to launch {args[0]}: {error}")


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


def safe_yaml_documents(text: str) -> list[object]:
    """Parse JSON-compatible YAML via Psych's AST, rejecting tags and aliases."""
    ruby = r'''
require "psych"
require "json"
scanner = Psych::ScalarScanner.new(Psych::ClassLoader::Restricted.new([], []))
def convert(node, scanner)
  case node
  when Psych::Nodes::Stream then node.children.map { |child| convert(child, scanner) }
  when Psych::Nodes::Document then convert(node.root, scanner)
  when Psych::Nodes::Mapping
    Hash[*node.children.map { |child| convert(child, scanner) }]
  when Psych::Nodes::Sequence then node.children.map { |child| convert(child, scanner) }
  when Psych::Nodes::Scalar
    raise "unsafe YAML tag #{node.tag}" if node.tag && !node.tag.start_with?("tag:yaml.org,2002:")
    node.quoted ? node.value : scanner.tokenize(node.value)
  when Psych::Nodes::Alias then raise "YAML aliases are not allowed"
  else raise "unsupported YAML node #{node.class}"
  end
end
puts JSON.generate(convert(Psych.parse_stream(STDIN.read), scanner))
'''
    try:
        parsed = subprocess.run(
            ["ruby", "-e", ruby], input=text, capture_output=True, text=True, check=False
        )
    except OSError as error:
        raise ValueError(f"YAML parser launch failed: {error}") from error
    if parsed.returncode != 0:
        raise ValueError((parsed.stderr or "invalid YAML").strip())
    value = json.loads(parsed.stdout)
    return value if isinstance(value, list) else []


def nested_value(document: object, path: tuple[str, ...]) -> tuple[bool, object]:
    current = document
    for component in path:
        if not isinstance(current, dict) or component not in current:
            return False, None
        current = current[component]
    return True, current


def scalar(value: object) -> str:
    return "" if value is None else str(value)


def merged_values_document(values: tuple[str, ...]) -> object:
    """Resolve Helm values files in order using recursive mapping merges."""

    def merge(earlier: object, later: object) -> object:
        if not isinstance(earlier, dict) or not isinstance(later, dict):
            return later
        result = dict(earlier)
        for key, value in later.items():
            result[key] = merge(result[key], value) if key in result else value
        return result

    resolved: object = {}
    for value_file in values:
        path = Path(value_file)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            documents = safe_yaml_documents(path.read_text(encoding="utf-8"))
        except OSError:
            continue  # Helm reports missing/unreadable values files with the authoritative error.
        resolved = merge(resolved, documents[0] if documents else {})
    return resolved


def release_associated(
    document: dict[str, object], release: str, *, allow_name: bool = True
) -> bool:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
    return (
        scalar(labels.get("app.kubernetes.io/instance")) == release
        or scalar(labels.get("release")) == release
        or scalar(annotations.get("meta.helm.sh/release-name")) == release
        or (allow_name and scalar(metadata.get("name")) == release)
    )


def contains_exact_scalar(value: object, expected: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            contains_exact_scalar(key, expected) or contains_exact_scalar(item, expected)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_exact_scalar(item, expected) for item in value)
    return isinstance(value, str) and value in expected


def count_exact_scalar(value: object, expected: str) -> int:
    if isinstance(value, dict):
        return sum(
            count_exact_scalar(key, expected) + count_exact_scalar(item, expected)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(count_exact_scalar(item, expected) for item in value)
    return int(isinstance(value, str) and value == expected)


def safe_dspace_metrics_token_count(
    document: dict[str, object], inputs: ReleaseInputs, metrics_enabled: bool
) -> int:
    """Count METRICS_TOKEN entries permitted by the legacy DSPACE chart."""
    if metrics_enabled or scalar(document.get("kind")) not in {
        "Deployment",
        "StatefulSet",
        "DaemonSet",
    }:
        return 0
    if not release_associated(document, inputs.release, allow_name=False):
        return 0
    found, containers = nested_value(document, ("spec", "template", "spec", "containers"))
    if not found or not isinstance(containers, list):
        return 0
    candidates = {inputs.app, inputs.release, *APP_CONTAINER_NAMES.get(inputs.app, set())}
    safe = 0
    for container in containers:
        if not isinstance(container, dict) or scalar(container.get("name")) not in candidates:
            continue
        env = container.get("env")
        for entry in env if isinstance(env, list) else []:
            # Chart 3.0.2 uses the pod UID as an unpredictable pod-local token to
            # keep legacy /metrics inaccessible when metrics are disabled.
            if isinstance(entry, dict) and entry == {
                "name": "METRICS_TOKEN",
                "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}},
            }:
                safe += 1
    return safe


def validate_rendered_manifest(manifest: str, inputs: ReleaseInputs) -> list[str]:
    try:
        documents = safe_yaml_documents(manifest)
    except (ValueError, json.JSONDecodeError) as error:
        return [f"rendered output is not safe structural YAML: {error}"]
    workloads: list[tuple[str, str]] = []
    kinds: set[str] = set()
    ingress_hosts: set[str] = set()
    service_monitors: list[dict[str, object]] = []
    candidates = {inputs.app, inputs.release, *APP_CONTAINER_NAMES.get(inputs.app, set())}
    expected_suffix = f":{inputs.tag}"
    errors: list[str] = []
    coherent_workload = False
    intended_container_found = False
    for document in documents:
        if not isinstance(document, dict):
            continue
        kind = scalar(document.get("kind"))
        metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        name = scalar(metadata.get("name"))
        namespace = scalar(metadata.get("namespace"))
        labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
        annotations = (
            metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
        )
        associated = release_associated(
            document,
            inputs.release,
            allow_name=(
                inputs.app != "dspace"
                and kind not in {"Deployment", "StatefulSet", "DaemonSet"}
            ),
        )
        if inputs.app == "dspace" and kind == "Secret":
            errors.append(
                f"DSPACE rendered Secret {name or '<unnamed>'}; literal Secret resources are forbidden"
            )
        if namespace and namespace != inputs.namespace:
            errors.append(
                f"rendered {kind or 'resource'} {name or '<unnamed>'} has namespace {namespace!r}"
            )
        if kind in {"Deployment", "StatefulSet", "DaemonSet"}:
            workloads.append((kind, name))
            coherent = associated
            coherent_workload = coherent_workload or coherent
            if coherent:
                found, containers = nested_value(
                    document, ("spec", "template", "spec", "containers")
                )
                intended = [
                    item
                    for item in containers if isinstance(item, dict) and scalar(item.get("name")) in candidates
                ] if found and isinstance(containers, list) else []
                intended_container_found = intended_container_found or bool(intended)
                for item in intended:
                    if not scalar(item.get("image")).endswith(expected_suffix):
                        errors.append(
                            f"rendered {kind} {name or '<unnamed>'} container "
                            f"{scalar(item.get('name')) or '<unnamed>'} does not use the exact "
                            "requested image tag"
                        )
        if kind == "Ingress" and associated:
            found, rules = nested_value(document, ("spec", "rules"))
            if found and isinstance(rules, list):
                ingress_hosts.update(
                    scalar(rule.get("host")) for rule in rules if isinstance(rule, dict)
                )
        if kind == "ServiceMonitor" and associated:
            service_monitors.append(document)
    if not workloads:
        errors.append("no rollout-capable application workload rendered")
    elif not coherent_workload:
        errors.append("no workload has a supported label or annotation for the requested release")
    if workloads and not intended_container_found:
        errors.append("intended application container does not use the exact requested image tag")
    if inputs.host and inputs.host not in ingress_hosts:
        errors.append(f"no Ingress rule exactly matches expected host {inputs.host!r}")
    if inputs.app == "dspace":
        for required in ("Deployment", "Service"):
            if not any(
                isinstance(doc, dict)
                and scalar(doc.get("kind")) == required
                and release_associated(doc, inputs.release, allow_name=False)
                for doc in documents
            ):
                errors.append(f"DSPACE intended {required} did not render")
        if inputs.host and not ingress_hosts:
            errors.append("DSPACE intended Ingress did not render")
        for monitor in service_monitors:
            spec = monitor.get("spec") if isinstance(monitor.get("spec"), dict) else {}
            endpoints = spec.get("endpoints")
            authenticated = bool(endpoints) and isinstance(endpoints, list)
            if authenticated:
                authenticated = all(
                    isinstance(endpoint, dict)
                    and isinstance(endpoint.get("bearerTokenSecret"), dict)
                    and scalar(endpoint["bearerTokenSecret"].get("name"))
                    and scalar(endpoint["bearerTokenSecret"].get("key"))
                    for endpoint in endpoints
                )
            if not authenticated:
                errors.append(
                    "DSPACE ServiceMonitor bearerTokenSecret name and key must be nonempty"
                )
        production_leaks = {"dspace-staging-metrics-token", "sugarkube-int"}
        metrics_enabled = (
            resolved_values_scalar(inputs.values, ("metrics", "enabled")).lower() == "true"
        )
        associated_documents = [
            doc
            for doc in documents
            if isinstance(doc, dict)
            and release_associated(doc, inputs.release, allow_name=False)
        ]
        unsafe_metrics_token = any(
            count_exact_scalar(doc, "METRICS_TOKEN")
            != safe_dspace_metrics_token_count(doc, inputs, metrics_enabled)
            for doc in associated_documents
        )
        if inputs.env == "prod" and (
            service_monitors
            or unsafe_metrics_token
            or any(contains_exact_scalar(doc, production_leaks) for doc in associated_documents)
        ):
            errors.append("DSPACE production rendered staging-only metrics configuration")
    return errors


def parse_chart_yaml(text: str) -> dict[str, str]:
    documents = safe_yaml_documents(text)
    document = documents[0] if documents else {}
    return {str(key): scalar(value) for key, value in document.items()} if isinstance(document, dict) else {}


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
    for document in safe_yaml_documents(manifest):
        if (
            not isinstance(document, dict)
            or scalar(document.get("kind")) != "Deployment"
            or not release_associated(document, release, allow_name=False)
        ):
            continue
        has_containers, containers = nested_value(
            document, ("spec", "template", "spec", "containers")
        )
        if not has_containers or not isinstance(containers, list):
            continue
        for container in containers:
            if not isinstance(container, dict):
                continue
            container_name = scalar(container.get("name"))
            if container_name not in candidates:
                continue
            envs = container.get("env")
            found.append(
                (
                    container_name,
                    {
                        scalar(item.get("name"))
                        for item in envs
                        if isinstance(item, dict) and scalar(item.get("name"))
                    }
                    if isinstance(envs, list)
                    else set(),
                )
            )
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
    document = merged_values_document(values)
    _, resolved_host = nested_value(document, ("ingress", "host"))
    _, resolved_enabled = nested_value(document, ("ingress", "enabled"))
    host = scalar(resolved_host)
    enabled = scalar(resolved_enabled).lower()
    if enabled == "true" and not host:
        raise SystemExit("ERROR: ingress.enabled is true but no nonempty ingress.host was resolved.")
    return host if enabled != "false" else ""


def resolved_values_scalar(values: tuple[str, ...], path_parts: tuple[str, ...]) -> str:
    _, resolved = nested_value(merged_values_document(values), path_parts)
    return scalar(resolved)


def validate_dspace_values(manifest: str, inputs: ReleaseInputs) -> list[str]:
    metrics_enabled = (
        resolved_values_scalar(inputs.values, ("metrics", "enabled")).lower() == "true"
    )
    monitor_enabled = (
        resolved_values_scalar(inputs.values, ("serviceMonitor", "enabled")).lower() == "true"
    )
    secret = resolved_values_scalar(inputs.values, ("metrics", "auth", "existingSecret"))
    secret_key = resolved_values_scalar(inputs.values, ("metrics", "auth", "secretKey")) or "token"
    rendered_monitor = any(
        isinstance(document, dict)
        and scalar(document.get("kind")) == "ServiceMonitor"
        and release_associated(document, inputs.release, allow_name=False)
        for document in safe_yaml_documents(manifest)
    )
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


def preflight_context(args: argparse.Namespace, version: str, host: str) -> str:
    """Format non-secret release identity for terminal preflight diagnostics."""
    return (
        f"app={args.app} env={args.env} release={args.release} "
        f"namespace={args.namespace} chart={args.chart} version={version} "
        f"tag={args.tag} host={host}"
    )


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
    values = tuple(filter(None, (value.strip() for value in args.values.split(","))))
    try:
        host = expected_ingress_host(values, getattr(args, "host", ""))
    except (ValueError, json.JSONDecodeError) as error:
        context = preflight_context(args, version, "<unresolved>")
        print(f"ERROR: values parsing failed; {context}: {error}", file=sys.stderr)
        return 1
    context = preflight_context(args, version, host or "<disabled>")
    print_summary(args.app, args.env, args.tag, args.chart, version, args.version_file)
    show = helm_show(args.chart, version)
    if show.returncode != 0:
        print(
            f"ERROR: helm show failed; {context}: {(show.stderr or show.stdout).strip()}",
            file=sys.stderr,
        )
        return show.returncode or 1
    try:
        chart_metadata = parse_chart_yaml(show.stdout)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: chart metadata parsing failed; {context}: {error}", file=sys.stderr)
        return 1
    if "@sha256:" in args.chart and chart_metadata.get("version") != version:
        print(
            "ERROR: digest-qualified chart metadata version "
            f"{chart_metadata.get('version', '<missing>')!r} does not match approved version "
            f"{version!r}; {context}.",
            file=sys.stderr,
        )
        return 1
    inputs = ReleaseInputs(
        app=args.app,
        env=args.env,
        release=args.release,
        namespace=args.namespace,
        chart=args.chart,
        version=version,
        values=values,
        tag=args.tag,
        host=host,
        pull_policy=getattr(args, "pull_policy", "Always"),
    )
    tmpl = run(inputs.helm_template_command())
    if tmpl.returncode != 0:
        print(
            f"ERROR: helm template failed; {context}: {(tmpl.stderr or tmpl.stdout).strip()}",
            file=sys.stderr,
        )
        return tmpl.returncode or 1
    try:
        errors = validate_rendered_manifest(tmpl.stdout, inputs)
        if inputs.app == "dspace":
            errors += validate_dspace_values(tmpl.stdout, inputs)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: rendered-YAML parsing failed; {context}: {error}", file=sys.stderr)
        return 1
    if errors:
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
            + ", ".join(missing or req)
            + f"; {context}",
            file=sys.stderr,
        )
        print(f"Pinned chart version: {version} ({args.version_file})", file=sys.stderr)
        print(f"Run: just app-chart-status app={args.app}", file=sys.stderr)
        print(
            f"Run: just app-chart-bump app={args.app} version=<published-version>", file=sys.stderr
        )
        return 1
    return 0


def cmd_resolve_host(args: argparse.Namespace) -> int:
    """Print the effective ingress host used as an explicit Helm override."""
    values = tuple(filter(None, (value.strip() for value in args.values.split(","))))
    try:
        host = expected_ingress_host(values, args.host)
    except (ValueError, json.JSONDecodeError, SystemExit) as error:
        print(f"ERROR: values parsing failed while resolving ingress host: {error}", file=sys.stderr)
        return 1
    print(host)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "bump", "preflight", "resolve-host"):
        s = sub.add_parser(name)
        if name == "resolve-host":
            s.add_argument("--values", required=True)
            s.add_argument("--host", default="")
            continue
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
    return {
        "status": cmd_status,
        "bump": cmd_bump,
        "preflight": cmd_preflight,
        "resolve-host": cmd_resolve_host,
    }[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
