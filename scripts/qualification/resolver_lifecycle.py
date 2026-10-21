#!/usr/bin/env python3
"""Review-only until explicitly approved: disposable, NIC-less guest lifecycle probe.

Never run on an existing lab member. See resolver-lifecycle.md for scope/substitutions.
"""

import argparse
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

if sys.flags.optimize:
    raise SystemExit("Qualification requires assertions enabled; unset PYTHONOPTIMIZE and -O.")

ROOT = Path("/run/sugarkube-qualification")
SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
FLAGS = {
    "SUGARKUBE_RUN_MOUNT_PROOF": "1",
    "SUGARKUBE_SKIP_PREINSTALL_TOOLS": "1",
    "SUGARKUBE_PREINSTALL_TOOL_SHIMS": "0",
    "SUGARKUBE_ALLOW_TOOL_SHIMS": "0",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
}
UNITS = ("sugarkube-qualification-runtime.service", "sugarkube-qualification-view.service")


def run(*args):
    return subprocess.check_output(args, text=True, timeout=20).strip()


def module():
    spec = importlib.util.spec_from_file_location(
        "resolver", REPO / "scripts/ethernet_mdns_resolver.py"
    )
    dns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dns)
    dns.STATE = ROOT / "run/sugarkube-ethernet-dns"
    dns.RESOLVED = ROOT / "run/systemd/resolve"
    dns.HOST_RESOLV = ROOT / "etc/resolv.conf"
    return dns


def snapshot():
    dns = module()
    data = {
        "namespace": os.readlink("/proc/self/ns/mnt"),
        "stub": dns.HOST_RESOLV.read_text(),
        "uplink": (dns.RESOLVED / "resolv.conf").read_text(),
        "mounts": [
            r for r in Path("/proc/self/mountinfo").read_text().splitlines() if str(ROOT) in r
        ],
        "ipc": {},
    }
    for name in ("io.systemd.Resolve", "io.systemd.Resolve.Monitor"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(dns.RESOLVED / name))
            data["ipc"][name] = client.recv(8).decode()
    for target in (dns.RESOLVED, dns.STATE / "host-resolved"):
        try:
            (target / "write-must-fail").write_text("failure")
        except OSError as error:
            assert error.errno == errno.EROFS
        else:
            raise AssertionError("writable resolver mount")
    return data


def probe():
    (ROOT / "ready").write_text(str(os.getpid()))
    seen = None
    while True:
        request = ROOT / "request"
        if request.exists() and (value := request.read_text()) != seen:
            data = snapshot()
            data["child"] = json.loads(run(sys.executable, str(SCRIPT), "--sample"))
            data["request"] = value
            temporary = ROOT / "response.new"
            temporary.write_text(json.dumps(data))
            temporary.replace(ROOT / "response")
            seen = value
        time.sleep(0.05)


def observe(number):
    (ROOT / "request").write_text(str(number))
    until = time.monotonic() + 10
    while time.monotonic() < until:
        path = ROOT / "response"
        if path.exists():
            data = json.loads(path.read_text())
            if data["request"] == str(number):
                child = data.pop("child")
                assert child == {k: v for k, v in data.items() if k != "request"}
                data["child_matches"] = True
                return data
        time.sleep(0.05)
    raise AssertionError("probe response timeout")


class IPC:
    def __init__(self, host, marker):
        self.stop = threading.Event()
        self.sockets, self.threads, self.errors = [], [], []
        try:
            for name in ("io.systemd.Resolve", "io.systemd.Resolve.Monitor"):
                path = host / name
                path.unlink(missing_ok=True)
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sockets.append(server)
                server.bind(str(path))
                server.listen(4)
                server.settimeout(0.1)

                def serve(server=server):
                    try:
                        while not self.stop.is_set():
                            try:
                                connection, _ = server.accept()
                            except socket.timeout:
                                continue
                            with connection:
                                connection.sendall(marker.encode())
                    except Exception as error:
                        self.errors.append(str(error))

                thread = threading.Thread(target=serve)
                thread.start()
                self.threads.append(thread)
        except Exception:
            self.close()
            raise

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(3)
        for server in self.sockets:
            server.close()
        assert not self.errors and not any(t.is_alive() for t in self.threads)


def refused(fn, diagnostic, records):
    try:
        fn()
    except ValueError as error:
        assert type(error).__name__ == "Unavailable" and str(error) == diagnostic
        records.append(diagnostic)
    else:
        raise AssertionError(f"unsafe acceptance: {diagnostic}")


def baseline():
    import hashlib

    files = {}
    for name in (
        "/etc/resolv.conf",
        "/run/systemd/resolve/stub-resolv.conf",
        "/run/systemd/resolve/resolv.conf",
    ):
        path = Path(name)
        files[name] = (
            None
            if not path.exists()
            else {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "inode": path.stat().st_ino,
                "device": path.stat().st_dev,
            }
        )
    return {"dns": files, "links": json.loads(run("ip", "-j", "link", "show"))}


def qualify(output):
    assert sys.version_info[:2] == (3, 12)
    assert not output.exists() and output.parent.is_dir()
    assert ROOT not in output.parents
    assert os.readlink("/etc/resolv.conf") == "../run/systemd/resolve/stub-resolv.conf"
    assert os.geteuid() == 0
    assert socket.gethostname() == "sugarkube-lifecycle-proof-v1"
    assert all(os.environ.get(k) == v for k, v in FLAGS.items())
    assert all(shutil.which(x) for x in ("systemctl", "mount", "unshare", "ip"))
    assert not ROOT.exists()
    assert not Path("/var/lib/rancher/k3s").exists()
    assert not Path("/etc/rancher/k3s").exists()
    for name in ("k3s.service", "sugarkube-ethernet-recovery.timer", *UNITS):
        assert run("systemctl", "show", name, "--property=LoadState") == "LoadState=not-found"
    before = baseline()
    assert [v["ifname"] for v in before["links"]] == ["lo"]
    result = {"namespace_cases": 0, "observations": [], "refusals": [], "before": before}
    dns = module()
    ipc = None
    installed = []
    try:
        # This qualification deliberately bypasses repository conftest, as well as disabling
        # its install/shim switches. No pytest plugins or implicit tool installers are used.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                "-q",
                "-o",
                "addopts=",
                str(REPO / "tests/test_ethernet_resolver_namespace.py"),
                "--junitxml=" + str(output.with_suffix(".xml")),
            ],
            check=True,
        )
        import xml.etree.ElementTree as ET

        report = ET.parse(output.with_suffix(".xml")).getroot()
        cases = report.findall(".//testcase")
        assert len(cases) == 2 and not report.findall(".//skipped")
        assert not report.findall(".//failure") and not report.findall(".//error")
        result["namespace_cases"] = 2
        dns.RESOLVED.mkdir(parents=True)
        dns.HOST_RESOLV.parent.mkdir()
        dns.HOST_RESOLV.symlink_to("../run/systemd/resolve/stub-resolv.conf")
        (dns.RESOLVED / "stub-resolv.conf").write_text("nameserver 127.0.0.53\nsearch original\n")
        (dns.RESOLVED / "resolv.conf").write_text("nameserver 192.0.2.53\nsearch original\n")
        enrollment = {
            "interface": "eth0",
            "members": [{"hostname": f"pi{i}.local"} for i in range(3)],
            "pod_resolv_source": "/run/systemd/resolve/resolv.conf",
            "resolver_view": dns.resolved_layout(),
        }
        generated = dns.service_files(enrollment)
        runtime_lines = [
            line
            for line in generated[dns.SERVICE].decode().splitlines()
            if line.startswith(
                ("RuntimeDirectory=", "RuntimeDirectoryMode=", "RuntimeDirectoryPreserve=")
            )
        ]
        assert len(runtime_lines) == 3
        runtime_lines = [
            line.replace(
                "RuntimeDirectory=sugarkube-ethernet-dns",
                "RuntimeDirectory=sugarkube-qualification/run/sugarkube-ethernet-dns",
            )
            for line in runtime_lines
        ]
        bind_lines = [
            line
            for line in generated[dns.HOOK].decode().splitlines()
            if line.startswith("BindReadOnlyPaths=")
        ]
        assert len(bind_lines) == 2
        # Only the runtime lifetime and mount directives are under test; no DNS daemon
        # or K3s ExecStart is launched. Exact generated sources are retained as evidence.
        result["generated"] = {
            str(p): b.decode() for p, b in generated.items() if p in (dns.SERVICE, dns.HOOK)
        }
        env = os.environ.get("PYTHONPATH", "")
        assert all(c not in env + str(SCRIPT) + sys.executable for c in ('"', "\n", "%", " "))
        units = [
            "[Service]\nType=simple\nTimeoutStopSec=5\nSendSIGKILL=no\n"
            + "\n".join(runtime_lines)
            + "\nExecStart=/usr/bin/sleep infinity\n",
            "[Service]\nType=simple\nTimeoutStopSec=5\nSendSIGKILL=no\n"
            + "\n".join(bind_lines)
            + f'\nEnvironment="PYTHONPATH={env}"\nExecStart={sys.executable} {SCRIPT} --probe\n',
        ]
        result["probe_units"] = dict(zip(UNITS, units))
        for name, text in zip(UNITS, units):
            path = Path("/run/systemd/system") / name
            assert not path.exists()
            path.write_text(text)
            installed.append(path)
        run("systemctl", "daemon-reload")
        run("systemctl", "start", UNITS[0])
        dns.initialize_view(enrollment)
        identity = dns.check_view(enrollment)
        ipc = IPC(dns.RESOLVED, "first")
        run("systemctl", "start", UNITS[1])
        for number, search in enumerate(("original", ".", "renewed")):
            dns.atomic(
                dns.RESOLVED / "stub-resolv.conf", f"nameserver 127.0.0.53\nsearch {search}\n"
            )
            if number:
                retained = observe(number * 2)
                assert retained["stub"] == result["observations"][-1]["stub"]
            dns.atomic(
                dns.STATE / "resolved/stub-resolv.conf", f"nameserver 127.0.0.55\nsearch {search}\n"
            )
            data = observe(number * 2 + 1)
            assert data["stub"] == f"nameserver 127.0.0.55\nsearch {search}\n"
            if result["observations"]:
                assert data["mounts"] == result["observations"][0]["mounts"]
            result["observations"].append(data)
        ipc.close()
        ipc = IPC(dns.RESOLVED, "second")
        dns.atomic(dns.RESOLVED / "resolv.conf", "nameserver 192.0.2.54\nsearch renewed\n")
        data = observe(7)
        assert set(data["ipc"].values()) == {"second"}
        assert data["uplink"] == "nameserver 192.0.2.54\nsearch renewed\n"
        result["observations"].append(data)
        run("systemctl", "stop", UNITS[0])
        assert dns.check_view(enrollment) == identity
        observe(8)  # Existing consumer survives producer stop.
        run("systemctl", "start", UNITS[0])
        dns.initialize_view(enrollment)
        assert dns.check_view(enrollment) == identity
        run("systemctl", "restart", UNITS[1])
        data = observe(9)
        pid = int(run("systemctl", "show", UNITS[1], "--property=MainPID", "--value"))
        dns.check_process_view(enrollment, pid, os.getpid(), data["stub"])
        run("systemctl", "stop", UNITS[1])
        # The probe unit alone is made writable; production text is retained above.
        installed[1].write_text(units[1].replace("BindReadOnlyPaths=", "BindPaths="))
        run("systemctl", "daemon-reload")
        # Remove the request so the probe waits rather than attempting its RO assertion.
        (ROOT / "request").unlink()
        (ROOT / "ready").unlink()
        run("systemctl", "start", UNITS[1])
        pid = int(run("systemctl", "show", UNITS[1], "--property=MainPID", "--value"))
        until = time.monotonic() + 10
        while not (ROOT / "ready").exists() and time.monotonic() < until:
            time.sleep(0.05)
        assert (ROOT / "ready").read_text() == str(pid)
        assert pid > 1 and Path(f"/proc/{pid}/mountinfo").is_file()
        assert run("systemctl", "is-active", UNITS[1]) == "active"
        refused(
            lambda: dns.check_process_view(enrollment, pid, os.getpid(), data["stub"]),
            "K3s resolver directory mount drifted",
            result["refusals"],
        )
        run("systemctl", "stop", UNITS[1])
        link = dns.STATE / "resolved/io.systemd.Resolve"
        link.unlink()
        link.symlink_to("wrong")
        refused(
            lambda: dns.check_view(enrollment),
            "resolver compatibility link changed",
            result["refusals"],
        )
        link.unlink()
        link.symlink_to(dns.view_links()[link.name])
        unknown = dns.RESOLVED / "unknown"
        unknown.touch()
        refused(
            lambda: dns.initialize_view(enrollment),
            "unsupported resolved directory entry",
            result["refusals"],
        )
        unknown.unlink()
        (dns.STATE / "view-identity.json").unlink()
        refused(
            lambda: dns.initialize_view(enrollment),
            "unfinished resolver view setup; explicit reconciliation required",
            result["refusals"],
        )
        assert not (dns.STATE / "view-identity.json").exists()
        dns.atomic(dns.STATE / "view-identity.json", json.dumps(identity))
        run("systemctl", "stop", UNITS[0])
        dns.STATE.rename(dns.STATE.with_name("retained-original-state"))
        shutil.copytree(dns.STATE.with_name("retained-original-state"), dns.STATE, symlinks=True)
        refused(
            lambda: dns.check_view(enrollment),
            "resolver directory identity changed; explicit migration required",
            result["refusals"],
        )
        result["passed"] = True
    except BaseException as error:
        result["error"] = repr(error)
        raise
    finally:
        # Independent cleanup attempts; preserve fixtures if any shutdown is uncertain.
        errors = []
        for path in reversed(installed):
            try:
                run("systemctl", "stop", path.name)
                assert run("systemctl", "show", path.name, "--property=MainPID") == "MainPID=0"
                assert run("systemctl", "show", path.name, "--property=ActiveState") in (
                    "ActiveState=inactive",
                    "ActiveState=failed",
                )
                path.unlink()
            except Exception as error:
                errors.append(f"{path.name}: {error!r}")
        if installed:
            try:
                run("systemctl", "daemon-reload")
            except Exception as error:
                errors.append(f"daemon-reload: {error!r}")
        if ipc:
            try:
                ipc.close()
            except Exception as error:
                errors.append(f"IPC cleanup: {error!r}")
        try:
            assert str(ROOT) not in Path("/proc/self/mountinfo").read_text()
            if not errors:
                if ROOT.exists():
                    shutil.rmtree(ROOT)
                assert not ROOT.exists()
            result["after"] = baseline()
            assert result["after"] == before
        except Exception as error:
            errors.append(f"fixture/baseline cleanup: {error!r}")
        result["cleanup_errors"] = errors
        result["cleanup_passed"] = not errors
        result["passed"] = result.get("passed", False) and not errors
        output.write_text(json.dumps(result, indent=2) + "\n")
        assert not errors, errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-approved", type=Path, metavar="RESULT_JSON")
    group.add_argument("--sample", action="store_true")
    group.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(snapshot()))
    elif args.probe:
        probe()
    else:

        def interrupted(signum, frame):
            raise InterruptedError(f"qualification interrupted by signal {signum}")

        signal.signal(signal.SIGTERM, interrupted)
        output = args.run_approved.resolve()
        try:
            qualify(output)
        except BaseException as error:
            # Capture preflight/import/early pytest failures too. Never overwrite a
            # detailed cleanup result or claim a failure before fixture setup passed.
            if output.parent.is_dir() and not output.exists():
                output.write_text(json.dumps({"passed": False, "early_error": repr(error)}) + "\n")
            raise
