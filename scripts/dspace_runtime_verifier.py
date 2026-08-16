#!/usr/bin/env python3
"""Prove DSPACE build identity, replica agreement, and the public chat journey."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import app_chart  # noqa: E402
from scripts import app_config  # noqa: E402
from scripts import dspace_release_manifest as release_manifest  # noqa: E402

CAPABILITIES = [
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "publicJourneys",
]
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
BUILD_FIELDS = {"version", "revision", "shortRevision", "buildTimestamp"}
OPTIONAL_BUILD_FIELDS = {"image"}
LEGACY_BUILD_FIELDS = {"gitSha", "generatedAt", "source"}
MODERN_IDENTITY_CONTRACT = "build-info-v1"
LEGACY_IDENTITY_CONTRACT = "legacy-build-meta-v1"
LEGACY_302_COORDINATES = {
    "schemaVersion": 2,
    "applicationVersion": "3.0.1",
    "sourceRevision": "1a31a569aff2dbeb238e8c2688b9e85140d2077d",
    "chartSourceRevision": "63063e287adb92a4158ce2c8e7d378b73f52c1c5",
    "imageTag": "main-1a31a56",
    "imageDigest": "sha256:23dbc573377549136c1f10b05706b3c176ffbabaf04a3194381a24752104a401",
    "chartVersion": "3.0.2",
    "chartDigest": "sha256:8b862135e52146f301a41259d6dabb053ed891d798fc1c8c95ca775b2b8e9575",
    "semanticTag": "v3.0.1",
    "expectedDefaultChatProvider": "openai",
}
LEGACY_303_COORDINATES = {
    **LEGACY_302_COORDINATES,
    "chartSourceRevision": "62da11005354e9f9a89c2e58584cdce4c8ec35aa",
    "chartVersion": "3.0.3",
    "chartDigest": "sha256:6ee663c426673bc0e516ed8f8b0ab11a918d2f2bb81fc9047b3eb37b78329f5c",
}
LEGACY_310_COORDINATES = {
    "schemaVersion": 2,
    "applicationVersion": "3.1.0",
    "sourceRevision": "018687f5a7f4de45508c6e36eb28afb3e44da24d",
    "chartSourceRevision": "719644999f284935f792dbe530511278643aa2ef",
    "imageTag": "main-018687f",
    "imageDigest": "sha256:2b95b7fdccdd011553c8d8617e3090ee27323996c532148fdb147cb9fd6e1b6c",
    "chartVersion": "3.1.1",
    "chartDigest": "sha256:e1f8ab8860e55ee3c8b8ca8cf7bce6ee7ae9c5dbc81ad8bf82b204b51773783b",
    "semanticTag": "v3.1.0",
    "expectedDefaultChatProvider": "token-place",
}
LEGACY_IDENTITY_COORDINATES = (
    LEGACY_302_COORDINATES,
    LEGACY_303_COORDINATES,
    LEGACY_310_COORDINATES,
)
META_RE = re.compile(
    r'<meta\s+[^>]*name=["\']dspace-build-revision["\'][^>]*content=["\']([^"\']+)',
    re.IGNORECASE,
)
IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}$")
BUILD_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{3})?Z$"
)
HTML_DOCUMENT_RE = re.compile(r"^\s*(?:<!doctype\s+html\b|<html\b)", re.IGNORECASE)
PUBLIC_HTTP_USER_AGENT = "sugarkube-dspace-runtime-verifier/1.0"
POD_SETTLE_TIMEOUT_SECONDS = 60.0
POD_SETTLE_INTERVAL_SECONDS = 2.0


class VerificationError(ValueError):
    """A bounded, non-secret verification failure."""


def fail(category: str) -> None:
    raise VerificationError(category)


def image_id_digest(image_id: object) -> str:
    """Return a canonical trailing runtime digest without exposing bad input."""
    if not isinstance(image_id, str):
        fail("pod/replica identity")
    match = IMAGE_ID_RE.search(image_id)
    if match is None:
        fail("pod/replica identity")
    return match.group(0)


def controller_owner(owners: object, kind: str) -> dict[str, Any]:
    """Select the sole controller owner of ``kind`` from Kubernetes metadata."""
    if not isinstance(owners, list):
        fail("pod/replica identity")
    matches = [
        owner
        for owner in owners
        if isinstance(owner, dict) and owner.get("kind") == kind and owner.get("controller") is True
    ]
    if len(matches) != 1:
        fail("pod/replica identity")
    return matches[0]


def helm_deployment_uid(metadata: object, release: str, namespace: str) -> str:
    """Validate that Deployment metadata belongs to the selected Helm release."""
    if not isinstance(metadata, dict):
        fail("cluster identity")
    uid = metadata.get("uid")
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    if (
        metadata.get("name") != release
        or not isinstance(uid, str)
        or not uid
        or not isinstance(labels, dict)
        or labels.get("app.kubernetes.io/managed-by") != "Helm"
        or labels.get("app.kubernetes.io/instance") != release
        or not isinstance(annotations, dict)
        or annotations.get("meta.helm.sh/release-name") != release
        or annotations.get("meta.helm.sh/release-namespace") != namespace
    ):
        fail("cluster identity")
    return uid


def command(argv: list[str]) -> str:
    try:
        completed = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=15)
    except subprocess.TimeoutExpired:
        fail("cluster identity")
    if completed.returncode:
        fail("cluster identity")
    return completed.stdout


def settle_selected_pods(
    argv: list[str],
    *,
    runner: Any = None,
    monotonic: Any = None,
    sleeper: Any = None,
) -> list[dict[str, Any]]:
    """Fetch fresh pod snapshots until selector-matched terminations disappear."""
    runner = command if runner is None else runner
    monotonic = time.monotonic if monotonic is None else monotonic
    sleeper = time.sleep if sleeper is None else sleeper
    deadline = monotonic() + POD_SETTLE_TIMEOUT_SECONDS
    while True:
        try:
            payload = json.loads(runner(argv))
            pods = payload.get("items") if isinstance(payload, dict) else None
        except (json.JSONDecodeError, TypeError):
            fail("pod/replica identity")
        if not isinstance(pods, list) or not all(isinstance(pod, dict) for pod in pods):
            fail("pod/replica identity")
        if not any(
            isinstance(pod.get("metadata"), dict)
            and pod["metadata"].get("deletionTimestamp") is not None
            for pod in pods
        ):
            return pods
        if monotonic() >= deadline:
            fail("pod/replica identity")
        sleeper(POD_SETTLE_INTERVAL_SECONDS)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str]):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme, parsed.netloc) != self.origin:
            fail("public identity")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, public_origin: tuple[str, str] | None = None) -> bytes:
    opener = (
        urllib.request.build_opener(SameOriginRedirect(public_origin))
        if public_origin
        else urllib.request.build_opener()
    )
    request = urllib.request.Request(url, headers={"User-Agent": PUBLIC_HTTP_USER_AGENT})
    try:
        with opener.open(request, timeout=15) as response:
            return response.read(1024 * 1024 + 1)
    except (OSError, urllib.error.URLError, VerificationError) as exc:
        if isinstance(exc, VerificationError):
            raise
        fail("public identity" if public_origin else "direct identity")
    raise AssertionError("unreachable")


def identity(
    raw: bytes, version: str, revision: str, image: str, category: str
) -> tuple[str, str, str, str]:
    if len(raw) > 1024 * 1024:
        fail(category)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        fail(category)
    if (
        not isinstance(value, dict)
        or not BUILD_FIELDS <= set(value)
        or set(value) - BUILD_FIELDS - OPTIONAL_BUILD_FIELDS
    ):
        fail(category)
    if (
        value.get("version") != version
        or value.get("revision") != revision
        or value.get("shortRevision") != revision[:7]
    ):
        fail(category)
    runtime_image = value.get("image")
    if runtime_image is not None and runtime_image != image:
        fail(category)
    build_timestamp = value.get("buildTimestamp")
    if (
        not isinstance(build_timestamp, str)
        or not build_timestamp
        or len(build_timestamp) > 40
        or any(ord(character) < 32 or ord(character) == 127 for character in build_timestamp)
        or BUILD_TIMESTAMP_RE.fullmatch(build_timestamp) is None
    ):
        fail(category)
    try:
        datetime.fromisoformat(build_timestamp.replace("Z", "+00:00"))
    except ValueError:
        fail(category)
    return version, revision, runtime_image or image, build_timestamp


def marker(raw: bytes, revision: str, category: str) -> None:
    if len(raw) > 1024 * 1024:
        fail(category)
    try:
        match = META_RE.search(raw.decode("utf-8"))
    except UnicodeDecodeError:
        fail(category)
    if match is None or match.group(1) != revision:
        fail(category)


def identity_contract(manifest: dict[str, Any]) -> str:
    """Select legacy identity only for a complete approved immutable tuple."""
    if any(
        all(manifest.get(key) == value for key, value in coordinates.items())
        for coordinates in LEGACY_IDENTITY_COORDINATES
    ):
        return LEGACY_IDENTITY_CONTRACT
    return MODERN_IDENTITY_CONTRACT


def named_http_port(container: object, category: str) -> int:
    """Return the unique, valid named HTTP container port."""
    if not isinstance(container, dict) or not isinstance(container.get("ports"), list):
        fail(category)
    matches = [
        port for port in container["ports"] if isinstance(port, dict) and port.get("name") == "http"
    ]
    if len(matches) != 1:
        fail(category)
    value = matches[0].get("containerPort")
    if type(value) is not int or not 1 <= value <= 65535:
        fail(category)
    return value


def legacy_identity(raw: bytes, revision: str, category: str) -> tuple[str, str, str]:
    """Validate and normalize the legacy public build metadata contract."""
    if len(raw) > 1024 * 1024:
        fail(category)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        fail(category)
    if not isinstance(value, dict) or set(value) != LEGACY_BUILD_FIELDS:
        fail(category)
    generated_at, source = value.get("generatedAt"), value.get("source")
    if value.get("gitSha") != revision or not isinstance(generated_at, str) or not generated_at:
        fail(category)
    if not isinstance(source, str) or not source.strip():
        fail(category)
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        fail(category)
    if timestamp.tzinfo is None:
        fail(category)
    return revision, generated_at, source


def root_document(raw: bytes, category: str) -> None:
    """Require a bounded UTF-8 HTML root document without inferring identity."""
    if len(raw) > 1024 * 1024:
        fail(category)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail(category)
    if HTML_DOCUMENT_RE.search(value) is None:
        fail(category)


def values_expectations(paths: list[Path]) -> tuple[str, str]:
    """Resolve token.place settings through the same ordered merge used by app_chart."""
    try:
        document = app_chart.merged_values_document(tuple(str(path) for path in paths))
    except (ValueError, json.JSONDecodeError):
        fail("manifest/evidence mismatch")
    found: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            name = value.get("name")
            scalar = value.get("value")
            if name in {"DSPACE_TOKEN_PLACE_URL", "DSPACE_TOKEN_PLACE_CHAT_MODEL"} and isinstance(
                scalar, str
            ):
                found[str(name)] = scalar
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    if set(found) != {"DSPACE_TOKEN_PLACE_URL", "DSPACE_TOKEN_PLACE_CHAT_MODEL"}:
        fail("manifest/evidence mismatch")
    return found["DSPACE_TOKEN_PLACE_URL"], found["DSPACE_TOKEN_PLACE_CHAT_MODEL"]


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return release_manifest.validate(value)
    except (OSError, json.JSONDecodeError, release_manifest.ManifestError):
        fail("manifest/evidence mismatch")
    raise AssertionError("unreachable")


def verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.manifest)
    contract = identity_contract(manifest)
    identity_path = (
        "/build-meta.json" if contract == LEGACY_IDENTITY_CONTRACT else "/build-info.json"
    )
    expected = {
        "version": manifest["applicationVersion"],
        "revision": manifest["sourceRevision"],
        "provider": manifest["expectedDefaultChatProvider"],
        "image_tag": manifest["imageTag"],
        "digest": manifest["imageDigest"],
        "chart_version": manifest["chartVersion"],
    }
    for field, supplied in (
        ("version", args.application_version),
        ("revision", args.source_revision),
        ("provider", args.provider),
    ):
        if supplied is not None and supplied != expected[field]:
            fail("manifest/evidence mismatch")

    config = app_config.load_config(
        "dspace", args.environment, str(args.config) if args.config else None
    )
    values = [Path(item).expanduser() for item in config["SUGARKUBE_VALUES"].split(",")]
    values = [path if path.is_absolute() else REPO_ROOT / path for path in values]
    host = args.host or _resolve_host(values)
    base_url = f"https://{host}"
    origin = ("https", host)

    runner = args.smoke_runner or os.environ.get("DSPACE_SMOKE_RUNNER", "")
    smoke = Path(runner).expanduser() if runner else None
    if smoke is None or not smoke.is_file() or not os.access(smoke, os.X_OK):
        fail("provider/chat smoke")

    selector = f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}"
    pods = settle_selected_pods(
        [
            "kubectl",
            "--kubeconfig",
            args.kubeconfig,
            "-n",
            args.namespace,
            "get",
            "pods",
            "-l",
            selector,
            "-o",
            "json",
        ]
    )
    if not pods:
        fail("pod/replica identity")

    canonical_image = f"{release_manifest.IMAGE_REF}:{expected['image_tag']}"
    rollback_image = f"{canonical_image}@{expected['digest']}"
    permitted_images = {canonical_image, rollback_image}
    token_values = values_expectations(values) if expected["provider"] == "token-place" else None
    try:
        deployment = json.loads(
            command(
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
                ]
            )
        )
        deployment_metadata = deployment["metadata"]
        containers = deployment["spec"]["template"]["spec"]["containers"]
        applications = [item for item in containers if item.get("name") == "dspace"]
    except (json.JSONDecodeError, KeyError, TypeError):
        fail("cluster identity")
    deployment_uid = helm_deployment_uid(deployment_metadata, args.release, args.namespace)
    declared_image = applications[0].get("image") if len(applications) == 1 else None
    if declared_image not in permitted_images:
        fail("cluster identity")
    proxy_port = named_http_port(applications[0], "cluster identity")
    if token_values is not None:
        live_env = {item.get("name"): item.get("value") for item in applications[0].get("env", [])}
        if (
            live_env.get("DSPACE_TOKEN_PLACE_URL") != token_values[0]
            or live_env.get("DSPACE_TOKEN_PLACE_CHAT_MODEL") != token_values[1]
        ):
            fail("cluster identity")

    helm_before = helm_identity(args, expected["chart_version"])

    replica_identity: tuple[str, str, str] | tuple[str, str, str, str] | None = None
    for pod in pods:
        metadata, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        if not all(isinstance(value, dict) for value in (metadata, spec, status)):
            fail("pod/replica identity")
        conditions = status.get("conditions", [])
        containers = spec.get("containers", [])
        statuses = status.get("containerStatuses", [])
        if not all(
            isinstance(items, list) and all(isinstance(item, dict) for item in items)
            for items in (conditions, containers, statuses)
        ):
            fail("pod/replica identity")
        if metadata.get("deletionTimestamp") is not None or status.get("phase") != "Running":
            fail("pod/replica identity")
        if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            fail("pod/replica identity")
        owner = controller_owner(metadata.get("ownerReferences", []), "ReplicaSet")
        replica_set_name, replica_set_uid = owner.get("name"), owner.get("uid")
        if not isinstance(replica_set_name, str) or not isinstance(replica_set_uid, str):
            fail("pod/replica identity")
        try:
            replica_set = json.loads(
                command(
                    [
                        "kubectl",
                        "--kubeconfig",
                        args.kubeconfig,
                        "-n",
                        args.namespace,
                        "get",
                        "replicaset",
                        replica_set_name,
                        "-o",
                        "json",
                    ]
                )
            )
            rs_metadata = replica_set["metadata"]
            rs_owners = rs_metadata["ownerReferences"]
        except (json.JSONDecodeError, KeyError, TypeError, VerificationError):
            fail("pod/replica identity")
        if rs_metadata.get("name") != replica_set_name or rs_metadata.get("uid") != replica_set_uid:
            fail("pod/replica identity")
        rs_owner = controller_owner(rs_owners, "Deployment")
        if rs_owner.get("name") != args.release or rs_owner.get("uid") != deployment_uid:
            fail("pod/replica identity")
        containers = [c for c in containers if c.get("name") == "dspace"]
        statuses = [c for c in statuses if c.get("name") == "dspace"]
        if len(containers) != 1 or containers[0].get("image") != declared_image:
            fail("pod/replica identity")
        if named_http_port(containers[0], "pod/replica identity") != proxy_port:
            fail("pod/replica identity")
        image_id = statuses[0].get("imageID") if len(statuses) == 1 else None
        if image_id_digest(image_id) != expected["digest"]:
            fail("pod/replica identity")
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            fail("pod/replica identity")
        proxy = ["kubectl", "--kubeconfig", args.kubeconfig, "get", "--raw"]
        prefix = f"/api/v1/namespaces/{args.namespace}/pods/{name}:{proxy_port}/proxy"
        try:
            direct_build = command(proxy + [prefix + identity_path]).encode()
            direct_html = command(proxy + [prefix + "/"]).encode()
        except VerificationError:
            fail("direct identity")
        direct_identity = (
            legacy_identity(direct_build, expected["revision"], "direct identity")
            if contract == LEGACY_IDENTITY_CONTRACT
            else identity(
                direct_build,
                expected["version"],
                expected["revision"],
                canonical_image,
                "direct identity",
            )
        )
        if replica_identity is not None and direct_identity != replica_identity:
            fail("pod/replica identity")
        replica_identity = direct_identity
        if contract == LEGACY_IDENTITY_CONTRACT:
            root_document(direct_html, "direct identity")
        else:
            marker(direct_html, expected["revision"], "direct identity")

    public_identity = (
        legacy_identity(
            fetch(base_url + identity_path, origin),
            expected["revision"],
            "public identity",
        )
        if contract == LEGACY_IDENTITY_CONTRACT
        else identity(
            fetch(base_url + identity_path, origin),
            expected["version"],
            expected["revision"],
            canonical_image,
            "public identity",
        )
    )
    if public_identity != replica_identity:
        fail("public identity")
    public_root = fetch(base_url + "/", origin)
    if contract == LEGACY_IDENTITY_CONTRACT:
        root_document(public_root, "public identity")
    else:
        marker(public_root, expected["revision"], "public identity")

    smoke_argv = [
        str(smoke),
        "--base-url",
        base_url,
        "--expected-version",
        expected["version"],
        "--expected-revision",
        expected["revision"],
        "--expected-provider",
        expected["provider"],
        "--identity-contract",
        contract,
    ]
    if expected["provider"] == "token-place":
        assert token_values is not None
        token_origin, token_model = token_values
        smoke_argv += [
            "--expected-token-place-origin",
            token_origin,
            "--expected-token-place-model",
            token_model,
        ]
    try:
        completed = subprocess.run(
            smoke_argv, text=True, capture_output=True, check=False, timeout=300
        )
    except subprocess.TimeoutExpired:
        fail("provider/chat smoke")
    if completed.returncode:
        fail("provider/chat smoke")
    if (
        helm_identity(
            args,
            expected["chart_version"],
            validation_category="concurrent Helm change",
            enforce_expected_revision=False,
        )
        != helm_before
    ):
        fail("concurrent Helm change")
    return {
        "schemaVersion": 1,
        "environment": args.environment,
        "release": args.release,
        "namespace": args.namespace,
        "applicationVersion": expected["version"],
        "runtimeSourceRevision": expected["revision"],
        "frontendSourceRevision": expected["revision"],
        "defaultProvider": expected["provider"],
        "journeys": [
            {
                "name": identity_path,
                "passed": True,
            },
            {"name": "/", "passed": True},
            {"name": "/chat", "passed": True},
        ],
    }


def helm_identity(
    args: argparse.Namespace,
    chart_version: str,
    validation_category: str = "cluster identity",
    enforce_expected_revision: bool = True,
) -> tuple[str, str, int]:
    try:
        status = json.loads(
            command(
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
                ]
            )
        )
        history = None
        if release_manifest.helm_status_needs_history(status):
            history = json.loads(
                command(
                    [
                        "helm",
                        "--kubeconfig",
                        args.kubeconfig,
                        "history",
                        args.release,
                        "--namespace",
                        args.namespace,
                        "-o",
                        "json",
                    ]
                )
            )
        name, version, revision = release_manifest.resolve_helm_identity(
            status, history, "dspace", chart_version
        )
    except (json.JSONDecodeError, release_manifest.ManifestError):
        fail(validation_category)
    if (
        enforce_expected_revision
        and getattr(args, "expected_helm_revision", None) is not None
        and revision != args.expected_helm_revision
    ):
        fail("staging drift")
    return name, version, revision


def _resolve_host(paths: list[Path]) -> str:
    result = command(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/app_chart.py"),
            "resolve-host",
            "--values",
            ",".join(str(path) for path in paths),
        ]
    ).strip()
    if not result or "/" in result:
        fail("manifest/evidence mismatch")
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VerificationError("invalid arguments")


def parser() -> argparse.ArgumentParser:
    result = SafeParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("capabilities", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--environment", required=True, choices=("staging", "prod"))
        item.add_argument("--release", required=True)
        item.add_argument("--namespace", required=True)
        if name == "capabilities":
            # Accepted but deliberately unused so callers can negotiate the
            # extended verify argv before a deployment or rollback mutation.
            item.add_argument("--manifest", type=Path)
            item.add_argument("--smoke-runner")
            item.add_argument("--config", type=Path)
            item.add_argument("--kubeconfig")
        else:
            item.add_argument("--manifest", type=Path, required=True)
            item.add_argument("--smoke-runner")
            item.add_argument("--config", type=Path)
            item.add_argument("--kubeconfig", required=True)
            item.add_argument("--host")
            item.add_argument("--application-version")
            item.add_argument("--source-revision")
            item.add_argument("--provider", choices=("token-place", "openai"))
            item.add_argument("--expected-helm-revision", type=int)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        value = (
            {
                "schemaVersion": 1,
                "environment": args.environment,
                "release": args.release,
                "namespace": args.namespace,
                "capabilities": CAPABILITIES,
            }
            if args.command == "capabilities"
            else verify(args)
        )
        print(json.dumps(value, separators=(",", ":")))
        return 0
    except (VerificationError, app_config.AppConfigError) as exc:
        if isinstance(exc, app_config.AppConfigError):
            exc = VerificationError("manifest/evidence mismatch")
        print(f"ERROR: DSPACE verification failed ({exc})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
