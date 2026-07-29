#!/usr/bin/env python3
"""Fail-closed, non-destructive DSPACE runtime and chat verification."""

from __future__ import annotations

import argparse
import html.parser
import json
import os
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

from scripts import app_chart, app_config  # noqa: E402
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

CAPABILITIES = (
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
)
IMAGE_REF = release_manifest.IMAGE_REF
SAFE_STAGES = {
    "manifest/evidence mismatch",
    "cluster identity",
    "pod/replica identity",
    "public identity",
    "direct identity",
    "provider/chat smoke",
}


class VerificationError(ValueError):
    """A bounded, non-secret verification failure."""

    def __init__(self, stage: str, message: str):
        if stage not in SAFE_STAGES:
            stage = "cluster identity"
        super().__init__(f"{stage}: {message}")


Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    """Run argv without exposing child output."""
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise VerificationError(
            "cluster identity", "required command could not be started"
        ) from exc
    if completed.returncode:
        raise VerificationError("cluster identity", "required command failed")
    return completed.stdout


def exact_fields(value: dict[str, Any], expected: tuple[str, ...], label: str) -> None:
    if set(value) != set(expected):
        raise VerificationError("manifest/evidence mismatch", f"{label} schema is invalid")


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        release_manifest.validate(value, value.get("recordType") == "final")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise VerificationError(
            "manifest/evidence mismatch", "approved manifest is invalid"
        ) from exc


class RevisionParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.revision: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "meta" and values.get("name") == "dspace-build-revision":
            self.revision = values.get("content")


def http_get(url: str, expected_origin: str, opener=urllib.request.urlopen) -> bytes:
    try:
        response = opener(
            urllib.request.Request(url, headers={"Accept": "application/json,text/html"})
        )
        final = urllib.parse.urlsplit(response.geturl())
        origin = f"{final.scheme}://{final.netloc}"
        if origin != expected_origin:
            raise VerificationError("public identity", "redirected to an unexpected origin")
        return response.read(1024 * 1024 + 1)
    except VerificationError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError("public identity", "public endpoint is unreachable") from exc


def identity(body: bytes, expected: dict[str, Any], stage: str) -> dict[str, str]:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(stage, "build identity is malformed") from exc
    if not isinstance(value, dict):
        raise VerificationError(stage, "build identity is malformed")
    wanted = {
        "applicationVersion": expected["applicationVersion"],
        "revision": expected["sourceRevision"],
        "shortRevision": expected["sourceRevision"][:7],
    }
    if any(value.get(key) != item for key, item in wanted.items()):
        raise VerificationError(stage, "build version or revision does not match approval")
    coordinate = value.get("image") or value.get("imageCoordinate")
    if coordinate is not None and coordinate not in {
        f"{IMAGE_REF}:{expected['imageTag']}",
        f"{IMAGE_REF}:{expected['imageTag']}@{expected['imageDigest']}",
    }:
        raise VerificationError(stage, "runtime image coordinate does not match approval")
    return wanted


def frontend(body: bytes, revision: str, stage: str) -> None:
    try:
        parser = RevisionParser()
        parser.feed(body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise VerificationError(stage, "frontend revision marker is malformed") from exc
    if parser.revision != revision:
        raise VerificationError(stage, "frontend revision marker does not match approval")


def value_expectations(config: dict[str, str]) -> tuple[str, str, str]:
    values = tuple(item.strip() for item in config["SUGARKUBE_VALUES"].split(",") if item.strip())
    document = app_chart.merged_values_document(values)
    host = app_chart.scalar(app_chart.nested_value(document, ("ingress", "host"))[1])
    origin = model = ""
    env = app_chart.nested_value(document, ("env",))[1]
    if isinstance(env, list):
        mapped = {
            item.get("name"): item.get("value")
            for item in env
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        origin = app_chart.scalar(mapped.get("DSPACE_TOKEN_PLACE_URL"))
        model = app_chart.scalar(mapped.get("DSPACE_TOKEN_PLACE_CHAT_MODEL"))
    if not host:
        raise VerificationError("manifest/evidence mismatch", "values do not resolve ingress host")
    return host, origin, model


def pod_items(raw: str, expected: dict[str, Any]) -> list[dict[str, str]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError("cluster identity", "pod inventory is malformed") from exc
    items = value.get("items") if isinstance(value, dict) else None
    if not isinstance(items, list) or not items:
        raise VerificationError("pod/replica identity", "no serving DSPACE pods were found")
    result = []
    for item in items:
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        if metadata.get("deletionTimestamp") is not None:
            raise VerificationError("pod/replica identity", "a stale terminating replica exists")
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in status.get("conditions", [])
            if isinstance(c, dict)
        )
        if status.get("phase") != "Running" or not ready:
            raise VerificationError("pod/replica identity", "a replica is not Running and Ready")
        containers = [
            c for c in item.get("spec", {}).get("containers", []) if c.get("name") == "dspace"
        ]
        statuses = [c for c in status.get("containerStatuses", []) if c.get("name") == "dspace"]
        if len(containers) != 1 or len(statuses) != 1:
            raise VerificationError(
                "pod/replica identity", "a replica lacks its named dspace container"
            )
        approved = f"{IMAGE_REF}:{expected['imageTag']}"
        if containers[0].get("image") not in {approved, f"{approved}@{expected['imageDigest']}"}:
            raise VerificationError(
                "pod/replica identity", "a pod image coordinate does not match approval"
            )
        try:
            digest = release_manifest._image_id_digest(statuses[0].get("imageID", ""))
        except ValueError as exc:
            raise VerificationError(
                "pod/replica identity", "a pod image digest is malformed"
            ) from exc
        if digest != expected["imageDigest"]:
            raise VerificationError(
                "pod/replica identity", "a pod image digest does not match approval"
            )
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            raise VerificationError("pod/replica identity", "a pod name is invalid")
        result.append({"name": name, "imageID": statuses[0]["imageID"]})
    return sorted(result, key=lambda item: item["name"])


def verify(args: argparse.Namespace, runner: Runner = run) -> dict[str, Any]:
    expected = read_manifest(args.manifest)
    if expected["environment"] != args.environment:
        raise VerificationError("manifest/evidence mismatch", "manifest environment does not match")
    for field, actual in (
        ("applicationVersion", args.application_version),
        ("sourceRevision", args.source_revision),
        ("expectedDefaultChatProvider", args.provider),
    ):
        if actual and expected[field] != actual:
            raise VerificationError(
                "manifest/evidence mismatch", "argv expectations do not match manifest"
            )
    config = app_config.load_config("dspace", args.environment, args.config or None)
    helm_command = [
        "helm",
        "--kubeconfig",
        args.kubeconfig,
        "status",
        args.release,
        "--namespace",
        args.namespace,
        "-o",
        "json",
    ]
    starting_revision = None
    if expected.get("recordType") == "final":
        try:
            starting_revision = json.loads(runner(helm_command)).get("version")
        except (json.JSONDecodeError, AttributeError) as exc:
            raise VerificationError("cluster identity", "live Helm identity is malformed") from exc
        if starting_revision != expected["helmRevision"]:
            raise VerificationError(
                "cluster identity", "live Helm revision differs from finalized evidence"
            )
    host, token_origin, token_model = value_expectations(config)
    base_url = f"https://{host}"
    public_identity = identity(
        http_get(f"{base_url}/build-info.json", base_url), expected, "public identity"
    )
    frontend(http_get(f"{base_url}/", base_url), expected["sourceRevision"], "public identity")
    kubectl = ["kubectl", "--kubeconfig", args.kubeconfig, "-n", args.namespace]
    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}"
    pods = pod_items(runner([*kubectl, "get", "pods", "-l", selector, "-o", "json"]), expected)
    for pod in pods:
        prefix = f"/api/v1/namespaces/{args.namespace}/pods/{pod['name']}:3000/proxy"
        direct = identity(
            runner([*kubectl, "get", "--raw", f"{prefix}/build-info.json"]).encode(),
            expected,
            "direct identity",
        )
        frontend(
            runner([*kubectl, "get", "--raw", f"{prefix}/"]).encode(),
            expected["sourceRevision"],
            "direct identity",
        )
        if direct != public_identity:
            raise VerificationError("direct identity", "public and direct-origin identity differ")
    smoke = args.smoke_runner
    if not smoke.is_file() or not os.access(smoke, os.X_OK):
        raise VerificationError(
            "provider/chat smoke", "smoke runner must be an existing executable file"
        )
    command = [
        str(smoke),
        "--base-url",
        base_url,
        "--expected-version",
        expected["applicationVersion"],
        "--expected-revision",
        expected["sourceRevision"],
        "--expected-provider",
        expected["expectedDefaultChatProvider"],
    ]
    if expected["expectedDefaultChatProvider"] == "token-place":
        if not token_origin or not token_model:
            raise VerificationError(
                "manifest/evidence mismatch", "token.place expectations are absent from values"
            )
        command += [
            "--expected-token-place-origin",
            token_origin,
            "--expected-token-place-model",
            token_model,
        ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise VerificationError("provider/chat smoke", "smoke runner could not be started") from exc
    if completed.returncode:
        raise VerificationError("provider/chat smoke", "remote chat verification failed")
    if starting_revision is not None:
        try:
            stable_revision = json.loads(runner(helm_command)).get("version")
        except (json.JSONDecodeError, AttributeError) as exc:
            raise VerificationError("cluster identity", "live Helm identity is malformed") from exc
        if stable_revision != starting_revision:
            raise VerificationError("cluster identity", "Helm revision changed concurrently")
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": expected["applicationVersion"],
        "runtimeSourceRevision": expected["sourceRevision"],
        "frontendSourceRevision": expected["sourceRevision"],
        "defaultProvider": expected["expectedDefaultChatProvider"],
        "journeys": [{"name": "/", "passed": True}, {"name": "/chat", "passed": True}],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subs = result.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        command = subs.add_parser(name)
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
            command.add_argument("--provider")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            value = {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": list(CAPABILITIES),
            }
        else:
            value = verify(args)
        sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
        return 0
    except (VerificationError, app_config.AppConfigError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
