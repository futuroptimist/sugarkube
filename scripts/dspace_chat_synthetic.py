#!/usr/bin/env python3
"""Construct, validate, run, and install the pinned DSPACE chat synthetic."""

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import grp
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

SHA = __import__("re").compile(r"[0-9a-f]{40}")
APPROVED = ("3.1.1", "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2", "legacy-no-default-provider-v1")
REQUIRED = {
    "schemaVersion",
    "repository",
    "runnerRevision",
    "dspaceVersion",
    "dspaceSourceRevision",
    "identityContract",
    "providerConfigContract",
    "provider",
    "origin",
    "model",
    "timeoutSeconds",
    "serviceUser",
    "serviceGroup",
    "runnerRoot",
    "resultRoot",
    "metricPath",
    "runnerCommand",
    "runnerArguments",
}


class Invalid(RuntimeError):
    pass


def load_config(path: Path) -> dict:
    value = json.loads(path.read_text())
    if set(value) != REQUIRED or value["schemaVersion"] != 1:
        raise Invalid("configuration fields do not match the explicit contract")
    if not all(SHA.fullmatch(value[k]) for k in ("runnerRevision", "dspaceSourceRevision")):
        raise Invalid("coordinates must be full commit IDs")
    if value["identityContract"] != "build-info-v1":
        raise Invalid("identity contract was not explicitly selected")
    if (
        value["dspaceVersion"],
        value["dspaceSourceRevision"],
        value["providerConfigContract"],
    ) != APPROVED:
        raise Invalid("legacy provider contract is restricted to approved immutable coordinates")
    if value["provider"] != "token-place" or not 1 <= value["timeoutSeconds"] <= 600:
        raise Invalid("provider or timeout is outside the approved contract")
    for key in ("runnerRoot", "resultRoot", "metricPath"):
        if not Path(value[key]).is_absolute() or "$" in value[key]:
            raise Invalid(f"{key} must be an absolute resolved path")
    return value


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if result.returncode:
        raise Invalid("git validation failed")
    return result.stdout.strip()


def validate_git(repo: Path, revision: str, repository: str | None = None) -> None:
    if not (repo / ".git").exists() or (repo / ".git").is_file():
        raise Invalid("complete independent Git metadata is required")
    if (repo / ".git/objects/info/alternates").exists():
        raise Invalid("external Git object stores are forbidden")
    if (
        git(repo, "rev-parse", "HEAD") != revision
        or git(repo, "cat-file", "-t", revision) != "commit"
    ):
        raise Invalid("runner HEAD or commit object mismatch")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise Invalid("tracked worktree/index is dirty")
    if repository and git(repo, "remote", "get-url", "origin").rstrip("/") != repository.rstrip(
        "/"
    ):
        raise Invalid("repository identity mismatch")
    git(repo, "fsck", "--full", "--no-dangling")


def hashes(root: Path) -> dict[str, str]:
    names = (
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "frontend/package.json",
        "frontend/tests/remote-chat-smoke.spec.ts",
    )
    result = {}
    for name in names:
        path = root / name
        if not path.is_file():
            raise Invalid(f"critical file missing: {name}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def validate_runner(root: Path, config: dict) -> None:
    validate_git(root, config["runnerRevision"], config["repository"])
    manifest = json.loads((root / "sugarkube-runner-manifest.json").read_text())
    if manifest != {"revision": config["runnerRevision"], "files": hashes(root)}:
        raise Invalid("critical-file hash mismatch")
    store = root / "node_modules/.pnpm"
    shim = root / config["runnerCommand"]
    if not store.is_dir() or not shim.is_file() or not os.access(shim, os.X_OK):
        raise Invalid("root pnpm store or executable Playwright shim missing")
    if any(p.is_symlink() and not p.exists() for p in (root / "frontend/node_modules").rglob("*")):
        raise Invalid("broken frontend dependency link")
    subprocess.run(
        [str(shim), "--version"],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )


def materialize(source: Path, revision: str, destination: Path, config: dict, pnpm: str) -> None:
    if revision != config["runnerRevision"] or destination.exists():
        raise Invalid("exact runner revision and a new destination are required")
    validate_git(source, revision, config["repository"])
    stage = destination.with_name(destination.name + ".staging")
    if stage.exists():
        raise Invalid("staging target already exists")
    try:
        subprocess.run(
            ["git", "clone", "--no-local", str(source), str(stage)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", str(stage), "checkout", "--detach", revision],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", str(stage), "remote", "set-url", "origin", config["repository"]],
            check=True,
        )
        subprocess.run([pnpm, "install", "--frozen-lockfile", "--offline"], cwd=stage, check=True)
        manifest = {"revision": revision, "files": hashes(stage)}
        (stage / "sugarkube-runner-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True) + "\n"
        )
        validate_runner(stage, config)
        os.replace(stage, destination)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def checked_dir(path: Path, uid: int, gid: int, mode: int) -> None:
    s = path.stat()
    if not stat.S_ISDIR(s.st_mode) or (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) != (
        uid,
        gid,
        mode,
    ):
        raise Invalid(f"ownership/mode mismatch: {path}")


def run(config: dict) -> None:
    invocation = os.environ.get("INVOCATION_ID", "")
    if not SHA.fullmatch(invocation):
        raise Invalid("exact systemd INVOCATION_ID is required")
    user, group = pwd.getpwnam(config["serviceUser"]), grp.getgrnam(config["serviceGroup"])
    root = Path(config["resultRoot"])
    checked_dir(root, 0, group.gr_gid, 0o710)
    runner = Path(config["runnerRoot"]) / config["runnerRevision"]
    validate_runner(runner, config)
    lock = os.open(root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise Invalid("overlapping invocation rejected") from exc
    result_dir = root / f"{user.pw_name}-{invocation}"
    if result_dir.exists():
        raise Invalid("invocation result path already exists")
    result_dir.mkdir(mode=0o770)
    os.chown(result_dir, 0, group.gr_gid)
    result = result_dir / "result.json"
    started = int(time.time())
    argv = [
        str(runner / config["runnerCommand"]),
        *config["runnerArguments"],
        "--provider",
        config["provider"],
        "--origin",
        config["origin"],
        "--model",
        config["model"],
        "--identity-contract",
        config["identityContract"],
        "--provider-config-contract",
        config["providerConfigContract"],
        "--result",
        str(result),
        "--invocation-id",
        invocation,
        "--started-at",
        str(started),
    ]

    def demote():
        os.setgroups([group.gr_gid])
        os.setgid(group.gr_gid)
        os.setuid(user.pw_uid)

    try:
        subprocess.run(
            argv,
            cwd=runner,
            preexec_fn=demote,
            timeout=config["timeoutSeconds"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        ended = int(time.time())
        s = result.stat()
        if (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) != (user.pw_uid, group.gr_gid, 0o600):
            raise Invalid("result ownership/mode mismatch")
        value = json.loads(result.read_text())
        expected = {
            "schemaVersion",
            "passed",
            "runnerRevision",
            "invocationId",
            "startedAt",
            "endedAt",
        }
        if (
            set(value) != expected
            or value["runnerRevision"] != config["runnerRevision"]
            or value["invocationId"] != invocation
        ):
            raise Invalid("malformed or shared result")
        if not (started <= value["startedAt"] <= value["endedAt"] <= ended):
            raise Invalid("result is outside invocation window")
        metric = (
            "# HELP dspace_chat_synthetic_success Last executed isolated /chat result.\n"
            "# TYPE dspace_chat_synthetic_success gauge\n"
            f'dspace_chat_synthetic_success{{application="dspace",environment="staging",cluster="sugarkube-int"}} {int(value["passed"] is True)}\n'
            "# HELP dspace_chat_synthetic_timestamp_seconds Unix time of the last execution.\n"
            "# TYPE dspace_chat_synthetic_timestamp_seconds gauge\n"
            f'dspace_chat_synthetic_timestamp_seconds{{application="dspace",environment="staging",cluster="sugarkube-int"}} {ended}\n'
        )
        target = Path(config["metricPath"])
        fd, temporary = tempfile.mkstemp(prefix=".dspace-chat.", dir=target.parent)
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(metric)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        print(f"invocation={invocation} result=consumed start={started} end={ended}")
    finally:
        shutil.rmtree(result_dir, ignore_errors=True)
        os.close(lock)


def install(args, config: dict) -> None:
    prefix = args.prefix.resolve()
    runner = args.runner.resolve()
    validate_runner(runner, config)
    files = {
        "usr/local/libexec/sugarkube-dspace-chat-synthetic": args.wrapper,
        "usr/local/libexec/sugarkube-dspace-chat-synthetic.py": Path(__file__),
        "etc/sugarkube/dspace-chat-synthetic.json": args.config,
        "etc/systemd/system/sugarkube-dspace-chat-synthetic.service": args.service,
        "etc/systemd/system/sugarkube-dspace-chat-synthetic.timer": args.timer,
    }
    if not args.apply:
        print("validated dry-run; no files changed")
        return
    revision_dir = prefix / "var/lib/sugarkube/dspace-chat-runner" / config["runnerRevision"]
    revision_dir.parent.mkdir(parents=True, exist_ok=True)
    if not revision_dir.exists():
        shutil.copytree(runner, revision_dir, symlinks=True)
    for relative, source in files.items():
        target = prefix / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".new")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    print("installed without service or timer activation")


def rollback(prefix: Path, revision: str, config: dict) -> None:
    if not SHA.fullmatch(revision):
        raise Invalid("rollback requires an exact revision")
    retained = prefix.resolve() / "var/lib/sugarkube/dspace-chat-runner" / revision
    rollback_config = dict(config)
    rollback_config["runnerRevision"] = revision
    validate_runner(retained, rollback_config)
    pointer = retained.parent / "current"
    temporary = pointer.with_name(".current.new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(revision)
    os.replace(temporary, pointer)
    print(f"selected validated retained revision {revision}; no service action performed")


def status(prefix: Path, config: dict) -> None:
    root = prefix.resolve()
    targets = {
        "wrapper": root / "usr/local/libexec/sugarkube-dspace-chat-synthetic",
        "configuration": root / "etc/sugarkube/dspace-chat-synthetic.json",
        "service": root / "etc/systemd/system/sugarkube-dspace-chat-synthetic.service",
        "timer": root / "etc/systemd/system/sugarkube-dspace-chat-synthetic.timer",
    }
    file_hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        for name, path in targets.items()
    }
    activation = {"timerActive": "not-queried", "timerEnabled": "not-queried"}
    if root == Path("/") and shutil.which("systemctl"):
        for key, operation in (("timerActive", "is-active"), ("timerEnabled", "is-enabled")):
            result = subprocess.run(
                ["systemctl", operation, "sugarkube-dspace-chat-synthetic.timer"],
                text=True,
                capture_output=True,
                timeout=5,
            )
            activation[key] = result.stdout.strip()[:32] or "unknown"
    print(
        json.dumps(
            {
                "runnerRevision": config["runnerRevision"],
                "dspaceVersion": config["dspaceVersion"],
                "dspaceSourceRevision": config["dspaceSourceRevision"],
                "identityContract": config["identityContract"],
                "providerConfigContract": config["providerConfigContract"],
                "fileSha256": file_hashes,
                **activation,
            },
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run", "status"):
        p = subs.add_parser(name)
        p.add_argument("--config", required=True, type=Path)
        if name == "status":
            p.add_argument("--prefix", default=Path("/"), type=Path)
    p = subs.add_parser("materialize")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--revision", required=True)
    p.add_argument("--destination", required=True, type=Path)
    p.add_argument("--pnpm", default="pnpm")
    p = subs.add_parser("install")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--runner", required=True, type=Path)
    p.add_argument("--prefix", required=True, type=Path)
    p.add_argument("--wrapper", required=True, type=Path)
    p.add_argument("--service", required=True, type=Path)
    p.add_argument("--timer", required=True, type=Path)
    p.add_argument("--apply", action="store_true")
    p = subs.add_parser("rollback")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--prefix", required=True, type=Path)
    p.add_argument("--revision", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "validate":
        print("configuration valid")
    elif args.command == "run":
        run(config)
    elif args.command == "materialize":
        materialize(args.source, args.revision, args.destination, config, args.pnpm)
    elif args.command == "install":
        install(args, config)
    elif args.command == "rollback":
        rollback(args.prefix, args.revision, config)
    elif args.command == "status":
        status(args.prefix, config)
    else:
        raise Invalid("unsupported command")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Invalid, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"dspace synthetic validation failed: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
