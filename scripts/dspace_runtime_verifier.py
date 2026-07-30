#!/usr/bin/env python3
"""Prove DSPACE identity and chat behavior without mutating the cluster.

The JSON written by this program is intentionally small.  In particular, HTTP
and child-process content is never copied into diagnostics or evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import app_config  # noqa: E402
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

CAPABILITIES = (
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
)
RESULT_FIELDS = (
    "schemaVersion",
    "environment",
    "release",
    "namespace",
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "journeys",
)
REVISION_META_RE = re.compile(
    r'<meta\s+[^>]*name=["\']dspace-build-revision["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
REVISION_META_RE_REVERSED = re.compile(
    r'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']dspace-build-revision["\'][^>]*>',
    re.IGNORECASE,
)


class VerificationError(ValueError):
    """A safe, classified runtime verification failure."""


Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise VerificationError(f"provider/chat smoke: command failed: {command[0]}")
    return completed.stdout


def _json_command(runner: Runner, command: list[str], category: str) -> dict[str, Any]:
    try:
        value = json.loads(_command(runner, command, category))
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{category}: command did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{category}: command returned an invalid object")
    return value


def _command(runner: Runner, command: list[str], category: str) -> str:
    try:
        return runner(command)
    except Exception as exc:
        raise VerificationError(f"{category}: command failed") from exc


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if urllib.parse.urlsplit(newurl)[:2] != urllib.parse.urlsplit(req.full_url)[:2]:
            raise VerificationError("public identity: redirect changed origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, category: str) -> bytes:
    try:
        with urllib.request.build_opener(SameOriginRedirect()).open(url, timeout=15) as response:
            return response.read(1024 * 1024 + 1)
    except VerificationError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError(f"{category}: endpoint is unreachable") from exc


def _identity(body: bytes, expected_version: str, expected_revision: str, category: str) -> None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{category}: invalid build identity") from exc
    expected = {
        "version": expected_version,
        "revision": expected_revision,
        "shortRevision": expected_revision[:7],
    }
    if not isinstance(value, dict) or any(
        value.get(key) != wanted for key, wanted in expected.items()
    ):
        raise VerificationError(f"{category}: version or revision mismatch")
    image = value.get("image")
    if image is not None and not isinstance(image, str):
        raise VerificationError(f"{category}: invalid runtime image coordinate")


def _frontend(body: bytes, expected_revision: str, category: str) -> None:
    try:
        html = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationError(f"{category}: invalid frontend marker") from exc
    match = REVISION_META_RE.search(html) or REVISION_META_RE_REVERSED.search(html)
    if not match or match.group(1) != expected_revision:
        raise VerificationError(f"{category}: frontend revision mismatch")


def _values_expectations(paths: list[Path]) -> dict[str, str]:
    """Read the three non-secret scalar contracts from the ordered values chain."""
    result: dict[str, str] = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise VerificationError("manifest/evidence mismatch: cannot read values chain") from exc
        section = ""
        env_name: str | None = None
        for raw in lines:
            line = raw.split("#", 1)[0].rstrip()
            stripped = line.strip()
            if not stripped:
                continue
            if len(line) == len(line.lstrip()) and stripped.endswith(":"):
                section = stripped[:-1]
                env_name = None
                continue
            if section == "ingress" and re.fullmatch(r"host:\s*.+", stripped):
                result["host"] = stripped.split(":", 1)[1].strip().strip("\"'")
            if section == "env":
                name = re.fullmatch(r"-\s*name:\s*(\S+)", stripped)
                if name:
                    env_name = name.group(1).strip("\"'")
                value = re.fullmatch(r"value:\s*(.+)", stripped)
                if value and env_name in {
                    "DSPACE_TOKEN_PLACE_URL",
                    "DSPACE_TOKEN_PLACE_CHAT_MODEL",
                }:
                    result[env_name] = value.group(1).strip().strip("\"'")
    return result


def expectations(config: dict[str, str], provider: str) -> tuple[str, str | None, str | None]:
    paths = []
    for raw in config["SUGARKUBE_VALUES"].split(","):
        path = Path(raw.strip()).expanduser()
        paths.append(path if path.is_absolute() else REPO_ROOT / path)
    values = _values_expectations(paths)
    host = values.get("host")
    if not isinstance(host, str) or not host:
        raise VerificationError("manifest/evidence mismatch: rendered ingress host is missing")
    if provider == "openai":
        return host, None, None
    origin = values.get("DSPACE_TOKEN_PLACE_URL")
    model = values.get("DSPACE_TOKEN_PLACE_CHAT_MODEL")
    if not all(isinstance(value, str) and value for value in (origin, model)):
        raise VerificationError("manifest/evidence mismatch: token.place expectations are missing")
    return host, origin, model


def _pods(runner: Runner, kubeconfig: str, namespace: str, release: str) -> list[dict[str, Any]]:
    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={release}"
    value = _json_command(
        runner,
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            selector,
            "-o",
            "json",
        ],
        "pod/replica identity",
    )
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise VerificationError("pod/replica identity: no serving replicas")
    return items


def verify(args: argparse.Namespace, runner: Runner = run) -> dict[str, Any]:
    manifest = release_manifest.validate(release_manifest._object(args.manifest), None)
    if manifest["environment"] != args.environment:
        raise VerificationError("manifest/evidence mismatch: environment differs")
    expected = {
        "applicationVersion": args.application_version or manifest["applicationVersion"],
        "sourceRevision": args.source_revision or manifest["sourceRevision"],
        "provider": args.provider or manifest["expectedDefaultChatProvider"],
    }
    for field, key in (
        ("applicationVersion", "applicationVersion"),
        ("sourceRevision", "sourceRevision"),
    ):
        if (
            args.__dict__.get(
                "application_version" if field == "applicationVersion" else "source_revision"
            )
            and expected[field] != manifest[key]
        ):
            raise VerificationError("manifest/evidence mismatch: argv expectation differs")
    if args.provider and args.provider != manifest["expectedDefaultChatProvider"]:
        raise VerificationError("manifest/evidence mismatch: provider differs")
    if args.compare_manifest:
        comparison = release_manifest.validate(
            release_manifest._object(args.compare_manifest), None
        )
        coordinates = (
            "applicationVersion",
            "sourceRevision",
            "imageTag",
            "imageDigest",
            "chartVersion",
            "chartDigest",
            "semanticTag",
            "expectedDefaultChatProvider",
        )
        if any(manifest[field] != comparison[field] for field in coordinates):
            raise VerificationError(
                "manifest/evidence mismatch: immutable staging and production coordinates differ"
            )
    smoke = args.smoke_runner.expanduser()
    if not smoke.is_file() or not os.access(smoke, os.X_OK):
        raise VerificationError("provider/chat smoke: runner must be an existing executable file")
    config = app_config.load_config("dspace", args.environment, args.config or None)
    host, token_origin, token_model = expectations(config, expected["provider"])
    base_url = f"https://{host}"
    coordinate = f"{release_manifest.IMAGE_REF}:{manifest['imageTag']}"
    digest = manifest["imageDigest"]

    deployment = _json_command(
        runner,
        [
            "kubectl",
            "--kubeconfig",
            args.kubeconfig,
            "-n",
            args.namespace,
            "get",
            "deployment",
            args.release,
            "-o",
            "json",
        ],
        "cluster identity",
    )
    live_containers = [
        item
        for item in deployment.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
        if isinstance(item, dict) and item.get("name") == "dspace"
    ]
    if len(live_containers) != 1 or live_containers[0].get("image") not in {
        coordinate,
        f"{coordinate}@{digest}",
    }:
        raise VerificationError("cluster identity: Deployment image differs from approval")
    live_env = {
        item.get("name"): item.get("value")
        for item in live_containers[0].get("env", [])
        if isinstance(item, dict)
    }
    if expected["provider"] == "token-place" and (
        live_env.get("DSPACE_TOKEN_PLACE_URL") != token_origin
        or live_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_model
    ):
        raise VerificationError("cluster identity: Deployment routing differs from values")

    if manifest["recordType"] == "final":
        helm = _json_command(
            runner,
            [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "status",
                args.release,
                "--namespace",
                args.namespace,
                "-o",
                "json",
            ],
            "staging drift",
        )
        if helm.get("version") != manifest["helmRevision"]:
            raise VerificationError("staging drift: Helm revision differs from evidence")
        chart = helm.get("chart", {}).get("metadata", {})
        if chart.get("name") != "dspace" or chart.get("version") != manifest["chartVersion"]:
            raise VerificationError("cluster identity: installed chart differs from approval")

    public_build = fetch(base_url + "/build-info.json", "public identity")
    _identity(
        public_build, expected["applicationVersion"], expected["sourceRevision"], "public identity"
    )
    public_value = json.loads(public_build)
    if public_value.get("image") is not None and public_value["image"] != coordinate:
        raise VerificationError("public identity: runtime image coordinate mismatch")
    _frontend(
        fetch(base_url + "/", "public identity"), expected["sourceRevision"], "public identity"
    )

    names: set[str] = set()
    for pod in _pods(runner, args.kubeconfig, args.namespace, args.release):
        metadata = pod.get("metadata", {})
        status = pod.get("status", {})
        name = metadata.get("name")
        if (
            not isinstance(name, str)
            or name in names
            or metadata.get("deletionTimestamp") is not None
        ):
            raise VerificationError("pod/replica identity: stale or duplicate replica")
        names.add(name)
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
        )
        containers = [
            c for c in pod.get("spec", {}).get("containers", []) if c.get("name") == "dspace"
        ]
        statuses = [c for c in status.get("containerStatuses", []) if c.get("name") == "dspace"]
        if (
            status.get("phase") != "Running"
            or not ready
            or len(containers) != 1
            or len(statuses) != 1
        ):
            raise VerificationError("pod/replica identity: replica is not Running and Ready")
        if containers[0].get("image") not in {coordinate, f"{coordinate}@{digest}"}:
            raise VerificationError("pod/replica identity: image coordinate mismatch")
        if not str(statuses[0].get("imageID", "")).endswith(digest):
            raise VerificationError("pod/replica identity: image digest mismatch")
        proxy = f"/api/v1/namespaces/{args.namespace}/pods/{name}:3000/proxy"
        direct_build = _command(
            runner,
            [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "get",
                "--raw",
                proxy + "/build-info.json",
            ],
            "direct identity",
        )
        _identity(
            direct_build.encode(),
            expected["applicationVersion"],
            expected["sourceRevision"],
            "direct identity",
        )
        direct_value = json.loads(direct_build)
        if direct_value != public_value:
            raise VerificationError("direct identity: public and direct identity differ")
        direct_html = _command(
            runner,
            ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw", proxy + "/"],
            "direct identity",
        )
        _frontend(direct_html.encode(), expected["sourceRevision"], "direct identity")

    smoke_command = [
        str(smoke),
        "--base-url",
        base_url,
        "--expected-version",
        expected["applicationVersion"],
        "--expected-revision",
        expected["sourceRevision"],
        "--expected-provider",
        expected["provider"],
    ]
    if expected["provider"] == "token-place":
        smoke_command += [
            "--expected-token-place-origin",
            token_origin,
            "--expected-token-place-model",
            token_model,
        ]
    _command(runner, smoke_command, "provider/chat smoke")
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": expected["applicationVersion"],
        "runtimeSourceRevision": expected["sourceRevision"],
        "frontendSourceRevision": expected["sourceRevision"],
        "defaultProvider": expected["provider"],
        "journeys": [
            {"name": "/build-info.json", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--environment", choices=("staging", "prod"), required=True)
        command.add_argument("--release", required=True)
        command.add_argument("--namespace", required=True)
        if name == "verify":
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--smoke-runner", type=Path, required=True)
            command.add_argument("--config", default="")
            command.add_argument("--kubeconfig", required=True)
            command.add_argument("--application-version")
            command.add_argument("--source-revision")
            command.add_argument("--provider", choices=("token-place", "openai"))
            command.add_argument("--compare-manifest", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            result = {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": list(CAPABILITIES),
            }
        else:
            result = verify(args)
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    except (VerificationError, release_manifest.ManifestError, app_config.AppConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
