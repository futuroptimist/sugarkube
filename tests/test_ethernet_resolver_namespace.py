"""Opt-in mount integration. Uses only disposable paths in private child namespaces.

Requires an explicitly approved mount-capable disposable executor. Never changes
host DNS, network, services, or kernel policy; default CI collects but skips it.
"""

import json
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from test_ethernet_mdns_resolver import DNS, ENROLLMENT


def configure(root):
    DNS.STATE = root / "run/sugarkube-ethernet-dns"
    DNS.RESOLVED = root / "run/systemd/resolve"
    DNS.HOST_RESOLV = root / "etc/resolv.conf"


def child(root, mode):
    root = Path(root).resolve(strict=True)
    assert root.name.startswith("sugarkube-view-proof-")
    configure(root)
    assert all(
        " shared:" not in row and " master:" not in row
        for row in Path("/proc/self/mountinfo").read_text().splitlines()
    )
    e = {**ENROLLMENT, "resolver_view": DNS.resolved_layout()}
    bindings = (
        DNS.resolver_bindings(e)
        if mode == "directory"
        else [f"{DNS.STATE}/resolved/stub-resolv.conf:{DNS.RESOLVED}/stub-resolv.conf:norbind"]
    )
    for binding in bindings:
        source, target, flag = binding.split(":")
        assert flag == "norbind"
        subprocess.run(["mount", "--bind", source, target], check=True, timeout=10)
        subprocess.run(["mount", "-o", "remount,bind,ro", target], check=True, timeout=10)

    def sample():
        mounts = [
            row for row in Path("/proc/self/mountinfo").read_text().splitlines() if str(root) in row
        ]
        data = {
            "content": DNS.HOST_RESOLV.read_text(),
            "mounts": mounts,
            "namespace": os.readlink("/proc/self/ns/mnt"),
        }
        if mode == "directory":
            # Actual AF_UNIX connection follows the generated compatibility link.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(DNS.RESOLVED / "io.systemd.Resolve"))
                data["ipc"] = client.recv(1).hex()
            data["uplink"] = (DNS.RESOLVED / "resolv.conf").read_text()
            for target in (DNS.RESOLVED, DNS.STATE / "host-resolved"):
                try:
                    (target / "must-not-write").write_text("wrong")
                except OSError as error:
                    assert error.errno == 30  # EROFS, not merely discretionary permissions.
                else:
                    raise AssertionError("resolver mount is writable")
        print(json.dumps(data), flush=True)

    sample()
    for line in sys.stdin:
        if line.strip() == "sample":
            sample()
        elif line.strip() == "exit":
            return
        else:
            raise AssertionError("unsupported child command")


@pytest.mark.skipif(
    os.environ.get("SUGARKUBE_RUN_MOUNT_PROOF") != "1",
    reason="explicit disposable mount executor required",
)
@pytest.mark.parametrize("mode", ["file", "directory"])
def test_private_namespace_host_replacement_and_generated_publication(mode):
    import threading

    assert os.geteuid() == 0 and all(shutil.which(name) for name in ("unshare", "mount"))
    # Short pathname also fits Unix socket sockaddr_un limits.
    with tempfile.TemporaryDirectory(prefix="sugarkube-view-proof-", dir="/tmp") as td:
        root = Path(td)
        old = DNS.STATE, DNS.RESOLVED, DNS.HOST_RESOLV
        configure(root)
        try:
            for directory in (DNS.STATE, DNS.RESOLVED, DNS.HOST_RESOLV.parent):
                directory.mkdir(parents=True)
            DNS.HOST_RESOLV.symlink_to("../run/systemd/resolve/stub-resolv.conf")
            (DNS.RESOLVED / "stub-resolv.conf").write_text(
                "nameserver 127.0.0.53\nsearch original\n"
            )
            (DNS.RESOLVED / "resolv.conf").write_text("nameserver 192.0.2.53\nsearch original\n")
            e = {**ENROLLMENT, "resolver_view": DNS.resolved_layout()}
            DNS.initialize_view(e)
            stop = threading.Event()
            server_errors = []
            endpoint = DNS.RESOLVED / "io.systemd.Resolve"

            def serve_ipc(server, marker):
                server.settimeout(0.2)
                try:
                    while not stop.is_set():
                        try:
                            connection, _ = server.accept()
                        except socket.timeout:
                            continue
                        with connection:
                            connection.sendall(marker)
                except Exception as error:
                    server_errors.append(error)

            def start_ipc(marker):
                endpoint.unlink(missing_ok=True)
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    server.bind(str(endpoint))
                    server.listen(1)
                    thread = threading.Thread(target=serve_ipc, args=(server, marker))
                    thread.start()
                    return server, thread
                except Exception:
                    server.close()
                    raise

            server, thread = start_ipc(b"1")
            proc = None

            def receive():
                assert select.select([proc.stdout], [], [], 15)[0], "child timed out"
                line = proc.stdout.readline()
                assert line, "namespace unavailable or child failed; do not change privileges"
                return json.loads(line)

            try:
                proc = subprocess.Popen(
                    [
                        "unshare",
                        "--mount",
                        "--propagation",
                        "private",
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--child",
                        td,
                        mode,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                first = receive()
                assert first["namespace"] != os.readlink("/proc/self/ns/mnt")
                DNS.atomic(DNS.RESOLVED / "stub-resolv.conf", "nameserver 127.0.0.53\nsearch .\n")
                proc.stdin.write("sample\n")
                proc.stdin.flush()
                second = receive()
                stop.set()
                thread.join(3)
                server.close()
                assert not thread.is_alive()
                stop.clear()
                server, thread = start_ipc(b"2")
                DNS.atomic(DNS.RESOLVED / "resolv.conf", "nameserver 192.0.2.54\nsearch renewed\n")
                DNS.atomic(
                    DNS.STATE / "resolved/stub-resolv.conf",
                    "nameserver 127.0.0.55\nsearch renewed\n",
                )
                proc.stdin.write("sample\n")
                proc.stdin.flush()
                third = receive()
                assert first["content"] == "nameserver 127.0.0.55\nsearch original\n"
                if mode == "file":
                    assert not second["mounts"] and not third["mounts"]
                    assert (
                        second["content"] == third["content"] == "nameserver 127.0.0.53\nsearch .\n"
                    )
                else:
                    assert first["mounts"] == second["mounts"] == third["mounts"]
                    assert first["content"] == second["content"]
                    assert third["content"] == "nameserver 127.0.0.55\nsearch renewed\n"
                    assert first["ipc"] == second["ipc"] == b"1".hex()
                    assert third["ipc"] == b"2".hex()
                    assert third["uplink"] == "nameserver 192.0.2.54\nsearch renewed\n"
                proc.stdin.write("exit\n")
                proc.stdin.flush()
                assert proc.wait(timeout=10) == 0
            finally:
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)
                stop.set()
                thread.join(3)
                server.close()
                assert not thread.is_alive() and not server_errors
                assert td not in Path("/proc/self/mountinfo").read_text()
        finally:
            DNS.STATE, DNS.RESOLVED, DNS.HOST_RESOLV = old
    assert not root.exists()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("Use pytest in an explicitly approved disposable mount executor")
