#!/usr/bin/env python3
"""Convert one bounded DSPACE verification observation to node-exporter textfile metrics."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG = re.compile(r"^main-[0-9a-f]{7}$")


def die(message):
    raise SystemExit(f"ERROR: {message}")


def load(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        die("input is missing or malformed")
    if not isinstance(value, dict):
        die("input root must be an object")
    return value


def quote(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def labels(**values):
    return "{" + ",".join(f'{key}="{quote(str(value))}"' for key, value in values.items()) + "}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument(
        "--result", required=True, help="JSON emitted by dspace_runtime_verifier.py"
    )
    parser.add_argument("--deployment-image-tag", required=True)
    parser.add_argument("--deployment-image-digest", required=True)
    parser.add_argument("--timestamp", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evidence, result = load(args.evidence), load(args.result)
    expected = evidence.get("sourceRevision")
    environment = evidence.get("environment")
    if evidence.get("recordType") != "final" or environment not in {"staging", "prod"}:
        die("evidence must be a finalized staging or production record")
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        die("evidence source revision is invalid")
    if not TAG.fullmatch(str(evidence.get("imageTag"))) or not DIGEST.fullmatch(
        str(evidence.get("imageDigest"))
    ):
        die("evidence image coordinate must be an immutable main revision and digest")
    required = {
        "schemaVersion",
        "environment",
        "release",
        "namespace",
        "applicationVersion",
        "runtimeSourceRevision",
        "frontendSourceRevision",
        "defaultProvider",
        "journeys",
    }
    if (
        set(result) != required
        or result.get("schemaVersion") != 1
        or result.get("environment") != environment
    ):
        die("runtime verifier result does not satisfy the exact contract")
    revision = result.get("runtimeSourceRevision")
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        die("runtime revision is invalid")
    journeys = result.get("journeys")
    chat = (
        [x for x in journeys if isinstance(x, dict) and x.get("name") == "/chat"]
        if isinstance(journeys, list)
        else []
    )
    if (
        len(chat) != 1
        or set(chat[0]) != {"name", "passed"}
        or not isinstance(chat[0]["passed"], bool)
    ):
        die("runtime verifier must report exactly one bounded /chat result")
    image_match = (
        args.deployment_image_tag == evidence["imageTag"]
        and args.deployment_image_digest == evidence["imageDigest"]
    )
    common = dict(
        application="dspace",
        environment=environment,
        expected_revision=expected,
        current_revision=revision,
    )
    coordinate_labels = labels(
        **common,
        image_tag=evidence["imageTag"],
        image_digest=evidence["imageDigest"],
    )
    lines = [
        "# HELP dspace_release_expected_info Approved immutable DSPACE release coordinate.",
        "# TYPE dspace_release_expected_info gauge",
        f"dspace_release_expected_info{coordinate_labels} 1",
        "# HELP dspace_deployment_image_pin_match Whether the active Deployment image "
        "equals finalized evidence.",
        "# TYPE dspace_deployment_image_pin_match gauge",
        f"dspace_deployment_image_pin_match{labels(**common)} {int(image_match)}",
        "# HELP dspace_chat_synthetic_success Result of the isolated non-mutating "
        "/chat smoke runner.",
        "# TYPE dspace_chat_synthetic_success gauge",
        f"dspace_chat_synthetic_success{labels(**common)} {int(chat[0]['passed'])}",
        "# HELP dspace_chat_synthetic_timestamp_seconds Unix time of the last executed "
        "/chat result.",
        "# TYPE dspace_chat_synthetic_timestamp_seconds gauge",
        f"dspace_chat_synthetic_timestamp_seconds{labels(**common)} {args.timestamp}",
    ]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
