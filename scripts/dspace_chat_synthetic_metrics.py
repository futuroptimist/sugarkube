#!/usr/bin/env python3
"""Atomically publish the bounded contract produced by a pinned DSPACE smoke runner."""

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--runner-revision", required=True)
    p.add_argument("--now", type=int, default=None)
    a = p.parse_args()
    if not SHA.fullmatch(a.runner_revision):
        p.error("--runner-revision must be a full immutable commit SHA")
    data = json.loads(a.result.read_text())
    allowed = {"schemaVersion", "journey", "passed", "mutationDisabled", "transport", "completedAt"}
    if (
        set(data) != allowed
        or data["schemaVersion"] != 1
        or data["journey"] != "/chat"
        or data["mutationDisabled"] is not True
        or data["transport"] != "intercepted"
    ):
        p.error("result violates the isolated non-mutating /chat contract")
    completed = int(data["completedAt"])
    now = a.now or int(time.time())
    if completed > now + 60 or completed < now - 3600:
        p.error("result is future-dated or too old to publish")
    labels = (
        'application="dspace",environment="staging",cluster="sugarkube-int",runner_revision="%s"'
        % a.runner_revision
    )
    content = (
        "# HELP dspace_chat_synthetic_success Last executed isolated /chat synthetic result.\n# TYPE dspace_chat_synthetic_success gauge\ndspace_chat_synthetic_success{%s} %d\n# HELP dspace_chat_synthetic_last_run_timestamp_seconds Completion time of the last executed synthetic.\n# TYPE dspace_chat_synthetic_last_run_timestamp_seconds gauge\ndspace_chat_synthetic_last_run_timestamp_seconds{%s} %d\n"
        % (labels, 1 if data["passed"] is True else 0, labels, completed)
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=a.output.parent, prefix=".dspace-chat-", text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, a.output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


if __name__ == "__main__":
    main()
