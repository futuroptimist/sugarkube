#!/usr/bin/env python3
"""Approved disposable guest only: bound tests, preserve evidence, graceful shutdown.

No networking, package installation, reboot, force-unmount or hard power-off.
All privileged behavior is behind --run-approved and explicit guest preflight.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

from resolver_lifecycle import FLAGS, ROOT, UNITS, baseline

if sys.flags.optimize:
    raise SystemExit("One-shot qualification requires assertions enabled.")

EVIDENCE = Path("/var/lib/sugarkube-qualification-evidence")


def save(name, value):
    path = EVIDENCE / name
    temporary = path.with_suffix(path.suffix + ".new")
    with temporary.open("w") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    fd = os.open(EVIDENCE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def command(*args, deadline=None):
    remaining = 10 if deadline is None else min(10, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError("qualification budget exhausted")
    return subprocess.check_output(
        args, text=True, timeout=remaining, stderr=subprocess.STDOUT
    ).strip()


def processes():
    records = []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            # comm may include spaces/parentheses: split after its closing delimiter.
            fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
            records.append(
                {
                    "pid": int(directory.name),
                    "state": fields[0],
                    "pgid": int(fields[2]),
                    "sid": int(fields[3]),
                    "start_ticks": int(fields[19]),
                }
            )
        except (FileNotFoundError, ProcessLookupError):
            continue
    return records


def owned(records, pgid, start_ticks):
    matches = [r for r in records if r["pgid"] == pgid]
    if any(r["sid"] != pgid or r["start_ticks"] < start_ticks for r in matches):
        raise RuntimeError("process-group ownership is ambiguous; do not signal")
    leader = [r for r in matches if r["pid"] == pgid]
    if leader and leader[0]["start_ticks"] != start_ticks:
        raise RuntimeError("process-group leader identity changed; do not signal")
    return matches


def fixtures():
    return ([ROOT] if ROOT.exists() else []) + sorted(Path("/tmp").glob("sugarkube-view-proof-*"))


def mount_evidence():
    records = {}
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            lines = (directory / "mountinfo").read_text().splitlines()
        except (FileNotFoundError, ProcessLookupError):
            continue
        matching = [
            line for line in lines if str(ROOT) in line or "/tmp/sugarkube-view-proof-" in line
        ]
        if matching:
            records[directory.name] = matching
    return records


def unit_evidence(deadline):
    return {
        unit: command(
            "systemctl",
            "show",
            unit,
            "--property=LoadState,ActiveState,SubState,MainPID,ControlGroup",
            deadline=deadline,
        )
        for unit in UNITS
    }


def already_cleaned(properties):
    values = dict(line.split("=", 1) for line in properties.splitlines())
    return (
        values.get("LoadState") == "not-found"
        and values.get("MainPID") == "0"
        and values.get("ActiveState") == "inactive"
    )


def probe_cgroup_processes():
    # These system services use the default system.slice; inspect even after unload.
    records = {}
    for unit in UNITS:
        path = Path("/sys/fs/cgroup/system.slice") / unit / "cgroup.procs"
        try:
            records[unit] = [int(pid) for pid in path.read_text().split()]
        except FileNotFoundError:
            records[unit] = []
    return records


def verify_bundle(bundle):
    for line in (bundle / "SHA256SUMS").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("invalid bundle manifest path")
        if hashlib.sha256((bundle / path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"bundle checksum mismatch: {relative}")


def main(bundle):
    # Do not create evidence, signal processes or power off on an unidentified guest.
    if os.geteuid() != 0 or socket.gethostname() != "sugarkube-lifecycle-proof-v1":
        raise SystemExit("wrong guest or missing root: no action")
    if EVIDENCE.exists():
        raise SystemExit("one-shot evidence already exists: no replay")
    EVIDENCE.mkdir(mode=0o700)
    started = time.monotonic()
    uptime = float(Path("/proc/uptime").read_text().split()[0])
    overall_deadline = started + max(0, 1800 - uptime)
    result = {"passed": False, "boot_uptime_seconds": uptime, "source_bundle": str(bundle)}
    save("status.json", result)
    proc = None
    pgid = start_ticks = None
    preflight_passed = False
    try:
        if uptime > 300:
            raise RuntimeError("five-minute boot budget exceeded; no tests started")
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("requires Python 3.12")
        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            raise RuntimeError("requires cgroup v2 for independent probe-process cleanup evidence")
        if any(
            not shutil.which(x)
            for x in ("ip", "systemctl", "journalctl", "mount", "unshare", "dpkg-query")
        ):
            raise RuntimeError("missing native tool; do not install or shim")
        if fixtures() or Path("/var/lib/rancher/k3s").exists() or Path("/etc/rancher/k3s").exists():
            raise RuntimeError("existing fixture or K3s state; no cleanup ownership")
        links = json.loads(command("ip", "-j", "link", "show"))
        if [item["ifname"] for item in links] != ["lo"]:
            raise RuntimeError("unexpected NIC")
        for unit in (*UNITS, "k3s.service", "sugarkube-ethernet-recovery.timer"):
            if command("systemctl", "show", unit, "--property=LoadState") != "LoadState=not-found":
                raise RuntimeError(f"existing unit: {unit}")
        verify_bundle(bundle)
        save(
            "native-baseline.json",
            {
                "kernel": os.uname().release,
                "python": sys.version,
                "packages": command(
                    "dpkg-query", "-W", "python3", "systemd", "util-linux", "iproute2"
                ),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "links": links,
            },
        )
        original_state = baseline()
        save("dns-network-before.json", original_state)
        preflight_passed = True
        env = {**os.environ, **FLAGS, "PYTHONPATH": str(bundle / "deps")}
        env.pop("PYTHONOPTIMIZE", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        harness = bundle / "source/scripts/qualification/resolver_lifecycle.py"
        with (EVIDENCE / "harness.log").open("wb") as log:
            proc = subprocess.Popen(
                [sys.executable, str(harness), "--run-approved", str(EVIDENCE / "result.json")],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
            pgid = proc.pid
            leader = next(r for r in processes() if r["pid"] == proc.pid)
            start_ticks = leader["start_ticks"]
            save("owned-process-group.json", leader)
            test_deadline = min(started + 900, overall_deadline - 600)
            while proc.poll() is None and time.monotonic() < test_deadline:
                time.sleep(0.2)
            if proc.poll() is None:
                result["test_timeout"] = True
            else:
                result["returncode"] = proc.returncode
            log.flush()
            os.fsync(log.fileno())
    except BaseException as error:
        result["error"] = repr(error)
    finally:
        save("test-outcome.json", result)
        cleanup_deadline = min(time.monotonic() + 600, overall_deadline)
        errors = []
        if preflight_passed:
            try:
                remaining = owned(processes(), pgid, start_ticks) if pgid is not None else []
                save(
                    "pre-cleanup.json",
                    {
                        "processes": remaining,
                        "units": unit_evidence(cleanup_deadline),
                        "mounts": mount_evidence(),
                        "fixtures": [str(p) for p in fixtures()],
                    },
                )
                if remaining:
                    # TERM only the session/process group created above. No host-wide kills,
                    # SIGKILL, reboot or power-off escalation when termination fails.
                    os.killpg(pgid, signal.SIGTERM)
                    until = min(time.monotonic() + 120, cleanup_deadline)
                    while time.monotonic() < until:
                        if proc:
                            proc.poll()
                        if not owned(processes(), pgid, start_ticks):
                            break
                        time.sleep(0.2)
                    if owned(processes(), pgid, start_ticks):
                        errors.append("owned process group did not exit after TERM")
            except Exception as error:
                errors.append(f"process cleanup: {error!r}")
            # Always attempt each owned probe independently, including after test timeout.
            for unit in reversed(UNITS):
                try:
                    properties = unit_evidence(cleanup_deadline)[unit]
                    if not already_cleaned(properties):
                        command("systemctl", "--no-block", "stop", unit, deadline=cleanup_deadline)
                except Exception as error:
                    errors.append(f"{unit} stop: {error!r}")
            try:
                while time.monotonic() < cleanup_deadline:
                    units = unit_evidence(cleanup_deadline)
                    if all(
                        "MainPID=0" in value
                        and ("ActiveState=inactive" in value or "ActiveState=failed" in value)
                        for value in units.values()
                    ):
                        break
                    time.sleep(0.2)
                else:
                    raise TimeoutError("probe services did not stop")
                mounts = mount_evidence()
                if mounts:
                    errors.append("fixture mounts remain in a live process namespace")
                if any(probe_cgroup_processes().values()):
                    errors.append("owned probe cgroup processes remain")
                if not errors:
                    for unit in UNITS:
                        (Path("/run/systemd/system") / unit).unlink(missing_ok=True)
                    command("systemctl", "daemon-reload", deadline=cleanup_deadline)
                    for path in fixtures():
                        if path.is_symlink() or path.stat().st_uid != 0 or not path.is_dir():
                            raise RuntimeError(f"unexpected fixture identity: {path}")
                        shutil.rmtree(path)
                final_state = {
                    "processes": owned(processes(), pgid, start_ticks) if pgid is not None else [],
                    "units": unit_evidence(cleanup_deadline),
                    "mounts": mount_evidence(),
                    "fixtures": [str(p) for p in fixtures()],
                    "probe_cgroups": probe_cgroup_processes(),
                    "errors": errors,
                    "dns_network_after": baseline(),
                }
                if (
                    final_state["processes"]
                    or any(final_state["probe_cgroups"].values())
                    or final_state["mounts"]
                    or final_state["fixtures"]
                    or not all(already_cleaned(v) for v in final_state["units"].values())
                    or final_state["dns_network_after"] != original_state
                ):
                    errors.append("pre-shutdown cleanup/baseline verification failed")
                save("pre-shutdown-cleanup.json", final_state)
            except Exception as error:
                errors.append(f"service/fixture cleanup: {error!r}")
            for unit in UNITS:
                try:
                    journal = command(
                        "journalctl", "-b", "-u", unit, "--no-pager", deadline=cleanup_deadline
                    )
                    save(unit + ".journal.json", {"journal": journal})
                except Exception as error:
                    errors.append(f"{unit} journal: {error!r}")
        else:
            errors.append("preflight incomplete; no cleanup or shutdown ownership assumed")
        result["cleanup_errors"] = errors
        result["cleanup_passed"] = not errors
        try:
            harness_result = json.loads((EVIDENCE / "result.json").read_text())
            result["passed"] = (
                not errors
                and result.get("returncode") == 0
                and harness_result.get("passed") is True
            )
        except (OSError, ValueError):
            result["passed"] = False
        result["elapsed_seconds"] = time.monotonic() - started
        save("status.json", result)
        if not errors and time.monotonic() < overall_deadline:
            save("shutdown-intent.json", {"method": "systemctl poweroff", "fallback": "none"})
            save(
                "evidence-hashes.json",
                {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(EVIDENCE.iterdir())
                    if path.is_file()
                },
            )
            try:
                command("systemctl", "--no-block", "poweroff", deadline=overall_deadline)
            except Exception as error:
                save("shutdown-error.json", {"error": repr(error)})
        # Failed/uncertain cleanup leaves the guest running for owner inspection.
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-approved", type=Path, required=True, metavar="BUNDLE")
    args = parser.parse_args()
    raise SystemExit(main(args.run_approved.resolve(strict=True)))
