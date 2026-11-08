#!/usr/bin/env python3
"""Explicit cold-host, original-database bootstrap before normal K3s startup.

This is a separately opted-in runtime. It does not install/enable units, stop
workloads, edit databases, bypass admission, or retry uncertain mutations.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import re
import shlex
import signal
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

source = Path(__file__).with_name("ethernet-quorum-recover.py")
if not source.exists():
    source = Path(__file__).with_name("ethernet_quorum_recover.py")
spec = importlib.util.spec_from_file_location("staged_quorum", source)
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)

RUNTIME = Path("/usr/local/libexec/sugarkube/ethernet_staged_recovery.py")
OPT_IN = Path("/etc/rancher/k3s/sugarkube-staged-recovery.json")
STATE = Path("/var/lib/sugarkube/ethernet-recovery")


def migration_guard(backend):
    guard = getattr(Q, "migration_start_guard", None)
    if guard is not None:
        # 'watch' is explicitly read-only: never consume a migration start permit.
        guard(Q.ENROLLMENT, backend, STATE, "watch")
    else:
        Q.require(
            not any(
                ((STATE / name).exists() or (STATE / name).is_symlink())
                for name in ("migration-intent.json", "migration-complete.json")
            ),
            "migration state requires a controller with the read-only migration guard",
        )


def hook():
    call = f"/usr/bin/python3 -I {RUNTIME}"
    return (
        "# Managed by ethernet_staged_recovery.py\n[Service]\n"
        "TimeoutStartSec=900\nTimeoutStopSec=75\nSendSIGKILL=no\n"
        f"ExecStartPre={call} pre-start\n"
        f"ExecStartPost={call} post-start\n"
    ).encode()


def completion_service():
    return (
        "# Managed by ethernet_staged_recovery.py\n[Unit]\n"
        "Description=Verify staged Ethernet recovery completion\nAfter=network-online.target\n"
        "[Service]\nType=oneshot\nUser=root\nUMask=0077\nTimeoutStartSec=185\n"
        f"ExecStart=/usr/bin/timeout 180s /usr/bin/python3 -I {RUNTIME} check-completion\n"
    ).encode()


def running_service():
    return (
        completion_service()
        .replace(b"check-completion", b"watch-running")
        .replace(
            b"Verify staged Ethernet recovery completion",
            b"Observe explicitly armed host reboot recovery",
        )
    )


def reboot_handoff(recovery, backend, opt_in):
    pending = STATE / "reboot-handoff.json"
    if opt_in.get("reboot_handoff") is None:
        Q.require(
            not pending.exists() and not pending.is_symlink(),
            "reboot handoff state exists without its explicit opt-in",
        )
        return None
    backend.config()  # Verify the extra module hash before importing it.
    module = Q.sibling("ethernet_reboot_handoff")
    return module.Handoff(Q, recovery, backend, opt_in, STATE)


def state_evidence(path):
    """Admit existing private-state evidence without following or replacing links."""
    if not (path.exists() or path.is_symlink()):
        return False
    Q.require(not path.is_symlink() and path.is_file(), "nonregular state evidence")
    Q.trusted_file(path)
    return True


class ReadUnavailable(Q.Stop):
    """Read-only transport unavailable; no mutation was repeated."""


class Backend(Q.Backend):
    def __init__(self, enrollment, opt_in):
        super().__init__(enrollment)
        self.opt_in = opt_in
        self.child = None
        self.write_failed = False
        self.transport = None

    def open_session(self, host, address, expected):
        # Keep the trusted module's exception identity with its sessions. The
        # original controller still owns the pinned, single-attempt connection.
        if self.transport is None:
            self.transport = Q.sibling("ethernet_etcd_grpc")
        return self.transport.Session(
            host,
            self.e["cluster_id"],
            expected["id"],
            self.e["etcd_tls"],
            lambda: self.connect_peer(address),
        )

    def request(self, host, route, payload):
        try:
            return super().request(host, route, payload)
        except Q.Stop as exc:
            if route in ("/v3/kv/txn", "/v3/cluster/member/update"):
                self.write_failed = True
            if (
                not self.write_failed
                and route in ("/v3/maintenance/status", "/v3/cluster/member/list", "/v3/kv/range")
                and self.transport is not None
                and isinstance(exc.__cause__, self.transport.Unavailable)
            ):
                raise ReadUnavailable("etcd read temporarily unavailable") from exc
            raise

    def address_node(self, host, node_name, patch=None, status=False):
        for attempt in range(3):
            try:
                return super().address_node(host, node_name, patch, status)
            except (Q.Stop, OSError) as exc:
                if patch is not None:
                    self.write_failed = True
                    raise
                # Only known connection loss/refusal/timeouts on GET are
                # retryable, plus explicit HTTP 503 startup unavailability.
                # TLS, other HTTP statuses, JSON and identity failures are not.
                cause = exc.__cause__ if isinstance(exc, Q.Stop) else exc
                unavailable = isinstance(cause, (ConnectionError, TimeoutError)) or (
                    isinstance(exc, Q.Stop) and str(exc) == "Node API HTTP 503; no retry"
                )
                if self.write_failed or not unavailable:
                    raise
                if attempt == 2:
                    raise ReadUnavailable("Node GET temporarily unavailable") from exc
                time.sleep(2)

    def retry_reads(self):
        Q.require(not self.write_failed, "uncertain mutation forbids transport retry")
        # Called only after an explicitly read-only proof failed. Keep pinned
        # locator addresses; a different address is a new incident, not a retry.
        self.close()
        self.connections = {}

    def recovery_hook_loaded(self):
        Q.trusted_file(Q.HOOK)
        Q.require(Q.HOOK.read_bytes() == hook(), "staged hook differs")
        unit = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=NeedDaemonReload,DropInPaths,ExecStartPre,ExecStartPost,"
                "TimeoutStartUSec,TimeoutStopUSec,SendSIGKILL",
            ]
        )
        properties = dict(line.split("=", 1) for line in unit.splitlines() if "=" in line)
        Q.require(
            properties.get("NeedDaemonReload") == "no"
            and str(Q.HOOK) in properties.get("DropInPaths", "").split()
            and properties.get("TimeoutStartUSec") == "15min"
            and properties.get("TimeoutStopUSec") == "1min 15s"
            and properties.get("SendSIGKILL") == "no",
            "staged hook not loaded",
        )
        for phase, key in [("pre-start", "ExecStartPre"), ("post-start", "ExecStartPost")]:
            expected = f"/usr/bin/python3 -I {RUNTIME} {phase}"
            commands = re.findall(
                r"argv\[\]=(.*?) ; ignore_errors=(yes|no) ;", properties.get(key, "")
            )
            Q.require(commands.count((expected, "no")) == 1, "staged command differs")
            Q.require(
                not any(str(Q.RUNTIME) in command for command, _ in commands),
                "old recovery hook still loaded",
            )
        for name, expected in self.opt_in["runtime_sha256"].items():
            path = Path(name)
            Q.trusted_file(path)
            Q.require(Q.digest(path.read_bytes()) == expected, "staged runtime identity changed")

    def config(self):
        migration_guard(self)
        super().config()
        if self.child is not None and self.child.poll() is None:
            self.process_executable(self.child.pid)
            dns = Q.sibling("ethernet_mdns_resolver")
            state = self.command(
                [
                    "/usr/bin/systemctl",
                    "show",
                    "sugarkube-ethernet-dns.service",
                    "--property=MainPID",
                ]
            )
            dns_pid = state.strip().removeprefix("MainPID=")
            Q.require(dns_pid.isdigit() and int(dns_pid) > 0, "resolver daemon not running")
            _, expected = dns.resolver_text((dns.STATE / "upstream-resolv.conf").read_text())
            Q.require(
                self.e.get("resolver_view") is not None,
                "staged bootstrap requires directory resolver view",
            )
            dns.check_process_view(self.e, str(self.child.pid), dns_pid, expected)

    def quiet(self):
        """Read-only fail-closed cold-host proof; never kill residual workloads."""
        unit = self.command(["/usr/bin/systemctl", "show", "k3s.service", "--property=MainPID"])
        Q.require(unit.strip() == "MainPID=0", "normal K3s main process still present")
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                comm = (entry / "comm").read_text().strip()
                cgroup = (entry / "cgroup").read_text()
                command = (entry / "cmdline").read_bytes().split(b"\0")[0].decode(errors="replace")
                executable = (entry / "exe").resolve().name
            except FileNotFoundError:
                continue
            Q.require(
                not any(word in cgroup for word in ("kubepods", "cri-containerd-")),
                "residual pod cgroup; cold/quiesced host required",
            )
            Q.require(
                not any(
                    name.startswith(("k3s", "containerd", "kubelet", "kube-proxy"))
                    or name == "etcd"
                    for name in (comm, Path(command).name, executable)
                ),
                "residual runtime process; cold/quiesced host required",
            )

    def process_executable(self, pid, allow_wrapper=False):
        actual = Path(f"/proc/{pid}/exe").resolve()
        expected = Path(self.opt_in["server_executable"])
        if allow_wrapper and actual == Path("/usr/local/bin/k3s"):
            return False
        Q.require(actual == expected, "K3s internal executable identity changed")
        return True

    def normal_running(self):
        unit = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=ActiveState,SubState,MainPID,InvocationID,NRestarts",
            ]
        )
        state = dict(line.split("=", 1) for line in unit.splitlines())
        Q.require(
            state["ActiveState"] in ("activating", "active")
            and state["SubState"] in ("start-post", "running")
            and int(state["MainPID"]) > 0,
            "normal K3s process not running",
        )
        proc = Path("/proc") / state["MainPID"]
        self.process_executable(state["MainPID"])
        cmdline = (proc / "cmdline").read_bytes()
        Q.require(b"--disable-agent" not in cmdline, "agentless process cannot complete handover")
        return state

    def service_context(self):
        unit = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=ControlPID,ControlGroup,InvocationID",
            ]
        )
        values = dict(line.split("=", 1) for line in unit.splitlines())
        groups = [
            line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
        ]
        Q.require(
            values["ControlPID"] == str(os.getpid())
            and values["ControlGroup"] in groups
            and values["ControlGroup"] != "/"
            and values["InvocationID"] == os.environ.get("INVOCATION_ID")
            and re.fullmatch("[0-9a-f]{32}", values["InvocationID"]),
            "staged lifecycle must run as the current k3s service control process",
        )

    def server_environment(self):
        unit = self.command(
            ["/usr/bin/systemctl", "show", "k3s.service", "--property=Environment,EnvironmentFiles"]
        )
        values = dict(line.split("=", 1) for line in unit.splitlines())
        assignments = shlex.split(values["Environment"])
        for filename in re.findall(
            r"(/[^ ;]+) \(ignore_errors=(?:yes|no)\)", values["EnvironmentFiles"]
        ):
            path = Path(filename)
            if path.exists():
                for line in path.read_text().splitlines():
                    if line.strip() and not line.lstrip().startswith(("#", ";")):
                        assignments.extend(shlex.split(line))
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root",
        }
        for assignment in assignments:
            key, separator, value = assignment.partition("=")
            Q.require(
                separator and re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", key),
                "unsupported service environment assignment",
            )
            env[key] = value
        for key in ("NOTIFY_SOCKET", "LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES", "INVOCATION_ID"):
            env.pop(key, None)
        return env

    def boot_id(self):
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        Q.require(
            re.fullmatch("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", value),
            "invalid kernel boot identity",
        )
        return value

    def running_network(self, ip, baseline):
        """Read-only old-or-current managed YAML proof before a host reboot."""
        self.config()
        local = next(m for m in self.e["members"] if m["id"] == self.e["local_member_id"])
        Q.require(
            self.address() == ip and self.resolve(local["hostname"]) == ip,
            "running Ethernet/mDNS address changed",
        )
        path = Path("/etc/rancher/k3s/config.yaml.d/20-sugarkube-network.yaml")
        Q.trusted_file(path)
        content = path.read_bytes()
        for candidate in (baseline, ip):
            expected = (
                f'# Managed by configure_k3s_node_ip.sh\nnode-ip: "{candidate}"\n'
                f'flannel-iface: "{self.e["interface"]}"\n'
            ).encode()
            if content == expected:
                return {"configured_ip": candidate, "network_sha256": Q.digest(content)}
        raise Q.Stop("running managed network YAML must exactly match old or current address")

    def reboot_admission(self):
        version = self.command(["/usr/bin/systemctl", "--version"]).splitlines()[0]
        Q.require(re.match(r"systemd 255(?: |$)", version), "reboot requires pinned systemd 255")
        state = dict(
            line.split("=", 1)
            for line in self.command(
                [
                    "/usr/bin/systemctl",
                    "show",
                    "k3s.service",
                    "--property=ActiveState,SubState,MainPID,ControlPID,Job,InvocationID,"
                    "NeedDaemonReload,KillMode,Delegate,Restart",
                ]
            ).splitlines()
        )
        Q.require(
            state["NeedDaemonReload"] == "no"
            and state["KillMode"] == "process"
            and state["Delegate"] == "yes"
            and state["ControlPID"] == "0"
            and state["Job"] in ("", "0"),
            "service job or unsupported lifecycle blocks reboot",
        )
        output = self.command(
            ["/usr/bin/systemctl", "list-jobs", "--no-legend", "--no-pager", "--plain", "--full"]
        )
        rows = [line.split() for line in output.splitlines() if line.strip()]
        if rows:
            Q.require(
                len(rows) == 1
                and len(rows[0]) == 4
                and rows[0][0].isdigit()
                and rows[0][1:] == ["sugarkube-ethernet-recovery.service", "start", "running"],
                "competing or unrecognized systemd jobs block reboot",
            )
            self.own_watcher_job(rows[0][0])
        if state["ActiveState"] == "active" and state["SubState"] == "running":
            Q.require(
                state["MainPID"].isdigit() and int(state["MainPID"]) > 0,
                "invalid normal server process",
            )
            self.process_executable(state["MainPID"])
            Q.require(
                re.fullmatch("[0-9a-f]{32}", state["InvocationID"]), "invalid service invocation"
            )
        else:
            Q.require(
                (state["ActiveState"], state["SubState"])
                in (("inactive", "dead"), ("failed", "failed"), ("activating", "auto-restart"))
                and state["MainPID"] == "0"
                and (state["SubState"] != "auto-restart" or state["Restart"] == "always"),
                "only running, stopped or idle automatic restart may request reboot",
            )
        return state

    def own_watcher_job(self, job_id):
        Q.trusted_file(Q.WATCH_SERVICE)
        Q.require(
            Q.WATCH_SERVICE.read_bytes() == running_service(), "running watcher artifact changed"
        )
        output = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "sugarkube-ethernet-recovery.service",
                "--property=Type,User,MainPID,ControlPID,ActiveState,SubState,Job,"
                "ControlGroup,InvocationID,NeedDaemonReload,DropInPaths,ExecStart",
            ]
        )
        state = dict(line.split("=", 1) for line in output.splitlines())
        invocation = os.environ.get("INVOCATION_ID")
        expected = f"/usr/bin/timeout 180s /usr/bin/python3 -I {RUNTIME} watch-running"
        commands = re.findall(r"argv\[\]=(.*?) ; ignore_errors=(yes|no) ;", state["ExecStart"])
        Q.require(
            state["Type"] == "oneshot"
            and state["User"] == "root"
            and state["ActiveState"] == "activating"
            and state["SubState"] == "start"
            and state["ControlPID"] == "0"
            and state["Job"] == job_id
            and state["NeedDaemonReload"] == "no"
            and not state["DropInPaths"]
            and state["InvocationID"] == invocation
            and re.fullmatch("[0-9a-f]{32}", invocation or "")
            and commands == [(expected, "no")],
            "current watcher job identity differs",
        )
        groups = [
            line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
        ]
        parent = str(os.getppid())
        Q.require(
            state["MainPID"] == parent
            and parent != "1"
            and state["ControlGroup"] in groups
            and state["ControlGroup"] != "/",
            "watcher timeout parent/cgroup differs",
        )
        proc = Path("/proc") / parent
        Q.require(
            (proc / "exe").resolve() == Path("/usr/bin/timeout").resolve()
            and (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            == [arg.encode() for arg in expected.split()],
            "watcher parent executable/argv differs",
        )
        Q.require(
            Path("/proc/self/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
            == [arg.encode() for arg in expected.split()[2:]],
            "watcher child argv differs",
        )

    def request_reboot(self):
        # systemd255 logind/reboot.target dispatch is asynchronous. This returns
        # only request acceptance, never proof of shutdown or a new boot.
        self.command(
            ["/usr/bin/systemctl", "--no-block", "--no-wall", "--check-inhibitors=yes", "reboot"]
        )

    def start(self, lease_fd):
        self.service_context()
        self.quiet()
        self.config()
        unit = self.command(["/usr/bin/systemctl", "show", "k3s.service", "--property=ExecStart"])
        match = re.search(r"argv\[\]=(.*?) ; ignore_errors=", unit)
        Q.require(match is not None, "unsupported original server command")
        argv = shlex.split(match[1])
        Q.require(argv[:2] == ["/usr/local/bin/k3s", "server"], "original server command required")
        # inventory() already verified the complete original argv/environment/YAML.
        # CLI override is ephemeral and used only by this supervised child.
        env = self.server_environment()
        self.child = subprocess.Popen(
            argv + ["--disable-agent=true"], env=env, pass_fds=(lease_fd,)
        )
        deadline = time.monotonic() + 30
        while not self.process_executable(self.child.pid, allow_wrapper=True):
            self.alive()
            Q.require(time.monotonic() < deadline, "K3s wrapper did not exec pinned server")
            time.sleep(0.1)
        return self.child.pid

    def alive(self):
        Q.require(
            self.child is not None and self.child.poll() is None,
            "bootstrap process exited; no automatic restart",
        )

    def stop(self):
        self.alive()
        self.child.send_signal(signal.SIGTERM)
        try:
            self.child.wait(timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise Q.Stop("bootstrap did not stop; normal startup forbidden") from exc
        Q.require(self.child.returncode == 0, "bootstrap did not exit cleanly")
        self.quiet()


class Recovery(Q.DualRecovery):
    """Address proof after original quorum and numeric peer repair, without Ready."""

    def prepare_node_address(self, ip, old):
        # The base method need not persist a journal if native controllers have
        # already converged locally. Retain its exact baseline only for this call.
        self.readback_baseline = (ip, old)
        try:
            return super().prepare_node_address(ip, old)
        finally:
            del self.readback_baseline

    def address_readback(self, ip):
        Q.require(not self.address_journal.is_symlink(), "symlink Node journal unsupported")
        record = (
            json.loads(self.address_journal.read_text())
            if self.address_journal.exists()
            else {"phase": "prepared", "old_ip": ip}
        )
        Q.require(
            record["phase"] in ("prepared", "annotation-confirmed", "status-confirmed", "verified")
            and not getattr(self.b, "write_failed", False),
            "uncertain Node mutation forbids readback retry",
        )
        baseline = getattr(self, "readback_baseline", (ip, record["old_ip"]))
        Q.require(baseline[0] == ip, "readback baseline address differs")
        old = baseline[1]
        for member in self.survivors:
            for attempt in range(3):
                node = self.b.address_node(
                    member["hostname"], self.local["hostname"].removesuffix(".local")
                )
                self.address_identity(node, self.local)
                annotation = node["metadata"]["annotations"].get("k3s.io/internal-ip")
                internal = [
                    a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"
                ]
                Q.require(
                    annotation in (old, ip) and internal in ([old], [ip]),
                    "unexpected Node address during readback",
                )
                if annotation == ip and internal == [ip]:
                    break
                Q.require(attempt < 2, "Node address readback has not converged")
                time.sleep(2)
        Q.require(self.local_guard() == ip, "address changed after Node reconciliation")

    def address_proof(self, ip, old):
        Q.require(self.local_guard() == ip, "address incident changed")
        _, members = self.prove_etcd(include_local=True)
        addresses = {m["id"]: self.b.resolve(m["hostname"]) for m in self.e["members"]}
        Q.require(len(set(addresses.values())) == 3, "duplicate discovered addresses")
        for member in self.e["members"]:
            Q.require(
                members[member["id"]]["peerURLs"] == Q.dual_urls(member, addresses[member["id"]]),
                "peer address repair pending",
            )
            Q.require(self.read_marker(member) == self.marker(member), "enrollment marker changed")
        node = self.b.address_node(self.host, self.local["hostname"].removesuffix(".local"))
        self.address_identity(node, self.local)
        annotation = node["metadata"]["annotations"].get("k3s.io/internal-ip")
        addresses = node["status"]["addresses"]
        internal = [a["address"] for a in addresses if a["type"] == "InternalIP"]
        Q.require(
            annotation in (old, ip) and len(internal) == 1 and internal[0] in (old, ip),
            "unexpected Node address",
        )
        for address in addresses:
            Q.require(
                set(address) == {"type", "address"}
                and (
                    address["type"] == "InternalIP"
                    or (
                        address["type"] in ("Hostname", "InternalDNS")
                        and address["address"]
                        in (self.local["hostname"], self.local["hostname"].removesuffix(".local"))
                    )
                ),
                "unsupported Node address shape",
            )
        return self.host, node


class Coordinator:
    def __init__(self, recovery, path, clock=time.monotonic, sleep=time.sleep):
        self.r, self.b, self.path = recovery, recovery.b, path
        self.clock, self.sleep = clock, sleep
        self.handoff = None
        Q.require(not path.is_symlink(), "symlink staged journal unsupported")
        self.record = json.loads(path.read_text()) if path.exists() else None
        if self.record:
            Q.require(re.fullmatch("[0-9a-f]{32}", self.record["token"]), "invalid staged token")
            Q.require(
                self.record["member_id"] == recovery.local["id"]
                and self.record["cluster_id"] == recovery.e["cluster_id"],
                "staged identity changed",
            )

    def save(self, phase, **values):
        self.record.update(values, phase=phase)
        Q.atomic_json(self.path, self.record)

    def wait(self, operation, deadline):
        while True:
            self.b.alive()
            if operation():
                return
            Q.require(self.clock() < deadline, "bootstrap deadline expired; preserve incident")
            self.sleep(2)

    def membership(self):
        incident = self.r.previous()
        if incident["phase"] in ("transport-pending", "waiting-for-lock"):
            # Only failed READ proofs can be polled. reconcile persists intent before
            # every write, so a mutation exception escapes and is never replayed.
            try:
                self.r.prove_transport(incident)
            except Q.Stop:
                self.b.retry_reads()
                return False
            if self.r.reconcile(incident) == "waiting-for-lock":
                return False
        Q.require(
            self.r.previous()["phase"] == "completion-pending", "membership outcome unresolved"
        )
        try:
            _, members = self.r.prove_etcd(include_local=True)
            return all(
                members[m["id"]]["peerURLs"] == Q.dual_urls(m, self.b.resolve(m["hostname"]))
                for m in self.r.e["members"]
            )
        except Q.Stop:
            self.b.retry_reads()
            return False

    def api(self):
        # Every original API must serve the same enrolled Node before any write.
        # An identity error is never treated as API startup delay.
        for member in self.r.e["members"]:
            try:
                node = self.b.address_node(
                    member["hostname"], self.r.local["hostname"].removesuffix(".local")
                )
            except ReadUnavailable:
                return False
            self.r.address_identity(node, self.r.local)
        try:
            self.r.address_proof(self.record["ip"], self.record["old_ip"])
        except ReadUnavailable:
            self.b.retry_reads()
            return False
        return True

    def handover(self):
        # Reuse the membership lock only after all membership mutations completed.
        self.save("handover-acquire-intent")
        result = self.r.transaction(self.record["token"])
        if result.get("succeeded") is False:
            self.save("waiting-for-handover")
            return False
        Q.require(result.get("succeeded") is True, "handover acquisition outcome unknown")
        self.save("handover-owned")
        self.r.owned(self.record["token"])
        return True

    def pre_start(self, lease_fd):
        state_evidence(self.r.address_journal)
        previous = self.r.previous()
        baseline = (
            previous["ip"]
            if previous and previous["phase"] == "complete"
            else self.r.e["local_ipv4"]
        )
        ip = self.r.local_guard()
        if self.record:
            Q.require(
                self.record["phase"] == "normal" and previous and previous["phase"] == "complete",
                "unfinished staged incident; no replay",
            )
            address = json.loads(self.r.address_journal.read_text())
            Q.require(
                address["phase"] == "verified"
                and address["ip"] == self.record["ip"]
                and previous["ip"] == self.record["ip"],
                "prior incident evidence differs",
            )
            if ip == baseline:
                # Ordinary simultaneous cold boot must not need any live peer API.
                return self.r.pre_start()
            archive = self.path.parent / ("staged-archive-" + self.record["token"] + ".json")
            bundle = dict(staged=self.record, membership=previous, address=address)
            if state_evidence(archive):
                Q.require(json.loads(archive.read_text()) == bundle, "archive conflicts")
            else:
                Q.atomic_json(archive, bundle)
            self.record = None
        if ip == baseline:
            return self.r.pre_start()
        Q.require(self.r.e.get("armed") is True, "fully armed enrollment required")
        Q.require(not previous or previous["phase"] == "complete", "existing membership incident")
        if self.r.address_journal.exists():
            address = json.loads(self.r.address_journal.read_text())
            Q.require(
                address["phase"] == "verified" and address["ip"] == baseline,
                "existing address journal requires review",
            )
        self.b.quiet()
        self.b.stable_address(ip)
        self.record = dict(
            member_id=self.r.local["id"],
            cluster_id=self.r.e["cluster_id"],
            ip=ip,
            old_ip=baseline,
            membership_id=uuid.uuid4().hex,
            **{"token": uuid.uuid4().hex},
        )
        self.save("bootstrap-start-intent")
        if self.handoff is not None:
            self.handoff.bind_staged(self.record)
        pid = self.b.start(lease_fd)
        self.save("bootstrap-running", pid=pid)
        incident = dict(
            **{"token": self.record["membership_id"]},
            phase="transport-pending",
            created_at=time.time(),
            kind="recovery",
            transport="staged-bootstrap",
            ip=ip,
            member_id=self.r.local["id"],
            cluster_id=self.r.e["cluster_id"],
            old_peer_urls=Q.dual_urls(self.r.local, baseline),
            mutation_dispatched=False,
        )
        Q.atomic_json(self.r.path, incident)
        deadline = self.clock() + 600
        self.wait(self.membership, deadline)
        self.wait(self.api, deadline)
        # Own the global turn before any Node mutation as well as process stop.
        # Otherwise another member can stop between this member's patch and its
        # required all-voter readback, producing an avoidable unknown outcome.
        self.save("waiting-for-handover")
        self.wait(self.handover, deadline)
        self.r.prepare_node_address(ip, baseline)
        self.save("addresses-verified-owned")
        self.r.address_proof(ip, baseline)
        self.r.address_readback(ip)
        self.save("bootstrap-stop-intent")
        self.b.stop()
        self.save("bootstrap-stopped")
        # No local endpoint remains. Both original survivors must still prove
        # authenticated consensus, identity, current peer URLs and Node readback.
        proof = Q.Recovery(self.r.e, self.b, self.r.path)
        current, members = proof.prove_etcd()
        Q.require(
            current == ip
            and members[self.r.local["id"]]["peerURLs"] == Q.dual_urls(self.r.local, ip),
            "handover identity or address changed",
        )
        proof.owned(self.record["token"])
        self.r.address_readback(ip)
        self.b.quiet()
        self.save("normal-start-intent", normal_start_at=time.time())
        return "normal-start-authorized"

    def normal_proof(self):
        Q.require(self.r.local_guard() == self.record["ip"], "address changed during normal start")
        self.r.prove_etcd(include_local=True)
        self.r.address_readback(self.record["ip"])
        node = self.b.address_node(self.r.host, self.r.local["hostname"].removesuffix(".local"))
        self.r.address_identity(node, self.r.local)
        Q.require(
            any(
                c.get("type") == "Ready"
                and c.get("status") == "True"
                and datetime.fromisoformat(
                    c["lastHeartbeatTime"].replace("Z", "+00:00")
                ).timestamp()
                >= self.record["normal_start_at"]
                for c in node["status"].get("conditions", [])
            ),
            "normal Node not Ready",
        )
        self.b.normal_running()

    def post_start(self):
        if not self.record:
            return self.r.post_start()
        Q.require(
            self.record["phase"] in ("normal-start-intent", "normal"),
            "staged phase blocks post-start",
        )
        if self.record["phase"] == "normal-start-intent":
            deadline = self.clock() + 120
            while True:
                try:
                    self.normal_proof()
                    break
                except Q.Stop:
                    self.b.retry_reads()
                    Q.require(
                        self.clock() < deadline,
                        "normal startup proof timed out; handover stays owned",
                    )
                    self.sleep(2)
            self.r.owned(self.record["token"])
            self.save("handover-release-intent")
            result = self.r.transaction(self.record["token"], release=True)
            Q.require(result.get("succeeded") is True, "handover release outcome unknown")
            self.save("normal")
        # Full cluster/workload readiness can legitimately await the other two
        # normal-agent handovers. Never fail the successful service start for it.
        try:
            return self.r.post_start()
        except Q.Stop:
            return "completion-pending"


def load_opt_in():
    Q.trusted_file(OPT_IN)
    opt = json.loads(OPT_IN.read_text())
    Q.require(isinstance(opt, dict), "invalid staged opt-in mapping")
    Q.require(
        type(opt.get("schema_version")) is int
        and opt["schema_version"] == 1
        and opt.get("cold_original_database_bootstrap") is True,
        "explicit staged bootstrap opt-in required",
    )
    Q.trusted_file(Q.ENROLLMENT)
    Q.require(Q.digest(Q.ENROLLMENT.read_bytes()) == opt["enrollment_sha256"], "enrollment changed")
    Q.require(
        re.fullmatch(r"/var/lib/rancher/k3s/data/[0-9a-f]{64}/bin/k3s", opt["server_executable"]),
        "canonical standard extracted K3s executable required",
    )
    expected_runtimes = {
        str(RUNTIME),
        str(Q.RUNTIME),
        "/usr/local/bin/k3s",
        str(Q.TRANSPORT),
        str(Q.DESCRIPTOR),
        str(Q.WAL_RUNTIME),
        str(RUNTIME.with_name("ethernet_mdns_resolver.py")),
        opt["server_executable"],
    }
    if opt.get("reboot_handoff") is not None:
        Q.require(isinstance(opt["reboot_handoff"], dict), "invalid reboot opt-in structure")
        Q.require(
            type(opt["reboot_handoff"].get("schema_version")) is int
            and type(opt["reboot_handoff"].get("systemd_major")) is int
            and opt["reboot_handoff"].get("whole_host_reboot") is True
            and opt["reboot_handoff"]
            == {
                "schema_version": 1,
                "whole_host_reboot": True,
                "systemd_major": 255,
            },
            "explicit whole-host reboot opt-in required",
        )
        expected_runtimes.update(
            {
                str(RUNTIME.with_name("ethernet_reboot_handoff.py")),
                "/usr/bin/systemctl",
                "/usr/bin/timeout",
            }
        )
    Q.require(
        isinstance(opt["runtime_sha256"], dict) and set(opt["runtime_sha256"]) == expected_runtimes,
        "exact staged and original runtimes must be pinned",
    )
    Q.require(
        all(re.fullmatch("[0-9a-f]{64}", value) for value in opt["runtime_sha256"].values()),
        "invalid runtime fingerprint",
    )
    e = json.loads(Q.ENROLLMENT.read_text())
    Q.validate_enrollment(e)
    Q.require(
        e["schema_version"] == 2 and e.get("armed") is True, "armed version 2 enrollment required"
    )
    Q.require(e.get("resolver_view") is not None, "directory resolver enrollment required")
    return e, opt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=[
            "hook",
            "completion-service",
            "running-service",
            "pre-start",
            "post-start",
            "check-completion",
            "watch-running",
        ],
    )
    args = parser.parse_args()
    if args.phase in ("hook", "completion-service", "running-service"):
        artifact = {
            "hook": hook,
            "completion-service": completion_service,
            "running-service": running_service,
        }[args.phase]()
        print(artifact.decode(), end="")
        return 0
    b = coordinator = None

    def interrupted(signum, frame):
        raise Q.Stop("startup interrupted; explicit incident review required")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        Q.require(os.geteuid() == 0, "root required")
        e, opt = load_opt_in()
        Q.private_state(STATE)
        b = Backend(e, opt)
        with (STATE / "lock").open("a") as lock, (STATE / "bootstrap.lock").open("a") as lease:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = Recovery(e, b, STATE / "incident.json")
            coordinator = Coordinator(r, STATE / "staged.json")
            migration_guard(b)
            handoff = reboot_handoff(r, b, opt)
            coordinator.handoff = handoff
            if args.phase in ("pre-start", "post-start"):
                b.service_context()
            if args.phase == "pre-start":
                if handoff is not None:
                    handoff.before_start()
                result = coordinator.pre_start(lease.fileno())
            elif args.phase == "post-start":
                result = coordinator.post_start()
            elif args.phase == "watch-running":
                Q.require(handoff is not None, "whole-host reboot opt-in required")
                result = handoff.watch()
            else:
                Q.require(
                    coordinator.record is None or coordinator.record["phase"] == "normal",
                    "unfinished staged lifecycle; no automatic replay",
                )
                b.config()
                previous = r.previous()
                baseline = (
                    previous["ip"]
                    if previous and previous["phase"] == "complete"
                    else e["local_ipv4"]
                )
                if coordinator.record is not None:
                    baseline = coordinator.record["ip"]
                Q.require(
                    b.address() == baseline,
                    "running address change requires cold/quiesced recovery; no automatic stop",
                )
                result = r.post_start()
        print(result)
        return 0
    except (
        RuntimeError,
        AttributeError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Staged recovery blocked: {exc}. Preserve all journals; no automatic replay.")
        if b is not None and b.child is not None and b.child.poll() is None:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                coordinator.save("cleanup-stop-intent", failed_phase=coordinator.record["phase"])
                b.stop()
                coordinator.save("cleanup-stopped")
            except (Q.Stop, OSError):
                print("Bootstrap cleanup unconfirmed; normal startup remains forbidden.")
        return 2
    finally:
        if b is not None:
            b.close()


if __name__ == "__main__":
    raise SystemExit(main())
