#!/usr/bin/env python3
"""Opt-in, fail-closed recovery of one enrolled etcd member before K3s starts.

No reset, membership add/remove or database edit exists here. Version 2 can
conditionally reconcile its original Node address through two healthy survivors.
A watcher may queue one local restart after authenticated recovery; an unfinished
incident blocks replay. Enrollment and qualification are explicit operator steps.
The program installs inactive units only when explicitly asked to enroll.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import yaml

KEY = "/sugarkube/ethernet-recovery/incident"
RUNTIME = Path("/usr/local/libexec/sugarkube/ethernet-quorum-recover.py")
HOOK = Path("/etc/systemd/system/k3s.service.d/30-sugarkube-quorum-recovery.conf")
NETWORK_HOOK = "/etc/systemd/system/k3s.service.d/20-sugarkube-network.conf"
WATCH_SERVICE = Path("/etc/systemd/system/sugarkube-ethernet-recovery.service")
WATCH_TIMER = Path("/etc/systemd/system/sugarkube-ethernet-recovery.timer")
TRANSPORT = RUNTIME.with_name("ethernet_etcd_grpc.py")
DESCRIPTOR = RUNTIME.with_name("ethernet-etcd.desc")
WAL_RUNTIME = RUNTIME.with_name("ethernet_wal_identity.py")
DNS_HOOK = "/etc/systemd/system/k3s.service.d/25-sugarkube-resolver.conf"
ENROLLMENT = Path("/etc/rancher/k3s/sugarkube-recovery.json")
VERSIONS = {"v1.35.4+k3s1", "v1.34.5+k3s1"}


class Stop(RuntimeError):
    """Preserve state and require operator intervention."""


def require(condition, message):
    if not condition:
        raise Stop(message)


def encode(value):
    return base64.b64encode(value.encode()).decode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sibling(name):
    source = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("sugarkube_" + name, source)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        raise Stop("required recovery dependency unavailable") from exc
    return module


def dual_urls(member, address):
    address = str(ipaddress.IPv4Address(address))
    return [f"https://{address}:2380", f"https://{member['hostname']}:2380"]


def recovery_hook():
    invocation = f"/usr/bin/python3 -I {RUNTIME}"
    return (
        "# Managed by ethernet_quorum_recover.py\n[Service]\n"
        f"ExecStartPre=/usr/bin/timeout 180s {invocation} pre-start --enrollment {ENROLLMENT}\n"
        f"ExecStartPost=-/usr/bin/timeout 60s {invocation} post-start --enrollment {ENROLLMENT}\n"
    ).encode()


def atomic_json(path, value):
    atomic_write(path, json.dumps(value, sort_keys=True).encode())


def atomic_write(path, content):
    """Persist before side effects; fsync both the file and containing directory."""
    fd, temporary = tempfile.mkstemp(prefix=".incident-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_enrollment(e):
    require(
        type(e["schema_version"]) is int and e["schema_version"] in (1, 2), "unsupported enrollment"
    )
    require(e["k3s_version"] in VERSIONS, "unqualified K3s version")
    require(re.fullmatch(r"[a-zA-Z0-9_.:-]+", e["interface"]), "invalid interface")
    require(not e["interface"].startswith("wl"), "Ethernet only")
    require(len(e["members"]) == 3, "exactly three enrolled voters required")
    ids, hosts, names = set(), set(), set()
    for member in e["members"]:
        require(re.fullmatch(r"[1-9][0-9]*", member["id"]), "decimal member ID required")
        require(int(member["id"]) < 2**64, "member ID exceeds uint64")
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.local", member["hostname"]), "invalid hostname")
        require(member["name"] and member["node_uid"], "member and Node identity required")
        ids.add(member["id"])
        hosts.add(member["hostname"])
        names.add(member["name"])
    require(len(ids) == len(hosts) == len(names) == 3, "duplicate enrollment identity")
    require(e["local_member_id"] in ids, "local member not enrolled")
    require(re.fullmatch(r"[1-9][0-9]*", e["cluster_id"]), "decimal cluster ID required")
    require(int(e["cluster_id"]) < 2**64, "cluster ID exceeds uint64")
    require(e["verified_backup"] is True, "operator-verified recovery backup required")
    ipaddress.IPv4Address(e["local_ipv4"])
    require(e["files"], "effective configuration files must be enrolled")
    if e["schema_version"] == 2:
        checks = e.get("completion_https_urls", [])
        require(
            isinstance(checks, list) and 1 <= len(checks) <= 8,
            "explicit application HTTPS completion checks required",
        )
        for value in checks:
            url = urlsplit(value)
            require(
                url.scheme == "https"
                and url.hostname
                and "." in url.hostname
                and "@" not in url.netloc
                and not url.query
                and not url.fragment
                and url.port not in (2379, 2380, 2381, 2382, 6443, 6444),
                "application completion URL must use HTTPS without credentials "
                "or control-plane ports",
            )
            try:
                ipaddress.ip_address(url.hostname)
            except ValueError:
                pass
            else:
                raise Stop("completion URL must use a stable DNS hostname")
    for path, expected in e["files"].items():
        require(
            Path(path).is_absolute()
            and (expected is None or re.fullmatch(r"[0-9a-f]{64}", expected)),
            "invalid configuration fingerprint",
        )


class Backend:
    """Bounded, authenticated commands. Never print command output or credentials."""

    def __init__(self, enrollment):
        self.e = enrollment
        self.enrolling = False
        self.preparing = False
        self.connections = {}
        self.locators = {}

    def command(self, argv, input_text=None):
        # Do not inherit ETCDCTL_*, KUBECONFIG or other endpoint/TLS overrides.
        env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "ETCDCTL_API": "3",
        }
        try:
            return subprocess.run(
                argv,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=12,
                check=True,
                env=env,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise Stop("bounded authenticated command failed; incident remains latched") from exc

    def startup_failure(self, since):
        """Return only an allowlisted signature, never arbitrary journal content."""
        output = self.command(
            [
                "/usr/bin/journalctl",
                "-u",
                "k3s.service",
                "--no-pager",
                "-n",
                "200",
                "-o",
                "json",
                f"--since=@{int(since)}",
            ]
        )
        for line in output.splitlines():
            entry = json.loads(line)
            message = entry.get("MESSAGE", "")
            if (
                "failed to start networking" in message
                and "failed to find interface with specified node ip" in message.lower()
            ):
                return {
                    "cause": "network-policy-node-ip-interface-mismatch",
                    "timestamp_us": entry.get("__REALTIME_TIMESTAMP"),
                    "invocation_id": entry.get("_SYSTEMD_INVOCATION_ID"),
                }
        return None

    def connect_peer(self, address, port=2379):
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            raw.settimeout(5)
            raw.setsockopt(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.e["interface"].encode() + b"\0"
            )
            raw.bind((self.address(), 0))
            raw.connect((address, port))
            return raw
        except Exception:
            raw.close()
            raise

    def open_session(self, host, address, expected):
        # -I intentionally excludes the script directory from sys.path. Load only
        # this installed sibling, not a module selected from the environment.
        module = sibling("ethernet_etcd_grpc")
        return module.Session(
            host,
            self.e["cluster_id"],
            expected["id"],
            self.e["etcd_tls"],
            lambda: self.connect_peer(address),
        )

    def request(self, host, route, payload):
        """One pinned gRPC session per voter; any failure forbids reconnect/replay."""
        expected = next(m for m in self.e["members"] if m["hostname"] == host)
        try:
            if host not in self.connections:
                # Latch even failed resolution/handshake; do not silently retry it.
                self.connections[host] = None
                address = self.resolve(host)
                self.connections[host] = self.open_session(host, address, expected)
            connection = self.connections[host]
            require(connection is not None, "session failed; no automatic reconnect")
            return connection.request(route, payload)
        except Exception as exc:
            connection = self.connections.get(host)
            if connection is not None:
                connection.close()
            self.connections[host] = None
            raise Stop(
                "authenticated gRPC failed; outcome may be unknown; no automatic reconnect"
            ) from exc

    def close(self):
        for host, connection in self.connections.items():
            if connection is not None:
                connection.close()
            self.connections[host] = None

    def etcd(self, host, *args, input_text=None):
        if args == ("member", "list"):
            return self.request(host, "/v3/cluster/member/list", {"linearizable": True})
        if args[:2] == ("member", "update"):
            return self.request(
                host,
                "/v3/cluster/member/update",
                {
                    "ID": str(int(args[2], 16)),
                    "peerURLs": args[3].removeprefix("--peer-urls=").split(","),
                },
            )
        if args == ("endpoint", "status"):
            return [{"Status": self.request(host, "/v3/maintenance/status", {})}]
        if args == ("endpoint", "health"):
            # A linearizable read proves quorum and endpoint identity in one response.
            self.request(
                host,
                "/v3/kv/range",
                {"key": encode(KEY + "/health"), "serializable": False, "count_only": True},
            )
            return [{"health": True}]
        keys = {KEY} | {KEY + "/enrollment/" + m["id"] for m in self.e["members"]}
        if len(args) == 2 and args[0] == "get" and args[1] in keys:
            return self.request(
                host, "/v3/kv/range", {"key": encode(args[1]), "serializable": False}
            )
        require(args == ("txn",), "unsupported recovery operation")
        return self.request(host, "/v3/kv/txn", json.loads(input_text))

    def inventory(self):
        """Snapshot the supported standard layout; refuse override ambiguity."""
        e = self.e
        require(
            Path("/var/lib/rancher/k3s/server/db/etcd/member").is_dir(),
            "existing standard-layout etcd database required",
        )
        version = self.command(["/usr/local/bin/k3s", "--version"]).splitlines()[0]
        require(version.split()[2] == e["k3s_version"], "K3s version changed")
        unit = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=ExecStart,Environment,EnvironmentFiles,DropInPaths",
            ]
        )
        command = re.search(r"^ExecStart=.*?argv\[\]=(.*?) ; ignore_errors=", unit, re.M)
        require(command is not None, "unsupported systemd ExecStart format")
        arguments = shlex.split(command[1])
        require(
            arguments[:2] == ["/usr/local/bin/k3s", "server"], "standard server command required"
        )
        forbidden = {
            "--node-ip",
            "--flannel-iface",
            "--config",
            "-c",
            "--data-dir",
            "-d",
            "--etcd-arg",
            "--node-external-ip",
            "--advertise-address",
            "--cluster-reset",
            "--cluster-reset-restore-path",
            "--datastore-endpoint",
            "--disable-etcd",
            "--disable-agent",
        }
        if e["schema_version"] == 2:
            forbidden.add("--resolv-conf")
        require(
            not any(arg.split("=", 1)[0] in forbidden for arg in arguments),
            "unsupported K3s CLI override/reset",
        )
        require(
            not any(arg.startswith("-") and not arg.startswith("--") for arg in arguments),
            "short K3s options require migration to the supported layout",
        )
        for index, arg in enumerate(arguments):
            if arg == "--server":
                self.join_target(arguments[index + 1])
            elif arg.startswith("--server="):
                self.join_target(arg.split("=", 1)[1])
        static = []
        for line in unit.splitlines():
            if line.startswith("ExecStart="):
                continue
            if line.startswith("DropInPaths="):
                paths = line.split("=", 1)[1].split()
                require(
                    set(paths)
                    <= {str(HOOK), NETWORK_HOOK}
                    | ({DNS_HOOK} if e["schema_version"] == 2 else set()),
                    "custom drop-ins require operator migration",
                )
                line = "DropInPaths=" + " ".join(
                    p for p in paths if p not in (str(HOOK), NETWORK_HOOK, DNS_HOOK)
                )
            static.append(line)
        effective = "\n".join(sorted(static) + ["argv=" + command[1]])
        envfiles = re.search(r"^EnvironmentFiles=(.*)$", unit, re.M)
        require(envfiles is not None, "missing systemd environment file evidence")
        envpaths = re.findall(r"(/[^ ;]+) \(ignore_errors=(?:yes|no)\)", envfiles[1])
        require(
            " ".join(f"{p} (ignore_errors=yes)" for p in envpaths) == envfiles[1]
            or not envfiles[1],
            "unsupported environment file layout",
        )
        environment = re.search(r"^Environment=(.*)$", unit, re.M)
        require(environment is not None, "missing environment evidence")
        assignments = shlex.split(environment[1])
        for filename in envpaths:
            path = Path(filename)
            if path.exists():
                for line in path.read_text().splitlines():
                    if line.strip() and not line.lstrip().startswith(("#", ";")):
                        assignments.extend(shlex.split(line))
        for assignment in assignments:
            key, _, value = assignment.partition("=")
            forbidden_env = {
                "K3S_" + item[2:].replace("-", "_").upper()
                for item in forbidden
                if item.startswith("--")
            }
            require(
                key not in forbidden_env | {"K3S_CONFIG_FILE"}, "unsupported environment override"
            )
            if key == "K3S_URL":
                self.join_target(value)
        fragments = sorted(
            str(p)
            for p in Path("/etc/rancher/k3s/config.yaml.d").glob("*.yaml")
            if p.name != "20-sugarkube-network.yaml"
            and not (e["schema_version"] == 2 and p.name == "21-sugarkube-resolver.yaml")
        )
        config_files = list(fragments)
        base = Path("/etc/rancher/k3s/config.yaml")
        if base.exists():
            config_files.append(str(base))
        require(not Path("/etc/rancher/k3s/config.yml").exists(), "unsupported alternate config")
        for filename in config_files:
            content = yaml.safe_load(Path(filename).read_text()) or {}
            require(isinstance(content, dict), "unsupported YAML configuration")
            for key, value in content.items():
                key = str(key).rstrip("+")
                require("--" + key not in forbidden, "network/reset override outside managed YAML")
                if key == "server":
                    self.join_target(value)
        required = set(
            config_files
            + envpaths
            + [
                e["kubeconfig"],
                *e["etcd_tls"].values(),
                "/etc/rancher/k3s/sugarkube-network-prestart.sh",
                NETWORK_HOOK,
            ]
        )
        if e["schema_version"] == 2 and not self.preparing:
            dns = sibling("ethernet_mdns_resolver")
            required.update(str(path) for path in dns.service_files(e))
            required.add("/var/lib/rancher/k3s/server/tls/etcd/peer-ca.crt")
        files = {}
        for filename in required:
            path = Path(filename)
            # Missing optional environment files must also be tracked against later creation.
            require(not path.is_symlink(), "symlink configuration unsupported")
            if path.exists():
                trusted_file(path)
            if filename in (e["etcd_tls"]["cert"], e["etcd_tls"]["key"]):
                require(path.is_file(), "missing client credential")
                continue  # K3s renews leaf credentials; TLS validates them when used.
            if filename == e["kubeconfig"]:
                config = yaml.safe_load(path.read_text())
                require(
                    len(config["clusters"]) == len(config["contexts"]) == 1,
                    "one explicit API trust context required",
                )
                cluster = config["clusters"][0]
                context = config["contexts"][0]
                require(
                    set(cluster["cluster"]) == {"server", "certificate-authority-data"}
                    and cluster["cluster"]["certificate-authority-data"]
                    and config["current-context"] == context["name"]
                    and context["context"]["cluster"] == cluster["name"],
                    "explicit API CA and matching context required; "
                    "insecure/proxy overrides refused",
                )
                require(
                    len(config["users"]) == 1, "standard inline-certificate kubeconfig required"
                )
                require(
                    context["context"]["user"] == config["users"][0]["name"],
                    "API user context mismatch",
                )
                user = config["users"][0]["user"]
                require(
                    set(user) == {"client-certificate-data", "client-key-data"}
                    and all(isinstance(value, str) and value for value in user.values()),
                    "exec/token/file credentials are outside the supported kubeconfig layout",
                )
                # Pin API trust/configuration while allowing native client certificate renewal.
                config["users"][0]["user"] = {key: "rotating-client-credential" for key in user}
                files[filename] = digest(json.dumps(config, sort_keys=True).encode())
            else:
                files[filename] = digest(path.read_bytes()) if path.exists() else None
        return {
            "machine_id_sha256": digest(Path("/etc/machine-id").read_bytes()),
            "systemd_sha256": digest(effective.encode()),
            "yaml_fragments": fragments,
            "files": files,
        }

    def join_target(self, value):
        require(isinstance(value, str), "unsupported join target")
        url = urlsplit(value)
        require(
            url.scheme == "https"
            and url.port == 6443
            and "@" not in url.netloc
            and not url.path
            and not url.query
            and not url.fragment
            and url.hostname
            in {m["hostname"] for m in self.e["members"] if m["id"] != self.e["local_member_id"]},
            "join target must be an enrolled hostname, not a stale IP",
        )

    def recovery_hook_loaded(self):
        # Enrollment installs this last and deliberately does not reload systemd.
        # Every operational invocation must prove both disk and loaded unit state.
        require(HOOK.is_file(), "missing recovery hook")
        trusted_file(HOOK)
        require(HOOK.read_bytes() == recovery_hook(), "recovery hook changed")
        unit = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=NeedDaemonReload,DropInPaths,ExecStartPre,ExecStartPost",
            ]
        )
        properties = dict(line.split("=", 1) for line in unit.splitlines() if "=" in line)
        require(
            properties.get("NeedDaemonReload") == "no"
            and str(HOOK) in properties.get("DropInPaths", "").split(),
            "recovery hook is not loaded; operator daemon-reload required",
        )
        for line in recovery_hook().decode().splitlines()[2:]:
            key, expected = line.split("=", 1)
            ignore = "yes" if expected.startswith("-") else "no"
            expected = expected.lstrip("-")
            commands = re.findall(
                r"argv\[\]=(.*?) ; ignore_errors=(yes|no) ;", properties.get(key, "")
            )
            require(
                commands.count((expected, ignore)) == 1,
                "loaded recovery command differs from the installed hook",
            )

    def config(self):
        if not self.enrolling:
            self.recovery_hook_loaded()
        inventory = self.inventory()
        require(
            all(inventory[key] == self.e[key] for key in inventory),
            "enrolled machine, configuration or trust material changed",
        )
        if self.e["schema_version"] == 2:
            require(
                self.local_database() == self.e["local_database"], "local database identity changed"
            )
            if not self.preparing:
                self.resolver_ready()

    def local_database(self):
        root = Path("/var/lib/rancher/k3s/server/db")
        member = root / "etcd/member"
        name = root / "etcd/name"
        for path in (member, member / "wal", member / "snap/db", name):
            trusted_file(path)
        for path in (member / "wal").glob("*.wal"):
            trusted_file(path)
        require(not (root / "reset-flag").exists(), "reset state requires operator investigation")
        require(
            member.is_dir() and (member / "snap/db").stat().st_size > 0,
            "initialized existing database required",
        )
        local = next(m for m in self.e["members"] if m["id"] == self.e["local_member_id"])
        require(name.read_text() == local["name"], "persisted member name changed")
        identity = sibling("ethernet_wal_identity").identity(member / "wal")
        require(
            identity == {"member_id": local["id"], "cluster_id": self.e["cluster_id"]},
            "persisted WAL identity differs from enrollment",
        )
        info = member.stat()
        return {
            **identity,
            "device": info.st_dev,
            "inode": info.st_ino,
            "name_sha256": digest(name.read_bytes()),
        }

    def resolver_ready(self):
        dns = sibling("ethernet_mdns_resolver")
        directory_view = self.e.get("resolver_view") is not None
        for path, content in dns.service_files(self.e).items():
            trusted_file(path)
            require(path.read_bytes() == content, "scoped resolver installation changed")
        state = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "sugarkube-ethernet-dns.service",
                "--property=ActiveState,NeedDaemonReload,DropInPaths,ExecStart,MainPID"
                + (",RuntimeDirectory,RuntimeDirectoryPreserve" if directory_view else ""),
            ]
        )
        dns_state = dict(line.split("=", 1) for line in state.splitlines() if "=" in line)
        if directory_view:
            require(
                dns_state.get("RuntimeDirectory") == "sugarkube-ethernet-dns"
                and dns_state.get("RuntimeDirectoryPreserve") == "yes",
                "resolver runtime directory lifetime is not preserved",
            )
        dns_command = f"/usr/bin/python3 -I {dns.RUNTIME} --enrollment {dns.CONFIG}"
        dns_pid = dns_state.get("MainPID", "0")
        require(
            dns_state.get("ActiveState") == "active"
            and dns_state.get("NeedDaemonReload") == "no"
            and not dns_state.get("DropInPaths")
            and dns_pid.isdigit()
            and int(dns_pid) > 0
            and re.findall(
                r"argv\[\]=(.*?) ; ignore_errors=(yes|no) ;", dns_state.get("ExecStart", "")
            )
            == [(dns_command, "no")],
            "scoped resolver not ready or loaded command changed",
        )
        unit = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=NeedDaemonReload,DropInPaths,BindReadOnlyPaths,MainPID",
            ]
        )
        properties = dict(line.split("=", 1) for line in unit.splitlines() if "=" in line)
        binding = f"{dns.STATE}/process-resolv.conf:/etc/resolv.conf"
        bindings = properties.get("BindReadOnlyPaths", "").split()
        if directory_view:
            expected_bindings = dns.resolver_bindings(self.e)
            binding_valid = bindings in (
                expected_bindings,
                [item.removesuffix(":norbind") for item in expected_bindings],
            )
        else:
            binding_valid = bindings in ([binding], [binding + ":rbind"])
        require(
            properties.get("NeedDaemonReload") == "no"
            and DNS_HOOK in properties.get("DropInPaths", "").split()
            and binding_valid,
            "K3s scoped resolver hook is not loaded exactly",
        )
        for filename in ("upstream-resolv.conf", "process-resolv.conf", "kubelet-resolv.conf"):
            trusted_file(dns.STATE / filename)
        _, expected = dns.resolver_text((dns.STATE / "upstream-resolv.conf").read_text())
        require(
            (dns.STATE / "process-resolv.conf").read_text() == expected,
            "resolver process view differs from host search/options",
        )
        require(
            (dns.STATE / "kubelet-resolv.conf").read_text()
            == dns.pod_resolver_text(
                Path(f"/proc/{dns_pid}/root{self.e['pod_resolv_source']}").read_text()
            ),
            "kubelet resolver differs from enrolled original source",
        )
        pid = properties.get("MainPID", "0")
        require(pid.isdigit(), "invalid K3s process identity")
        if directory_view:
            dns.check_view(self.e, Path(f"/proc/{dns_pid}/root"))
            require(
                (dns.STATE / "upstream-resolv.conf").read_text()
                == Path(f"/proc/{dns_pid}/root/run/systemd/resolve/stub-resolv.conf").read_text()
                and (dns.STATE / "resolved/stub-resolv.conf").read_text() == expected,
                "resolver publication differs from current original source",
            )
            if int(pid):
                dns.check_process_view(self.e, pid, dns_pid, expected)
        elif int(pid):
            require(
                Path(f"/proc/{pid}/root/etc/resolv.conf").read_text() == expected,
                "running K3s resolver view drifted; explicit restart required",
            )

    def peer_tls(self, host):
        """Healthy-time check of both peer hostname SAN and source-SAN acceptance."""
        base = Path("/var/lib/rancher/k3s/server/tls/etcd")
        context = ssl.create_default_context(cafile=str(base / "peer-ca.crt"))
        context.load_cert_chain(
            str(base / "peer-server-client.crt"), str(base / "peer-server-client.key")
        )
        connection = http.client.HTTPConnection(host, 2380, timeout=5)
        raw = self.connect_peer(self.resolve(host), port=2380)
        try:
            connection.sock = context.wrap_socket(raw, server_hostname=host)
            names = {
                value
                for kind, value in connection.sock.getpeercert().get("subjectAltName", [])
                if kind == "DNS"
            }
            enrolled = {m["hostname"] for m in self.e["members"]}
            require(
                names & enrolled == {host} and "*.local" not in names,
                "peer hostname SAN is not specific to the enrolled member",
            )
            connection.request("GET", "/members")
            response = connection.getresponse()
            data = response.read(1024 * 1024 + 1)
            require(
                response.status == 200 and len(data) <= 1024 * 1024,
                "peer source-SAN authentication failed",
            )
        finally:
            raw.close()
            connection.close()

    def network(self, ip):
        path = Path("/etc/rancher/k3s/config.yaml.d/20-sugarkube-network.yaml")
        expected = (
            f'# Managed by configure_k3s_node_ip.sh\nnode-ip: "{ip}"\n'
            f'flannel-iface: "{self.e["interface"]}"\n'
        )
        require(
            not path.is_symlink() and path.read_text() == expected,
            "managed network configuration does not match current Ethernet address",
        )

    def refresh(self):
        self.command(
            [
                "/bin/bash",
                "/etc/rancher/k3s/sugarkube-network-prestart.sh",
                "--refresh-on-start",
                self.e["interface"],
                "/etc/rancher/k3s",
                "/var/lib/sugarkube/logs",
                "/usr/sbin/ip",
            ]
        )

    def active(self):
        return self.command(["/usr/bin/systemctl", "is-active", "k3s.service"]).strip() == "active"

    def transport_running(self):
        output = self.command(
            ["/usr/bin/systemctl", "show", "k3s.service", "--property=ActiveState,MainPID"]
        )
        values = dict(line.split("=", 1) for line in output.splitlines())
        return values["ActiveState"] in ("active", "activating") and int(values["MainPID"]) > 0

    def stable_address(self, expected):
        for index in range(3):
            require(self.address() == expected, "Ethernet address is not stable")
            if index < 2:
                time.sleep(15)

    def running(self):
        output = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                "k3s.service",
                "--property=ActiveState,MainPID,InvocationID,NRestarts",
            ]
        )
        fields = dict(line.split("=", 1) for line in output.splitlines())
        require(
            fields["ActiveState"] == "active"
            and int(fields["MainPID"]) > 0
            and re.fullmatch(r"[0-9a-f]{32}", fields["InvocationID"]),
            "K3s has not reached active service state",
        )
        return {key: fields[key] for key in ("MainPID", "InvocationID", "NRestarts")}

    def restart(self, operator=False):
        # Called only after durable authorization and after releasing the local lock.
        self.command(
            [
                "/usr/bin/systemctl",
                "--no-block",
                "restart" if operator else "try-restart",
                "k3s.service",
            ]
        )

    def address(self):
        rows = json.loads(
            self.command(
                [
                    "/usr/sbin/ip",
                    "-j",
                    "-4",
                    "addr",
                    "show",
                    "dev",
                    self.e["interface"],
                    "scope",
                    "global",
                ]
            )
        )
        addresses = [
            a["local"]
            for row in rows
            for a in row["addr_info"]
            if a["scope"] == "global"
            and not any(
                a.get(k, False) or k in a.get("flags", [])
                for k in ("secondary", "tentative", "deprecated")
            )
        ]
        require(len(addresses) == 1, "one primary Ethernet IPv4 required")
        ip = ipaddress.IPv4Address(addresses[0])
        require(
            not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified),
            "invalid Ethernet address",
        )
        return str(ip)

    def resolve(self, host):
        if self.e["schema_version"] == 2 and not self.preparing:
            require(host in {m["hostname"] for m in self.e["members"]}, "unenrolled resolver name")
            ip = sibling("ethernet_mdns_resolver").query_stub(host)
            if host in self.locators:
                require(self.locators[host] == ip, "address changed during recovery")
            self.locators[host] = ip
            return ip
        rows = self.command(["/usr/bin/avahi-resolve-host-name", "-4", host]).splitlines()
        require(len(rows) == 1, "ambiguous mDNS result")
        fields = rows[0].split()
        require(len(fields) == 2 and fields[0].lower() == host, "mDNS name mismatch")
        ip = str(ipaddress.IPv4Address(fields[1]))
        # Corroborate the locator through NSS before pinning the numeric TCP destination.
        rows = self.command(["/usr/bin/getent", "ahostsv4", host]).splitlines()
        addresses = {line.split()[0] for line in rows}
        require(addresses == {ip}, "mDNS and NSS disagree")
        if host in self.locators:
            require(self.locators[host] == ip, "address changed during recovery")
        self.locators[host] = ip
        return ip

    def address_node(self, host, node_name, patch=None, status=False):
        """One authenticated HTTP request, with no redirects, proxy or retry."""
        require(host in {m["hostname"] for m in self.e["members"]}, "unenrolled API host")
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]*", node_name), "invalid Node name")
        config = yaml.safe_load(Path(self.e["kubeconfig"]).read_text())
        ca = base64.b64decode(config["clusters"][0]["cluster"]["certificate-authority-data"])
        user = config["users"][0]["user"]
        context = ssl.create_default_context(cadata=ca.decode())
        # load_cert_chain needs paths; temporary credentials are private and removed
        # before the request, including on failure. Never change enrolled credentials.
        with tempfile.TemporaryDirectory(prefix="sugarkube-api-") as directory:
            paths = []
            for key in ("client-certificate-data", "client-key-data"):
                path = Path(directory) / key
                with path.open("xb") as handle:
                    os.chmod(path, 0o600)
                    handle.write(base64.b64decode(user[key]))
                paths.append(str(path))
            context.load_cert_chain(*paths)
        connection = http.client.HTTPConnection(host, 6443, timeout=5)
        raw = self.connect_peer(self.resolve(host), port=6443)
        try:
            connection.sock = context.wrap_socket(raw, server_hostname=host)
            route = f"/api/v1/nodes/{node_name}" + ("/status" if status else "")
            connection.request(
                "PATCH" if patch is not None else "GET",
                route,
                body=json.dumps(patch) if patch is not None else None,
                headers={"Content-Type": "application/json-patch+json", "Connection": "close"},
            )
            response = connection.getresponse()
            data = response.read(1024 * 1024 + 1)
            require(response.status == 200, f"Node API HTTP {response.status}; no retry")
            require(len(data) <= 1024 * 1024, "Node API response too large")
            return json.loads(data)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise Stop(
                "Node API transport/response failed; mutation intent remains latched"
            ) from exc
        finally:
            raw.close()
            connection.close()

    def node(self, host, node_name):
        return json.loads(
            self.command(
                [
                    "/usr/local/bin/kubectl",
                    f"--kubeconfig={self.e['kubeconfig']}",
                    f"--server=https://{self.resolve(host)}:6443",
                    f"--tls-server-name={host}",
                    "--request-timeout=5s",
                    "get",
                    "node",
                    node_name,
                    "-o",
                    "json",
                ]
            )
        )

    def workloads(self, host):
        base = [
            "/usr/local/bin/kubectl",
            f"--kubeconfig={self.e['kubeconfig']}",
            f"--server=https://{self.resolve(host)}:6443",
            f"--tls-server-name={host}",
            "--request-timeout=5s",
            "get",
        ]
        items = json.loads(
            self.command(
                base
                + [
                    "deployments.apps,statefulsets.apps,daemonsets.apps,pods",
                    "--all-namespaces",
                    "-o",
                    "json",
                ]
            )
        )["items"]
        for item in items:
            status, kind = item.get("status", {}), item["kind"]
            if kind == "Pod":
                require(
                    status.get("phase") == "Succeeded"
                    or (
                        status.get("phase") == "Running"
                        and any(
                            c.get("type") == "Ready" and c.get("status") == "True"
                            for c in status.get("conditions", [])
                        )
                    ),
                    "workload Pod completion pending",
                )
                continue
            require(
                status.get("observedGeneration", 0) >= item["metadata"]["generation"],
                "workload controller has not observed desired state",
            )
            if kind == "DaemonSet":
                desired = status.get("desiredNumberScheduled", 0)
                require(
                    status.get("numberReady", 0) == desired
                    and status.get("numberUnavailable", 0) == 0,
                    "DaemonSet completion pending",
                )
            else:
                desired = item["spec"].get("replicas", 1)
                require(status.get("readyReplicas", 0) == desired, "workload replicas not Ready")
        for value in self.e["completion_https_urls"]:
            url = urlsplit(value)
            connection = http.client.HTTPSConnection(
                url.hostname, url.port or 443, timeout=5, context=ssl.create_default_context()
            )
            try:
                connection.request("GET", url.path or "/")
                response = connection.getresponse()
                require(
                    response.status == 200 and len(response.read(1024 * 1024 + 1)) <= 1024 * 1024,
                    "application HTTPS completion pending",
                )
            finally:
                connection.close()


class Recovery:
    def __init__(self, enrollment, backend, journal):
        validate_enrollment(enrollment)
        self.e, self.b, self.path = enrollment, backend, journal
        self.local = next(
            m for m in enrollment["members"] if m["id"] == enrollment["local_member_id"]
        )
        self.survivors = [m for m in enrollment["members"] if m != self.local]
        self.host = self.survivors[0]["hostname"]

    def membership(self):
        result = self.b.etcd(self.host, "member", "list")
        require(str(result["header"]["cluster_id"]) == self.e["cluster_id"], "cluster changed")
        actual = {str(m["ID"]): m for m in result["members"]}
        require(len(result["members"]) == len(actual) == 3, "membership changed")
        require(set(actual) == {m["id"] for m in self.e["members"]}, "member identity changed")
        for member in self.e["members"]:
            entry = actual[member["id"]]
            require(
                entry["name"] == member["name"] and not entry.get("isLearner", False),
                "member name or voter role changed",
            )
            if self.e["schema_version"] == 1:
                require(len(entry["peerURLs"]) == 1, "one peer URL per voter required")
            else:
                urls = entry["peerURLs"]
                numeric = urlsplit(urls[0]).hostname if urls else None
                try:
                    address = ipaddress.IPv4Address(numeric)
                except (ValueError, TypeError) as exc:
                    raise Stop("canonical numeric peer URL required") from exc
                require(
                    not (
                        address.is_loopback
                        or address.is_unspecified
                        or address.is_multicast
                        or address.is_link_local
                    ),
                    "invalid peer address",
                )
                expected = dual_urls(member, str(address))
                allowed = [expected]
                if (
                    getattr(self.b, "enrolling", False) or getattr(self, "allow_single", False)
                ) and not self.e.get("armed", False):
                    allowed.append(expected[:1])
                require(
                    urls in allowed, "only canonical numeric and enrolled hostname URLs allowed"
                )
                # Client URLs are automatically republished by etcd during startup.
                # They are never our locators or MemberUpdate inputs. Snapshot the
                # identity/role/peer-URL state protected by this controller.
                actual[member["id"]] = {
                    "ID": str(entry["ID"]),
                    "name": entry["name"],
                    "isLearner": False,
                    "peerURLs": list(urls),
                }
        return actual

    def prove_etcd(self, include_local=False):
        self.b.config()
        ip = self.b.address()
        require(self.b.resolve(self.local["hostname"]) == ip, "local mDNS/Ethernet mismatch")
        voters = self.e["members"] if include_local else self.survivors
        for member in voters:
            self.b.resolve(member["hostname"])
            status = self.b.etcd(member["hostname"], "endpoint", "status")
            require(len(status) == 1, "ambiguous endpoint status")
            status = status[0]["Status"]
            require(
                str(status["header"]["cluster_id"]) == self.e["cluster_id"]
                and str(status["header"]["member_id"]) == member["id"],
                "endpoint identity changed",
            )
            require(
                not status.get("errors") and not status.get("isLearner", False),
                "unhealthy or learner endpoint",
            )
            health = self.b.etcd(member["hostname"], "endpoint", "health")
            require(
                len(health) == 1 and health[0].get("health") is True,
                "two healthy surviving voters are required; no reset is permitted",
            )
        return ip, self.membership()

    def prove(self, include_local=False):
        ip, members = self.prove_etcd(include_local)
        node = self.b.node(self.host, self.local["hostname"].removesuffix(".local"))
        require(node["metadata"]["uid"] == self.local["node_uid"], "Node identity changed")
        require(
            node["metadata"]["annotations"]["etcd.k3s.cattle.io/node-name"] == self.local["name"],
            "Node/member binding changed",
        )
        return ip, members, node

    def transaction(self, token, release=False):
        compare = {
            "key": encode(KEY),
            "result": "EQUAL",
            "target": "VALUE" if release else "VERSION",
        }
        compare["value" if release else "version"] = encode(token) if release else "0"
        operation = {"key": encode(KEY)}
        if not release:
            operation["value"] = encode(token)
        payload = {
            "compare": [compare],
            "success": [{"request_delete_range" if release else "request_put": operation}],
            "failure": [],
        }
        return self.b.etcd(self.host, "txn", input_text=json.dumps(payload))

    def previous(self):
        if not self.path.exists():
            return None
        previous = json.loads(self.path.read_text())
        require(
            previous["member_id"] == self.local["id"]
            and previous["cluster_id"] == self.e["cluster_id"],
            "journal identity changed",
        )
        return previous

    def pre_start(self, watch=False):
        # An unfinished authorization cannot be replayed by Restart=always.
        baseline = self.e["local_ipv4"]
        previous = self.previous()
        if previous:
            if previous["phase"] == "restart-requested" and not watch:
                ip, members, _ = self.prove()
                require(
                    ip == previous["ip"]
                    and members[self.local["id"]]["peerURLs"] == [f"https://{ip}:2380"],
                    "pending restart identity/address changed",
                )
                self.owned(previous["token"])
                self.b.network(ip)
                previous["phase"] = "start-authorized"
                atomic_json(self.path, previous)
                return "one-start-authorized"
            require(
                previous["phase"] == "complete",
                "unfinished recovery; operator intervention required",
            )
            baseline = previous["ip"]
        self.b.config()
        ip = self.b.address()
        # Unchanged voters must start after a cold cluster shutdown without quorum.
        if ip == baseline:
            if watch:
                observation = self.path.parent / "observation.json"
                if observation.exists():
                    atomic_json(observation, {"ip": ip, "time": time.time()})
            if not watch:
                self.b.network(ip)
            return "unchanged"
        if watch:
            require(self.b.active(), "K3s must already be active for a watcher restart")
            observation = self.path.parent / "observation.json"
            now = time.time()
            observed = json.loads(observation.read_text()) if observation.exists() else {}
            if observed.get("ip") != ip or not 30 <= now - observed.get("time", now) <= 300:
                if observed.get("ip") != ip or not 0 <= now - observed.get("time", now) < 30:
                    atomic_json(observation, {"ip": ip, "time": now})
                return "observing"
        ip, members, _ = self.prove()
        url = f"https://{ip}:2380"
        old = members[self.local["id"]]["peerURLs"]
        require(
            old == [f"https://{baseline}:2380"],
            "peer URL changed outside this enrollment; reconcile explicitly",
        )
        incident = {
            "token": uuid.uuid4().hex,
            "phase": "reserved",
            "ip": ip,
            "member_id": self.local["id"],
            "old_peer_urls": old,
            "cluster_id": self.e["cluster_id"],
        }
        atomic_json(self.path, incident)
        acquired = self.transaction(incident["token"])
        require(acquired.get("succeeded") is True, "another incident owns recovery")
        if watch:
            self.b.refresh()
        self.b.network(ip)
        # Revalidate immediately before the non-transactional membership RPC.
        fresh_ip, fresh_members, _ = self.prove()
        require(fresh_ip == ip and fresh_members == members, "evidence changed while reserving")
        self.owned(incident["token"])
        self.b.etcd(
            self.host, "member", "update", format(int(self.local["id"]), "x"), f"--peer-urls={url}"
        )
        confirmed = self.membership()
        require(confirmed[self.local["id"]]["peerURLs"] == [url], "member update not confirmed")
        require(
            all(confirmed[m["id"]] == members[m["id"]] for m in self.survivors),
            "survivor membership changed",
        )
        require(self.b.address() == ip, "Ethernet address changed after member update")
        self.b.network(ip)
        self.b.config()
        incident["phase"] = "restart-requested" if watch else "start-authorized"
        atomic_json(self.path, incident)
        return "restart-requested" if watch else "one-start-authorized"

    def owned(self, token):
        values = self.b.etcd(self.host, "get", KEY).get("kvs", [])
        require(
            len(values) == 1 and base64.b64decode(values[0]["value"]).decode() == token,
            "incident ownership lost",
        )

    def watch(self):
        previous = self.previous()
        if previous and previous["phase"] in ("start-authorized", "verifying"):
            # A healthy process may converge after ExecStartPost timed out. Only
            # completion may retry; never replay a membership write or restart request.
            return self.post_start()
        return self.pre_start(watch=True)

    def resume(self):
        """Explicit operator action after investigation/status repair; never called by timer."""
        incident = self.previous()
        require(incident is not None and incident["phase"] != "complete", "no pending incident")
        ip, members, node = self.prove()
        require(
            ip == incident["ip"]
            and members[self.local["id"]]["peerURLs"] == [f"https://{ip}:2380"],
            "member update must be reconciled before resuming",
        )
        self.owned(incident["token"])
        self.b.network(ip)
        annotation = node["metadata"]["annotations"].get("k3s.io/internal-ip")
        internal = [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"]
        prior_ip = urlsplit(incident["old_peer_urls"][0]).hostname
        require(
            (annotation == ip and internal == [ip])
            or (annotation == prior_ip and internal == [prior_ip]),
            "Node status/annotation must be reconciled before resuming",
        )
        incident["operator_resumes"] = incident.get("operator_resumes", 0) + 1
        incident["phase"] = "restart-requested"
        atomic_json(self.path, incident)
        return "operator-restart-requested"

    def post_start(self):
        if not self.path.exists():
            return "unchanged"
        incident = json.loads(self.path.read_text())
        if incident["phase"] == "complete":
            return "unchanged"
        require(
            incident["phase"] in ("start-authorized", "verifying"),
            "incident requires operator reconciliation",
        )
        ip, members, node = self.prove(include_local=True)
        require(
            ip == incident["ip"]
            and self.local["id"] == incident["member_id"]
            and self.e["cluster_id"] == incident["cluster_id"],
            "incident identity/address changed",
        )
        require(members[self.local["id"]]["peerURLs"] == [f"https://{ip}:2380"], "peer URL changed")
        require(
            node["metadata"]["annotations"].get("k3s.io/internal-ip") == ip,
            "Node annotation has not converged",
        )
        internal = [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"]
        require(internal == [ip], "Node status has not converged; never patch blindly")
        require(
            any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in node["status"].get("conditions", [])
            ),
            "Node is not Ready",
        )
        running = self.b.running()
        now = time.monotonic()
        if incident["phase"] == "start-authorized":
            incident.update(phase="verifying", running=running, verified_at_monotonic=now)
            atomic_json(self.path, incident)
            return "verifying"
        require(running == incident["running"], "K3s restarted during recovery verification")
        elapsed = now - incident["verified_at_monotonic"]
        require(elapsed >= 0, "verification clock changed; reconcile the incident")
        if elapsed < 30:
            return "verifying"
        released = self.transaction(incident["token"], release=True)
        require(released.get("succeeded") is True, "incident ownership changed")
        incident["phase"] = "complete"
        atomic_json(self.path, incident)
        return "complete"


class DualRecovery(Recovery):
    """Version 2: restore original transport, then reconcile one original member.

    Global ownership protects only membership. Node/workload completion remains a
    local pending journal, so one stale API cannot prevent the other two repairs.
    """

    def __init__(self, enrollment, backend, journal):
        super().__init__(enrollment, backend, journal)
        self.host = self.local["hostname"]
        self.allow_single = False

    def save(self, incident, phase):
        incident["phase"] = phase
        atomic_json(self.path, incident)

    def marker(self, member):
        roster = sorted(self.e["members"], key=lambda entry: entry["id"])
        return json.dumps(
            {
                "schema_version": 2,
                "cluster_id": self.e["cluster_id"],
                "member_id": member["id"],
                "node_uid": member["node_uid"],
                "hostname": member["hostname"],
                "k3s_version": self.e["k3s_version"],
                "roster_sha256": digest(json.dumps(roster, sort_keys=True).encode()),
            },
            sort_keys=True,
        )

    def read_marker(self, member):
        values = self.b.etcd(self.host, "get", KEY + "/enrollment/" + member["id"]).get("kvs", [])
        require(len(values) <= 1, "ambiguous enrollment marker")
        return base64.b64decode(values[0]["value"]).decode() if values else None

    def finish_enrollment(self, incident, *, resume=False):
        self.allow_single = True
        members = self.prove_transport(incident)
        require(
            members[self.local["id"]]["peerURLs"] == dual_urls(self.local, incident["ip"]),
            "dual peer enrollment is not confirmed",
        )
        self.healthy_nodes()
        if incident["phase"] == "enrollment-marker-intent":
            require(
                resume and self.read_marker(self.local) == self.marker(self.local),
                "enrollment marker outcome unknown; no replay permitted",
            )
        else:
            require(incident["phase"] == "completion-pending", "unfinished enrollment")
            key, value = KEY + "/enrollment/" + self.local["id"], self.marker(self.local)
            self.save(incident, "enrollment-marker-intent")
            payload = {
                "compare": [
                    {"key": encode(key), "target": "VERSION", "result": "EQUAL", "version": "0"}
                ],
                "success": [{"request_put": {"key": encode(key), "value": encode(value)}}],
                "failure": [],
            }
            result = self.b.etcd(self.host, "txn", input_text=json.dumps(payload))
            require(type(result.get("succeeded")) is bool, "enrollment marker outcome unknown")
            require(self.read_marker(self.local) == value, "conflicting enrollment marker")
        self.save(incident, "complete")
        return "peer-enrolled"

    def enroll_peer(self, *, resume=False):
        require(self.e.get("armed") is not True, "already armed; enrollment cannot mutate again")
        self.allow_single = True
        ip, members = self.prove_etcd(include_local=True)
        require(ip == self.e["local_ipv4"], "address changed during healthy-time enrollment")
        self.healthy_nodes()
        for member in self.e["members"]:
            address = self.b.resolve(member["hostname"])
            require(
                members[member["id"]]["peerURLs"]
                in (dual_urls(member, address), dual_urls(member, address)[:1]),
                "healthy-time enrollment requires current numeric URLs",
            )
            self.b.peer_tls(member["hostname"])
        incident = self.previous()
        if incident is None:
            incident = {
                "token": uuid.uuid4().hex,
                "phase": "transport-pending",
                "created_at": time.time(),
                "kind": "enrollment",
                "transport": "not-needed",
                "ip": ip,
                "member_id": self.local["id"],
                "cluster_id": self.e["cluster_id"],
                "mutation_dispatched": False,
                "old_peer_urls": members[self.local["id"]]["peerURLs"],
            }
            atomic_json(self.path, incident)
        require(
            incident["kind"] == "enrollment", "existing recovery journal requires reconciliation"
        )
        if incident["phase"] == "complete":
            require(
                members[self.local["id"]]["peerURLs"] == dual_urls(self.local, ip)
                and self.read_marker(self.local) == self.marker(self.local),
                "enrollment drifted",
            )
            return "peer-enrolled"
        if incident["phase"] in ("transport-pending", "waiting-for-lock"):
            outcome = self.reconcile(incident)
            if outcome == "waiting-for-lock":
                return outcome
        elif incident["phase"] not in ("completion-pending", "enrollment-marker-intent"):
            require(resume, "unknown enrollment outcome remains latched; explicit resume required")
            self.resume()
        return self.finish_enrollment(self.previous(), resume=resume)

    def arm(self):
        require(self.e.get("dual_enrolled") is True, "local peer enrollment incomplete")
        incident = self.previous()
        require(incident and incident["phase"] == "complete", "pending enrollment/recovery journal")
        ip, members = self.prove_etcd(include_local=True)
        require(ip == self.e["local_ipv4"], "address changed before arming")
        self.healthy_nodes()
        for member in self.e["members"]:
            require(
                members[member["id"]]["peerURLs"]
                == dual_urls(member, self.b.resolve(member["hostname"])),
                "all three dual peer enrollments must be current before arming",
            )
            require(
                self.read_marker(member) == self.marker(member),
                "missing/conflicting peer enrollment marker",
            )
            self.b.peer_tls(member["hostname"])
        return "armed"

    def local_guard(self):
        self.b.config()
        ip = self.b.address()
        require(self.b.resolve(self.local["hostname"]) == ip, "local mDNS/Ethernet mismatch")
        self.b.network(ip)
        return ip

    @property
    def address_journal(self):
        return self.path.parent / "node-address.json"

    def address_identity(self, node, member):
        metadata = node["metadata"]
        require(
            metadata["name"] == member["hostname"].removesuffix(".local")
            and metadata["uid"] == member["node_uid"]
            and metadata["annotations"].get("etcd.k3s.cattle.io/node-name") == member["name"]
            and not metadata.get("deletionTimestamp")
            and isinstance(metadata["resourceVersion"], str)
            and bool(metadata["resourceVersion"]),
            "Node name/UID/member binding or resourceVersion changed",
        )

    def address_proof(self, ip, old):
        require(self.local_guard() == ip, "Node address incident changed")
        # DualRecovery normally uses its local etcd endpoint. This pre-start proof
        # must use survivors exclusively, including the linearizable member list.
        proof = Recovery(self.e, self.b, self.path)
        current, members = proof.prove_etcd()
        require(current == ip, "Ethernet address changed during Node proof")
        addresses = {m["id"]: self.b.resolve(m["hostname"]) for m in self.e["members"]}
        require(len(set(addresses.values())) == 3, "duplicate discovered member addresses")
        require(
            members[self.local["id"]]["peerURLs"]
            in (dual_urls(self.local, old), dual_urls(self.local, ip)),
            "local peer URL changed outside address incident",
        )
        for member in self.survivors:
            host = member["hostname"]
            require(
                members[member["id"]]["peerURLs"] == dual_urls(member, addresses[member["id"]]),
                "survivor peer address has not converged",
            )
            node = self.b.address_node(host, host.removesuffix(".local"))
            self.address_identity(node, member)
            require(
                node["metadata"]["annotations"].get("k3s.io/internal-ip") == addresses[member["id"]]
                and [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"]
                == [addresses[member["id"]]]
                and any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in node["status"].get("conditions", [])
                ),
                "two healthy converged surviving Nodes required; all-member recovery unsupported",
            )
        node = self.b.address_node(proof.host, self.local["hostname"].removesuffix(".local"))
        self.address_identity(node, self.local)
        annotation = node["metadata"]["annotations"].get("k3s.io/internal-ip")
        addresses = node["status"]["addresses"]
        internal = [a["address"] for a in addresses if a["type"] == "InternalIP"]
        require(
            annotation in (old, ip) and len(internal) == 1 and internal[0] in (old, ip),
            "unexpected Node address; only incident old/new IPv4 allowed",
        )
        for address in addresses:
            require(set(address) == {"type", "address"}, "unexpected Node address fields")
            require(
                address["type"] == "InternalIP"
                or (
                    address["type"] in ("Hostname", "InternalDNS")
                    and address["address"]
                    in (self.local["hostname"], self.local["hostname"].removesuffix(".local"))
                ),
                "unsupported Node address layout; preserve for operator review",
            )
        return proof.host, node

    def address_record(self, ip, old):
        record = (
            json.loads(self.address_journal.read_text()) if self.address_journal.exists() else None
        )
        if record:
            require(
                record["cluster_id"] == self.e["cluster_id"]
                and record["member_id"] == self.local["id"]
                and record["node_uid"] == self.local["node_uid"],
                "Node address journal identity changed",
            )
            if (record["ip"], record["old_ip"]) != (ip, old):
                require(
                    record["phase"] == "verified" and record["ip"] == old,
                    "unfinished Node address incident or second address change",
                )
                record = None
        if record is None:
            record = dict(
                cluster_id=self.e["cluster_id"],
                member_id=self.local["id"],
                node_uid=self.local["node_uid"],
                ip=ip,
                old_ip=old,
                phase="prepared",
            )
        return record

    def address_patch(self, record, host, node, path, value, phase, status=False):
        metadata = node["metadata"]
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": metadata["resourceVersion"],
            },
            {"op": "test", "path": "/metadata/annotations", "value": metadata["annotations"]},
            {"op": "test", "path": "/status/addresses", "value": node["status"]["addresses"]},
            {"op": "replace", "path": path, "value": value},
        ]
        require(self.local_guard() == record["ip"], "address changed before Node mutation")
        record.update(phase=phase + "-intent", patch=patch, status=status)
        atomic_json(self.address_journal, record)
        self.b.address_node(host, self.local["hostname"].removesuffix(".local"), patch, status)
        # Even a successful HTTP response requires an independent authenticated read.
        _, fresh = self.address_proof(record["ip"], record["old_ip"])
        self.confirm_address_patch(record, fresh)
        record["phase"] = phase + "-confirmed"
        atomic_json(self.address_journal, record)

    def confirm_address_patch(self, record, node):
        target = record["patch"][-1]["value"]
        actual = (
            node["status"]["addresses"]
            if record["status"]
            else node["metadata"]["annotations"].get("k3s.io/internal-ip")
        )
        require(actual == target, "Node mutation outcome not confirmed; no replay")

    def prepare_node_address(self, ip, old):
        record = self.address_record(ip, old)
        require(
            not record["phase"].endswith("-intent"),
            "Node mutation outcome unresolved; use read-only resume-node-address; no retry",
        )
        host, node = self.address_proof(ip, old)
        if record["phase"] == "verified":
            require(
                node["metadata"]["annotations"]["k3s.io/internal-ip"] == ip
                and [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"]
                == [ip],
                "verified Node address reverted; operator review required",
            )
            self.address_readback(ip)
            return
        if node["metadata"]["annotations"]["k3s.io/internal-ip"] != ip:
            require(record["phase"] == "prepared", "confirmed annotation reverted")
            self.address_patch(
                record, host, node, "/metadata/annotations/k3s.io~1internal-ip", ip, "annotation"
            )
        # Give the cloud controller a bounded chance to converge naturally. These
        # are read-only polls, never retries of a mutation. A later watcher can
        # continue confirmed work; unknown writes require explicit reconciliation.
        for attempt in range(3):
            host, node = self.address_proof(ip, old)
            require(
                node["metadata"]["annotations"]["k3s.io/internal-ip"] == ip,
                "Node annotation reverted before status convergence",
            )
            if [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"] == [
                ip
            ]:
                break
            if attempt < 2:
                time.sleep(2)
        else:
            require(
                record["phase"] in ("prepared", "annotation-confirmed"), "confirmed status reverted"
            )
            desired = [
                dict(a, address=ip) if a["type"] == "InternalIP" else a
                for a in node["status"]["addresses"]
            ]
            self.address_patch(
                record, host, node, "/status/addresses", desired, "status", status=True
            )
        self.address_readback(ip)
        record["phase"] = "verified"
        atomic_json(self.address_journal, record)

    def address_readback(self, ip):
        # Both survivor APIs are checked again when a start is consumed.
        for member in self.survivors:
            fresh = self.b.address_node(
                member["hostname"], self.local["hostname"].removesuffix(".local")
            )
            self.address_identity(fresh, self.local)
            require(
                fresh["metadata"]["annotations"]["k3s.io/internal-ip"] == ip
                and [
                    a["address"] for a in fresh["status"]["addresses"] if a["type"] == "InternalIP"
                ]
                == [ip],
                "Node address readback has not converged",
            )
        require(self.local_guard() == ip, "address changed after Node reconciliation")

    def resume_node_address(self):
        require(self.address_journal.exists(), "no Node address incident")
        record = json.loads(self.address_journal.read_text())
        record = self.address_record(record["ip"], record["old_ip"])
        require(
            record["phase"] in ("annotation-intent", "status-intent"), "no unknown Node mutation"
        )
        _, node = self.address_proof(record["ip"], record["old_ip"])
        self.confirm_address_patch(record, node)
        record["phase"] = record["phase"].replace("-intent", "-confirmed")
        atomic_json(self.address_journal, record)
        return "node-mutation-observed; no start authorized"

    def pre_start(self, watch=False):
        previous = self.previous()
        baseline = (
            previous["ip"] if previous and previous["phase"] == "complete" else self.e["local_ipv4"]
        )
        self.b.config()
        ip = self.b.address()
        if previous and previous["phase"] != "complete":
            if not watch and previous.get("transport") == "restart-requested":
                require(ip == previous["ip"], "pending transport address changed")
                self.local_guard()
                old = urlsplit(previous["old_peer_urls"][0]).hostname
                self.prepare_node_address(ip, old)
                previous["transport"] = "start-authorized"
                atomic_json(self.path, previous)
                return "one-start-authorized"
            raise Stop("unfinished transport authorization; explicit reconciliation required")
        if ip == baseline and self.address_journal.exists():
            record = json.loads(self.address_journal.read_text())
            record = self.address_record(record["ip"], record["old_ip"])
            require(
                record["phase"] == "verified" and record["ip"] == ip,
                "Node address journal blocks baseline return; preserve mutation outcome",
            )
        if ip == baseline:
            if watch:
                observation = self.path.parent / "observation.json"
                if observation.exists():
                    atomic_json(observation, {"ip": ip, "time": time.time()})
            if not watch:
                self.b.network(ip)
            return "unchanged"
        require(self.e.get("armed") is True, "all-member recovery is not armed")
        if watch:
            require(self.b.transport_running(), "existing K3s process required for rebind")
            observation = self.path.parent / "observation.json"
            now = time.time()
            observed = json.loads(observation.read_text()) if observation.exists() else {}
            if observed.get("ip") != ip or not 30 <= now - observed.get("time", now) <= 300:
                if observed.get("ip") != ip or not 0 <= now - observed.get("time", now) < 30:
                    atomic_json(observation, {"ip": ip, "time": now})
                return "observing"
            self.b.refresh()
        else:
            self.b.stable_address(ip)
        require(self.local_guard() == ip, "local address changed before transport start")
        self.prepare_node_address(ip, baseline)
        incident = {
            "token": uuid.uuid4().hex,
            "phase": "transport-pending",
            "created_at": time.time(),
            "kind": "recovery",
            "transport": "restart-requested" if watch else "start-authorized",
            "ip": ip,
            "member_id": self.local["id"],
            "cluster_id": self.e["cluster_id"],
            "old_peer_urls": dual_urls(self.local, baseline),
            "mutation_dispatched": False,
        }
        atomic_json(self.path, incident)
        return "restart-requested" if watch else "one-start-authorized"

    def prove_transport(self, incident):
        ip, members = self.prove_etcd(include_local=True)
        require(ip == incident["ip"], "incident address changed")
        addresses = {self.b.resolve(member["hostname"]) for member in self.e["members"]}
        require(len(addresses) == 3, "duplicate discovered member addresses")
        return members

    def healthy_nodes(self):
        for member in self.e["members"]:
            ip = self.b.resolve(member["hostname"])
            node = self.b.node(member["hostname"], member["hostname"].removesuffix(".local"))
            require(
                node["metadata"]["uid"] == member["node_uid"]
                and node["metadata"]["annotations"].get("etcd.k3s.cattle.io/node-name")
                == member["name"],
                "Node/member identity changed",
            )
            require(
                node["metadata"]["annotations"].get("k3s.io/internal-ip") == ip
                and [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"]
                == [ip]
                and any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in node["status"].get("conditions", [])
                ),
                "Node address/Ready completion pending",
            )

    def verify_intent(self, incident, members):
        expected = incident["before_members"]
        require(
            members[self.local["id"]]["peerURLs"] == incident["desired_peer_urls"],
            "membership outcome not confirmed; no replay permitted",
        )
        require(
            all(members[m["id"]] == expected[m["id"]] for m in self.survivors),
            "other membership changed during owned update",
        )

    def release_membership(self, incident):
        self.owned(incident["token"])
        self.save(incident, "release-intent")
        result = self.transaction(incident["token"], release=True)
        require(result.get("succeeded") is True, "membership lock release not confirmed")
        self.save(incident, "completion-pending")
        return "completion-pending"

    def reconcile(self, incident, *, owned=False):
        require(
            incident["phase"] in ("transport-pending", "waiting-for-lock", "lock-owned"),
            "unknown outcome remains latched; explicit resume required",
        )
        require(not incident["mutation_dispatched"], "mutation cannot be replayed")
        members = self.prove_transport(incident)  # No Kubernetes API call here.
        require(
            members[self.local["id"]]["peerURLs"] == incident["old_peer_urls"],
            "membership changed outside this incident",
        )
        if not owned:
            self.save(incident, "lock-acquire-intent")
            result = self.transaction(incident["token"])
            if result.get("succeeded") is False:
                # Authenticated, definitive compare failure: no update was dispatched.
                self.save(incident, "waiting-for-lock")
                return "waiting-for-lock"
            require(result.get("succeeded") is True, "lock acquisition outcome unknown")
            self.save(incident, "lock-owned")
        self.owned(incident["token"])
        fresh = self.prove_transport(incident)
        if fresh != members:
            # Another original owner may have completed between our snapshot and
            # successful acquisition. Accept only its canonical, current locator;
            # identity/role/hostname and all-three health were re-proven above.
            require(
                fresh[self.local["id"]] == members[self.local["id"]],
                "local membership changed while reserving",
            )
            for member in self.survivors:
                if fresh[member["id"]] != members[member["id"]]:
                    require(
                        fresh[member["id"]]["peerURLs"]
                        == dual_urls(member, self.b.resolve(member["hostname"])),
                        "unexpected peer membership change while reserving",
                    )
            require(self.b.address() == incident["ip"], "address changed while reserving")
            self.owned(incident["token"])
            # No MemberUpdate intent or dispatch exists. Release only this exact
            # ownership, once, then re-prove on a later watcher invocation.
            # A false/unknown release stays in its own latched phase; neither
            # watcher nor resume can confuse it with post-mutation completion.
            self.save(incident, "pre-mutation-release-intent")
            result = self.transaction(incident["token"], release=True)
            require(result.get("succeeded") is True, "pre-mutation lock release not confirmed")
            self.save(incident, "waiting-for-lock")
            return "waiting-for-lock"
        incident["before_members"] = fresh
        incident["desired_peer_urls"] = dual_urls(self.local, incident["ip"])
        incident["mutation_dispatched"] = True  # Conservative intent, before dispatch.
        self.save(incident, "membership-intent")
        self.b.etcd(
            self.host,
            "member",
            "update",
            format(int(self.local["id"]), "x"),
            "--peer-urls=" + ",".join(incident["desired_peer_urls"]),
        )
        confirmed = self.membership()
        self.verify_intent(incident, confirmed)
        require(self.b.address() == incident["ip"], "address changed after membership update")
        self.save(incident, "membership-verified")
        return self.release_membership(incident)

    def watch(self):
        incident = self.previous()
        if not incident or incident["phase"] == "complete":
            return self.pre_start(watch=True)
        require(incident.get("transport") != "restart-requested", "transport restart not consumed")
        if incident["phase"] in ("transport-pending", "waiting-for-lock"):
            return self.reconcile(incident)
        if incident["phase"] in ("completion-pending", "verifying"):
            return self.post_start()
        raise Stop("unknown outcome remains latched; explicit resume required")

    def resume_transport(self):
        """Explicit one-start authorization; retain any unknown membership intent."""
        incident = self.previous()
        require(incident and incident["phase"] != "complete", "no pending incident")
        require(self.local_guard() == incident["ip"], "pending address changed")
        self.b.stable_address(incident["ip"])
        self.prepare_node_address(incident["ip"], urlsplit(incident["old_peer_urls"][0]).hostname)
        incident["transport"] = "restart-requested"
        incident["operator_transport_resumes"] = incident.get("operator_transport_resumes", 0) + 1
        atomic_json(self.path, incident)
        return "operator-restart-requested"

    def resume(self):
        incident = self.previous()
        require(incident and incident["phase"] != "complete", "no pending incident")
        members = self.prove_transport(incident)
        if incident["phase"] in ("lock-acquire-intent", "lock-owned"):
            require(not incident["mutation_dispatched"], "mutation outcome is unknown")
            self.owned(incident["token"])
            self.save(incident, "lock-owned")
            return self.reconcile(incident, owned=True)
        if incident["phase"] in ("membership-intent", "membership-verified"):
            self.owned(incident["token"])
            self.verify_intent(incident, members)
            self.save(incident, "membership-verified")
            return self.release_membership(incident)
        if incident["phase"] == "release-intent":
            require(
                members[self.local["id"]]["peerURLs"] == incident["desired_peer_urls"],
                "local membership changed after release intent",
            )
            values = self.b.etcd(self.host, "get", KEY).get("kvs", [])
            require(not values, "unknown release remains latched; no lock takeover or replay")
            self.save(incident, "completion-pending")
            return "completion-pending"
        if incident["phase"] in ("completion-pending", "verifying"):
            if incident["phase"] == "verifying":
                self.save(incident, "completion-pending")
            return self.post_start()
        raise Stop("use watcher for confirmed waiting or resume-transport for stopped original DB")

    def post_start(self):
        incident = self.previous()
        if not incident or incident["phase"] == "complete":
            return "unchanged"
        if incident["phase"] in ("transport-pending", "waiting-for-lock"):
            return self.reconcile(incident)
        require(
            incident["phase"] in ("completion-pending", "verifying"),
            "unknown outcome remains latched; explicit resume required",
        )
        members = self.prove_transport(incident)
        require(
            members[self.local["id"]]["peerURLs"] == dual_urls(self.local, incident["ip"]),
            "local membership drifted before completion",
        )
        self.healthy_nodes()  # API and Node gates only AFTER membership lock release.
        self.b.workloads(self.host)
        running, now = self.b.running(), time.monotonic()
        if incident["phase"] == "completion-pending":
            incident.update(running=running, verified_at_monotonic=now)
            self.save(incident, "verifying")
            return "verifying"
        require(running == incident["running"], "K3s restarted during completion")
        elapsed = now - incident["verified_at_monotonic"]
        require(elapsed >= 0, "completion clock changed")
        if elapsed < 30:
            return "verifying"
        self.save(incident, "complete")
        return "complete"


def trusted_file(path):
    info = path.lstat()
    require(
        not path.is_symlink() and info.st_uid == 0 and info.st_mode & 0o022 == 0,
        "untrusted enrollment permissions",
    )
    for parent in path.parents:
        info = parent.lstat()
        require(
            not parent.is_symlink() and info.st_uid == 0 and info.st_mode & 0o022 == 0,
            "untrusted parent directory",
        )


def install_directory(path, mode=0o755):
    """Create only trusted directories and persist every new ancestor entry."""
    if path.exists() or path.is_symlink():
        require(path.is_dir(), "installation parent is not a directory")
        trusted_file(path)
    else:
        install_directory(path.parent)
        path.mkdir(mode=mode)
        path.chmod(mode)
        trusted_file(path)
    # A durable child file is insufficient if its newly created directory can
    # disappear after power loss. Persist this directory and its parent entry,
    # including an existing directory left by an interrupted previous attempt.
    for directory in (path, path.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def enroll(request, destination):
    """Explicit healthy-time enrollment; install inactive hooks, never reload/start."""
    require(destination == ENROLLMENT, "only the standard enrollment path is supported")
    trusted_file(request)
    e = json.loads(request.read_text())
    backend = Backend(e)
    try:
        return enroll_checked(e, destination, backend)
    finally:
        backend.close()


def prepare_resolver(request):
    """Healthy-time, inactive resolver installation; never change certificates."""
    require(
        not ENROLLMENT.exists() and not ENROLLMENT.is_symlink(),
        "existing enrollment requires explicit migration; resolver preparation refused",
    )
    trusted_file(request)
    e = json.loads(request.read_text())
    require(e["schema_version"] == 2, "explicit version 2 request required")
    backend = Backend(e)
    backend.enrolling = backend.preparing = True
    try:
        e.update(backend.inventory())
        e["local_ipv4"] = backend.address()
        e["local_database"] = backend.local_database()
        validate_enrollment(e)
        Recovery(e, backend, Path("/unused-prepare-journal")).prove(include_local=True)
        dns = sibling("ethernet_mdns_resolver")
        e["pod_resolv_source"] = str(dns.select_pod_source())
        e["resolver_view"] = dns.resolved_layout()
        files = dns.service_files(e)
        for path in files:
            require(
                not path.exists() and not path.is_symlink(),
                "existing resolver preparation requires reconciliation",
            )
            install_directory(path.parent)
        # Kubelet must not consume a runtime resolver path until its producer
        # and the K3s dependency on that producer are durably installed.
        kubelet_config = files.pop(dns.KUBELET_CONFIG)
        hook = files.pop(dns.HOOK)
        for path, content in files.items():
            atomic_write(path, content)
            path.chmod(0o644)
        atomic_write(dns.HOOK, hook)
        dns.HOOK.chmod(0o644)
        atomic_write(dns.KUBELET_CONFIG, kubelet_config)
        dns.KUBELET_CONFIG.chmod(0o644)
        return (
            "resolver prepared inactive; owner must activate and qualify "
            "one healthy server at a time"
        )
    finally:
        backend.close()


def enroll_checked(e, destination, backend):
    """Keep every authenticated session bounded to this enrollment invocation."""
    backend.enrolling = True  # Read-only healthy-time proof precedes hook installation.
    if e["schema_version"] == 2:
        dns = sibling("ethernet_mdns_resolver")
        trusted_file(dns.CONFIG)
        resolver_config = json.loads(dns.CONFIG.read_text())
        e["pod_resolv_source"] = resolver_config["pod_resolv_source"]
        e.pop("resolver_view", None)
        if resolver_config.get("resolver_view") is not None:
            dns.view_enabled(resolver_config)
            e["resolver_view"] = resolver_config["resolver_view"]
    e.update(backend.inventory())
    e["local_ipv4"] = backend.address()
    if e["schema_version"] == 2:
        e["armed"] = False
        e["dual_enrolled"] = False
        e["local_database"] = backend.local_database()
    validate_enrollment(e)
    backend.network(e["local_ipv4"])
    running = backend.running()
    # This is enrollment, so every voter and its Node binding must already be healthy.
    recovery = Recovery(e, backend, Path("/unused-enrollment-journal"))
    ip, members, _ = recovery.prove(include_local=True)
    addresses = set()
    for member in e["members"]:
        address = backend.resolve(member["hostname"])
        require(address not in addresses, "duplicate enrolled Ethernet address")
        addresses.add(address)
        require(
            members[member["id"]]["peerURLs"] == [f"https://{address}:2380"]
            or (
                e["schema_version"] == 2
                and members[member["id"]]["peerURLs"] == dual_urls(member, address)
            ),
            "enrollment requires converged peer URLs",
        )
        node = backend.node(member["hostname"], member["hostname"].removesuffix(".local"))
        require(
            node["metadata"]["uid"] == member["node_uid"]
            and node["metadata"]["annotations"].get("etcd.k3s.cattle.io/node-name")
            == member["name"],
            "enrollment Node/member identity mismatch",
        )
        require(
            node["metadata"]["annotations"].get("k3s.io/internal-ip") == address
            and [a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"]
            == [address],
            "enrollment requires converged Node addresses",
        )
        if e["schema_version"] == 2:
            require(
                any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in node["status"].get("conditions", [])
                ),
                "enrollment requires Ready Nodes",
            )
            backend.peer_tls(member["hostname"])
    require(
        ip == e["local_ipv4"] and backend.inventory() == {k: e[k] for k in backend.inventory()},
        "enrollment inputs changed",
    )
    require(backend.running() == running, "K3s process changed during enrollment")
    invocation = f"/usr/bin/python3 -I {RUNTIME}"
    enrollment_arg = f"--enrollment {ENROLLMENT}"
    files = {
        RUNTIME: Path(__file__).read_bytes(),
        TRANSPORT: Path(__file__).with_name("ethernet_etcd_grpc.py").read_bytes(),
        DESCRIPTOR: Path(__file__).with_name("ethernet-etcd.desc").read_bytes(),
        HOOK: recovery_hook(),
        WATCH_SERVICE: (
            "# Managed by ethernet_quorum_recover.py\n[Unit]\n"
            "Description=Guarded Ethernet address recovery\nAfter=network-online.target\n"
            "[Service]\nType=oneshot\nUser=root\nUMask=0077\nTimeoutStartSec=185\n"
            f"ExecStart=/usr/bin/timeout 180s {invocation} watch {enrollment_arg}\n"
        ).encode(),
        WATCH_TIMER: (
            "# Managed by ethernet_quorum_recover.py\n[Unit]\n"
            "Description=Observe Ethernet address changes\n[Timer]\nOnBootSec=60s\n"
            "OnUnitInactiveSec=30s\nAccuracySec=5s\n"
            "Unit=sugarkube-ethernet-recovery.service\n[Install]\nWantedBy=timers.target\n"
        ).encode(),
    }
    if e["schema_version"] == 2:
        files[WAL_RUNTIME] = Path(__file__).with_name("ethernet_wal_identity.py").read_bytes()
    # Do all conflict checks before writing. Failed installation is never enabled.
    for path in [destination, *files]:
        require(
            not path.exists() and not path.is_symlink(),
            "existing enrollment/hook must be reconciled",
        )
    # The K3s hook is the activation boundary: a reboot discovers it even without
    # daemon-reload. Persist every prerequisite before making that hook visible.
    hook_content = files.pop(HOOK)
    # Validate/create every destination directory before installing executable
    # content. Refuse existing writable/symlink ancestors instead of changing them.
    for path in [destination, HOOK, *files]:
        install_directory(path.parent)
    for path, content in files.items():
        atomic_write(path, content)
        path.chmod(0o644)
    atomic_json(destination, e)
    atomic_write(HOOK, hook_content)
    HOOK.chmod(0o644)
    return "enrolled; hooks and timer installed but not reloaded or enabled"


def private_state(path):
    # Journal durability also requires the state directory's own entry to survive
    # power loss before a membership write or start authorization can occur.
    install_directory(path, mode=0o700)
    info = path.lstat()
    require(
        not path.is_symlink() and info.st_uid == 0 and info.st_mode & 0o077 == 0,
        "untrusted journal directory",
    )


def report_startup_failure(backend, state_dir):
    """Best effort: preserve the initiating error without masking the guard failure."""
    if backend is None:
        return
    try:
        incident = json.loads((state_dir / "incident.json").read_text())
        since = incident.get("created_at")
        if since is None:
            return
        path = state_dir / "startup-failure.json"
        previous = json.loads(path.read_text()) if path.exists() else {}
        if previous.get("token") == incident["token"]:
            finding = previous["finding"]
        else:
            finding = backend.startup_failure(since)
            if not finding:
                return
            atomic_json(path, {"token": incident["token"], "finding": finding})
        print(
            "Earlier K3s startup failure: "
            + finding["cause"]
            + "; inspect k3s.service journal and preserve Node snapshots. "
            "A later etcd connection failure may follow service shutdown."
        )
    except (OSError, ValueError, KeyError, TypeError, Stop):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=[
            "enroll",
            "prepare-resolver",
            "enroll-peer",
            "resume-peer-enrollment",
            "arm",
            "pre-start",
            "post-start",
            "watch",
            "resume",
            "resume-transport",
            "resume-node-address",
        ],
    )
    parser.add_argument("--enrollment", type=Path, default=ENROLLMENT)
    parser.add_argument("--request", type=Path)
    parser.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/sugarkube/ethernet-recovery")
    )
    args = parser.parse_args()
    backend = None
    try:
        require(os.geteuid() == 0, "root-owned enrollment and state required")
        if args.phase in ("enroll", "prepare-resolver"):
            require(args.request is not None, "explicit healthy-time enrollment request required")
            print(
                prepare_resolver(args.request)
                if args.phase == "prepare-resolver"
                else enroll(args.request, args.enrollment)
            )
            return 0
        trusted_file(args.enrollment)
        enrollment = json.loads(args.enrollment.read_text())
        private_state(args.state_dir)
        backend = Backend(enrollment)
        with (args.state_dir / "lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            recovery_class = DualRecovery if enrollment["schema_version"] == 2 else Recovery
            recovery = recovery_class(enrollment, backend, args.state_dir / "incident.json")
            require(
                enrollment["schema_version"] == 2
                or args.phase in ("pre-start", "post-start", "watch", "resume"),
                "phase requires version 2 enrollment",
            )
            action = {
                "pre-start": recovery.pre_start,
                "post-start": recovery.post_start,
                "watch": recovery.watch,
                "resume": recovery.resume,
                **(
                    {
                        "enroll-peer": recovery.enroll_peer,
                        "arm": recovery.arm,
                        "resume-peer-enrollment": lambda: recovery.enroll_peer(resume=True),
                        "resume-transport": recovery.resume_transport,
                        "resume-node-address": recovery.resume_node_address,
                    }
                    if enrollment["schema_version"] == 2
                    else {}
                ),
            }[args.phase]()
            if action in ("peer-enrolled", "armed"):
                enrollment["dual_enrolled" if action == "peer-enrolled" else "armed"] = True
                atomic_json(args.enrollment, enrollment)
        # Release flock before queuing the systemd restart; its pre-start takes the same lock.
        if action in ("restart-requested", "operator-restart-requested"):
            backend.restart(operator=action == "operator-restart-requested")
        print(action)
        return 0
    except Stop as exc:
        report_startup_failure(backend, args.state_dir)
        print(f"Ethernet recovery blocked: {exc}. Preserve the incident for operator review.")
        return 2
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        yaml.YAMLError,
    ):
        print("Ethernet recovery blocked; preserve the incident and obtain operator review.")
        return 2
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
