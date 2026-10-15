#!/usr/bin/env python3
"""Opt-in, fail-closed recovery of one enrolled etcd member before K3s starts.

No reset, membership add/remove, database operation or status patch exists here.
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
    require(type(e["schema_version"]) is int and e["schema_version"] == 1, "unsupported enrollment")
    require(e["k3s_version"] in VERSIONS, "unqualified K3s version")
    require(re.fullmatch(r"[a-zA-Z0-9_.:-]+", e["interface"]), "invalid interface")
    require(not e["interface"].startswith("wl"), "Ethernet only")
    require(len(e["members"]) == 3, "exactly three enrolled voters required")
    ids, hosts, names = set(), set(), set()
    for member in e["members"]:
        require(re.fullmatch(r"[1-9][0-9]*", member["id"]), "decimal member ID required")
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.local", member["hostname"]), "invalid hostname")
        require(member["name"] and member["node_uid"], "member and Node identity required")
        ids.add(member["id"])
        hosts.add(member["hostname"])
        names.add(member["name"])
    require(len(ids) == len(hosts) == len(names) == 3, "duplicate enrollment identity")
    require(e["local_member_id"] in ids, "local member not enrolled")
    require(re.fullmatch(r"[1-9][0-9]*", e["cluster_id"]), "decimal cluster ID required")
    require(e["verified_backup"] is True, "operator-verified recovery backup required")
    ipaddress.IPv4Address(e["local_ipv4"])
    require(e["files"], "effective configuration files must be enrolled")
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

    def connect_peer(self, address):
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            raw.settimeout(5)
            raw.setsockopt(
                socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.e["interface"].encode() + b"\0"
            )
            raw.bind((self.address(), 0))
            raw.connect((address, 2379))
            return raw
        except Exception:
            raw.close()
            raise

    def request(self, host, route, payload):
        """Use one pinned-address, hostname-verified TLS session per enrolled voter.

        Never reconnect automatically between health proof and a mutation. Every
        response must bind its cluster/member identity, including linearizable reads.
        """
        expected = next(m for m in self.e["members"] if m["hostname"] == host)
        if host not in self.connections:
            address = self.resolve(host)
            tls = self.e["etcd_tls"]
            context = ssl.create_default_context(cafile=tls["ca"])
            context.load_cert_chain(tls["cert"], tls["key"])
            connection = http.client.HTTPConnection(host, 2379, timeout=5)
            raw = self.connect_peer(address)
            try:
                connection.sock = context.wrap_socket(raw, server_hostname=host)
            except Exception:
                raw.close()
                raise
            self.connections[host] = connection
        connection = self.connections[host]
        require(connection.sock is not None, "authenticated session ended; no automatic reconnect")
        try:
            connection.request(
                "POST", route, json.dumps(payload), {"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            require(
                response.status == 200 and len(raw) <= 1024 * 1024, "etcd gateway request failed"
            )
            result = json.loads(raw)
            require(
                str(result["header"]["cluster_id"]) == self.e["cluster_id"]
                and str(result["header"]["member_id"]) == expected["id"],
                "authenticated response identity mismatch",
            )
            return result
        except Exception:
            connection.close()
            raise

    def etcd(self, host, *args, input_text=None):
        if args == ("member", "list"):
            return self.request(host, "/v3/cluster/member/list", {})
        if args[:2] == ("member", "update"):
            return self.request(
                host,
                "/v3/cluster/member/update",
                {"ID": str(int(args[2], 16)), "peerURLs": [args[3].removeprefix("--peer-urls=")]},
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
        if args == ("get", KEY):
            return self.request(host, "/v3/kv/range", {"key": encode(KEY), "serializable": False})
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
                    set(paths) <= {str(HOOK), NETWORK_HOOK},
                    "custom drop-ins require operator migration",
                )
                line = "DropInPaths=" + " ".join(
                    p for p in paths if p not in (str(HOOK), NETWORK_HOOK)
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

    def config(self):
        inventory = self.inventory()
        require(
            all(inventory[key] == self.e[key] for key in inventory),
            "enrolled machine, configuration or trust material changed",
        )

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
                "/var/log/sugarkube",
                "/usr/sbin/ip",
            ]
        )

    def active(self):
        return self.command(["/usr/bin/systemctl", "is-active", "k3s.service"]).strip() == "active"

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
        rows = self.command(["/usr/bin/avahi-resolve-host-name", "-4", host]).splitlines()
        require(len(rows) == 1, "ambiguous mDNS result")
        fields = rows[0].split()
        require(len(fields) == 2 and fields[0].lower() == host, "mDNS name mismatch")
        ip = str(ipaddress.IPv4Address(fields[1]))
        # etcdctl resolves the authenticated DNS name through NSS; corroborate its locator.
        rows = self.command(["/usr/bin/getent", "ahostsv4", host]).splitlines()
        addresses = {line.split()[0] for line in rows}
        require(addresses == {ip}, "mDNS and NSS disagree")
        if host in self.locators:
            require(self.locators[host] == ip, "address changed during recovery")
        self.locators[host] = ip
        return ip

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
            require(len(entry["peerURLs"]) == 1, "one peer URL per voter required")
        return actual

    def prove(self, include_local=False):
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
        members = self.membership()
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


def enroll(request, destination):
    """Explicit healthy-time enrollment; install inactive hooks, never reload/start."""
    require(destination == ENROLLMENT, "only the standard enrollment path is supported")
    trusted_file(request)
    e = json.loads(request.read_text())
    backend = Backend(e)
    e.update(backend.inventory())
    e["local_ipv4"] = backend.address()
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
            members[member["id"]]["peerURLs"] == [f"https://{address}:2380"],
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
    require(
        ip == e["local_ipv4"] and backend.inventory() == {k: e[k] for k in backend.inventory()},
        "enrollment inputs changed",
    )
    require(backend.running() == running, "K3s process changed during enrollment")
    invocation = f"/usr/bin/python3 -I {RUNTIME}"
    enrollment_arg = f"--enrollment {ENROLLMENT}"
    files = {
        RUNTIME: Path(__file__).read_bytes(),
        HOOK: (
            "# Managed by ethernet_quorum_recover.py\n[Service]\n"
            f"ExecStartPre=/usr/bin/timeout 180s {invocation} pre-start {enrollment_arg}\n"
            f"ExecStartPost=-/usr/bin/timeout 60s {invocation} post-start {enrollment_arg}\n"
        ).encode(),
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
    # Do all conflict checks before writing. Failed installation is never enabled.
    for path in [destination, *files]:
        require(
            not path.exists() and not path.is_symlink(),
            "existing enrollment/hook must be reconciled",
        )
    # The K3s hook is the activation boundary: a reboot discovers it even without
    # daemon-reload. Persist every prerequisite before making that hook visible.
    hook_content = files.pop(HOOK)
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, content)
        path.chmod(0o644)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(destination, e)
    HOOK.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(HOOK, hook_content)
    HOOK.chmod(0o644)
    return "enrolled; hooks and timer installed but not reloaded or enabled"


def private_state(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    trusted_file(path)
    info = path.lstat()
    require(
        not path.is_symlink() and info.st_uid == 0 and info.st_mode & 0o077 == 0,
        "untrusted journal directory",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["enroll", "pre-start", "post-start", "watch", "resume"])
    parser.add_argument("--enrollment", type=Path, default=ENROLLMENT)
    parser.add_argument("--request", type=Path)
    parser.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/sugarkube/ethernet-recovery")
    )
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, "root-owned enrollment and state required")
        if args.phase == "enroll":
            require(args.request is not None, "explicit healthy-time enrollment request required")
            print(enroll(args.request, args.enrollment))
            return 0
        trusted_file(args.enrollment)
        enrollment = json.loads(args.enrollment.read_text())
        private_state(args.state_dir)
        backend = Backend(enrollment)
        with (args.state_dir / "lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            recovery = Recovery(enrollment, backend, args.state_dir / "incident.json")
            action = {
                "pre-start": recovery.pre_start,
                "post-start": recovery.post_start,
                "watch": recovery.watch,
                "resume": recovery.resume,
            }[args.phase]()
        # Release flock before queuing the systemd restart; its pre-start takes the same lock.
        if action in ("restart-requested", "operator-restart-requested"):
            backend.restart(operator=action == "operator-restart-requested")
        print(action)
        return 0
    except Stop as exc:
        print(f"Ethernet recovery blocked: {exc}. Preserve the incident for operator review.")
        return 2
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        http.client.HTTPException,
        yaml.YAMLError,
    ):
        print("Ethernet recovery blocked; preserve the incident and obtain operator review.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
