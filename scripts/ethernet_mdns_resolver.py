#!/usr/bin/env python3
"""Loopback DNS for enrolled Ethernet mDNS names, with ordinary DNS forwarding.

Answers are untrusted locators. Only consumers using the enrolled hostname, CA
and exact member/cluster identity may authorize a membership mutation.
No membership, API, database or certificate operation occurs in this service.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import select
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dnslib import QTYPE, RCODE, RR, A, DNSRecord

LISTEN = "127.0.0.55"
PORT = 53
WINDOW = 1.0
MAX_PACKET = 4096
MAX_PACKETS = 128
STATE = Path("/run/sugarkube-ethernet-dns")
HOST_RESOLV = Path("/etc/resolv.conf")
RUNTIME = Path("/usr/local/libexec/sugarkube/ethernet_mdns_resolver.py")
CONFIG = Path("/etc/rancher/k3s/sugarkube-dns.json")
SERVICE = Path("/etc/systemd/system/sugarkube-ethernet-dns.service")
HOOK = Path("/etc/systemd/system/k3s.service.d/25-sugarkube-resolver.conf")
KUBELET_CONFIG = Path("/etc/rancher/k3s/config.yaml.d/21-sugarkube-resolver.yaml")
POD_SOURCES = (
    HOST_RESOLV,
    Path("/run/systemd/resolve/resolv.conf"),
    Path("/var/lib/rancher/k3s/agent/etc/resolv.conf"),
)
RESOLVED = Path("/run/systemd/resolve")
VIEW_KIND = "resolved-stub-directory-v1"
RESOLVED_ENTRIES = {
    "resolv.conf",
    "stub-resolv.conf",
    "io.systemd.Resolve",
    "io.systemd.Resolve.Monitor",
}


def directory_identity(path, *, root_owned=False):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 or (root_owned and info.st_uid != 0):
        raise Unavailable("untrusted resolver directory")
    return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid, "gid": info.st_gid}


def resolved_layout(root=Path("/")):
    """Only the observed resolved stub layout is supported, never an arbitrary parent."""
    host = root / RESOLVED.relative_to("/")
    link = os.readlink(root / HOST_RESOLV.relative_to("/"))
    if link != "../run/systemd/resolve/stub-resolv.conf":
        raise Unavailable("unsupported resolver symlink layout")
    owner = directory_identity(host)
    for path in host.iterdir():
        # systemd v255 tempfn_random(): these unpublished files are not IPC entries.
        temporary = re.fullmatch(r"\.\#(?:stub-resolv|resolv)\.conf[0-9a-f]{16}", path.name)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if temporary:
                continue
            raise
        socket_entry = path.name.startswith("io.systemd.")
        if (
            (path.name not in RESOLVED_ENTRIES and not temporary)
            or info.st_uid != owner["uid"]
            or not (stat.S_ISSOCK(info.st_mode) if socket_entry else stat.S_ISREG(info.st_mode))
            or (not socket_entry and info.st_mode & 0o022)
        ):
            raise Unavailable("unsupported resolved directory entry")
    for name in ("stub-resolv.conf", "resolv.conf"):
        if not (host / name).is_file():
            raise Unavailable("missing original resolved file")
    return {"kind": VIEW_KIND, "symlink": link, "uid": owner["uid"], "gid": owner["gid"]}


def view_enabled(enrollment):
    view = enrollment.get("resolver_view")
    if view is None:
        return False  # Existing enrollment is not silently migrated.
    if (
        not isinstance(view, dict)
        or set(view) != {"kind", "symlink", "uid", "gid"}
        or view["kind"] != VIEW_KIND
        or view["symlink"] != "../run/systemd/resolve/stub-resolv.conf"
        or any(type(view[key]) is not int or view[key] < 0 for key in ("uid", "gid"))
    ):
        raise Unavailable("unsupported enrolled resolver view")
    return True


def view_links():
    # Relative links also remain inspectable through /proc/PID/root.
    return {
        name: f"../../{STATE.name}/host-resolved/{name}"
        for name in RESOLVED_ENTRIES - {"stub-resolv.conf"}
    }


def view_identity(root=Path("/")):
    state = root / STATE.relative_to("/")
    host = root / RESOLVED.relative_to("/")
    return {
        "state": directory_identity(state, root_owned=True),
        "view": directory_identity(state / "resolved", root_owned=True),
        "alias": directory_identity(state / "host-resolved", root_owned=True),
        "host": directory_identity(host),
    }


def check_view(enrollment, root=Path("/")):
    state = root / STATE.relative_to("/")
    if resolved_layout(root) != enrollment["resolver_view"]:
        raise Unavailable("original resolver layout changed")
    marker = state / "view-identity.json"
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise Unavailable("untrusted resolver view identity")
    identity = view_identity(root)
    if json.loads(marker.read_text()) != identity:
        raise Unavailable("resolver directory identity changed; explicit migration required")
    view = state / "resolved"
    if {p.name for p in view.iterdir()} != RESOLVED_ENTRIES:
        raise Unavailable("unexpected resolver view entries")
    for name, target in view_links().items():
        if os.readlink(view / name) != target:
            raise Unavailable("resolver compatibility link changed")
    info = (view / "stub-resolv.conf").lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise Unavailable("untrusted process resolver view")
    return identity


def initialize_view(enrollment):
    """Keep directory inodes across service restarts; interrupted setup is not repaired."""
    if resolved_layout() != enrollment["resolver_view"]:
        raise Unavailable("original resolver layout changed")
    directory_identity(STATE, root_owned=True)
    marker = STATE / "view-identity.json"
    if marker.exists() or marker.is_symlink():
        check_view(enrollment)
        return
    view, alias = STATE / "resolved", STATE / "host-resolved"
    if any(path.exists() or path.is_symlink() for path in (view, alias)):
        raise Unavailable("unfinished resolver view setup; explicit reconciliation required")
    view.mkdir(mode=0o755)
    alias.mkdir(mode=0o755)
    for name, target in view_links().items():
        (view / name).symlink_to(target)
    atomic(view / "stub-resolv.conf", resolver_text(HOST_RESOLV.read_text())[1])
    atomic(marker, json.dumps(view_identity(), sort_keys=True) + "\n")
    check_view(enrollment)


def resolver_bindings(enrollment):
    if view_enabled(enrollment):
        # systemd sorts destination paths: preserve the original directory before shadowing it.
        return [f"{RESOLVED}:{STATE}/host-resolved:norbind", f"{STATE}/resolved:{RESOLVED}:norbind"]
    return [f"{STATE}/process-resolv.conf:/etc/resolv.conf"]


def check_process_view(enrollment, pid, dns_pid, expected):
    """Validate the mount actually used by K3s, not just rendered systemd properties."""
    original = Path(f"/proc/{dns_pid}/root")
    identity = check_view(enrollment, original)
    root = Path(f"/proc/{pid}/root")
    if os.readlink(f"/proc/{pid}/ns/mnt") == os.readlink(f"/proc/{dns_pid}/ns/mnt"):
        raise Unavailable("K3s resolver namespace is not isolated")
    expected_mounts = {
        str(RESOLVED): identity["view"],
        str(STATE / "host-resolved"): identity["host"],
    }
    mounts = {path: [] for path in expected_mounts}
    for line in Path(f"/proc/{pid}/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) < 7 or "-" not in fields:
            raise Unavailable("invalid K3s mount information")
        target = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        for path in mounts:
            if target.startswith(path + "/"):
                raise Unavailable("unexpected child mount in resolver view")
            if target == path:
                mounts[path].append(fields[5].split(","))
    for path, pinned in expected_mounts.items():
        actual = root / path.lstrip("/")
        if (
            len(mounts[path]) != 1
            or "ro" not in mounts[path][0]
            or directory_identity(actual) != pinned
        ):
            raise Unavailable("K3s resolver directory mount drifted")
    if os.readlink(root / "etc/resolv.conf") != enrollment["resolver_view"]["symlink"]:
        raise Unavailable("K3s resolver symlink drifted")
    if (root / RESOLVED.relative_to("/") / "stub-resolv.conf").read_text() != expected:
        raise Unavailable("running K3s resolver view drifted; explicit restart required")
    # Check again after inspecting the running view; never accept a changed generation.
    if check_view(enrollment, original) != identity:
        raise Unavailable("resolver directory changed during observation")


class Unavailable(ValueError):
    """No single fresh interface-local locator can be established."""


def service_files(enrollment):
    """Inactive installation only. No daemon-reload, restart or host DNS edit."""
    Resolver(enrollment)  # Validate the exact allowlist before rendering it.
    if Path(enrollment["pod_resolv_source"]) not in POD_SOURCES:
        raise Unavailable("unsupported original kubelet resolver source")
    directory_view = view_enabled(enrollment)
    config = {
        "schema_version": 2,
        "interface": enrollment["interface"],
        "pod_resolv_source": enrollment["pod_resolv_source"],
        "members": [{"hostname": m["hostname"]} for m in enrollment["members"]],
    }
    if directory_view:
        config["resolver_view"] = enrollment["resolver_view"]
    preserve = "RuntimeDirectoryPreserve=yes\n" if directory_view else ""
    return {
        RUNTIME: Path(__file__).read_bytes(),
        CONFIG: (json.dumps(config, sort_keys=True) + "\n").encode(),
        SERVICE: (
            "# Managed by ethernet_quorum_recover.py\n[Unit]\n"
            "Description=Enrolled Ethernet mDNS resolver for K3s\n"
            "After=network-online.target\nBefore=k3s.service\n"
            "StartLimitIntervalSec=300\nStartLimitBurst=3\n"
            "[Service]\nType=notify\nNotifyAccess=main\nUser=root\nUMask=0022\n"
            "RuntimeDirectory=sugarkube-ethernet-dns\nRuntimeDirectoryMode=0755\n"
            f"{preserve}"
            f"ExecStart=/usr/bin/python3 -I {RUNTIME} --enrollment {CONFIG}\n"
            "TimeoutStartSec=15\nTimeoutStopSec=5\nRestart=on-failure\nRestartSec=10\n"
        ).encode(),
        HOOK: (
            "# Managed by ethernet_quorum_recover.py\n[Unit]\n"
            "Requires=sugarkube-ethernet-dns.service\nAfter=sugarkube-ethernet-dns.service\n"
            "[Service]\n"
            + "".join(f"BindReadOnlyPaths={binding}\n" for binding in resolver_bindings(enrollment))
        ).encode(),
        KUBELET_CONFIG: (
            "# Managed by ethernet_quorum_recover.py\n"
            f'resolv-conf: "{STATE}/kubelet-resolv.conf"\n'
        ).encode(),
    }


def query_stub(host):
    query = DNSRecord.question(host, "A")
    reply = DNSRecord.parse(query.send(LISTEN, PORT, timeout=2))
    if (
        not reply.header.qr
        or reply.header.id != query.header.id
        or reply.header.rcode
        or reply.questions != query.questions
        or len(reply.rr) != 1
    ):
        raise Unavailable("no unambiguous local resolver answer")
    record = reply.rr[0]
    if (
        record.rtype != QTYPE.A
        or record.rclass != 1
        or record.ttl != 1
        or record.rname != query.q.qname
    ):
        raise Unavailable("unexpected local resolver answer")
    return str(ipaddress.IPv4Address(str(record.rdata)))


def notify_ready():
    destination = os.environ.get("NOTIFY_SOCKET")
    if destination:
        if destination.startswith("@"):
            destination = "\0" + destination[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(b"READY=1", destination)


def interface_state(interface):
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", interface) or interface.startswith("wl"):
        raise Unavailable("invalid Ethernet interface")
    rows = json.loads(
        subprocess.run(
            ["/usr/sbin/ip", "-j", "-4", "addr", "show", "dev", interface, "scope", "global"],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        ).stdout
    )
    addresses = [
        a
        for row in rows
        for a in row["addr_info"]
        if a["scope"] == "global"
        and not any(
            a.get(k, False) or k in a.get("flags", [])
            for k in ("secondary", "tentative", "deprecated")
        )
    ]
    if len(rows) != 1 or len(addresses) != 1:
        raise Unavailable("one primary Ethernet IPv4 required")
    address = ipaddress.IPv4Address(addresses[0]["local"])
    network = ipaddress.IPv4Network(f"{address}/{addresses[0]['prefixlen']}", strict=False)
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise Unavailable("invalid interface address")
    return str(address), network, rows[0]["ifindex"]


def candidate_answers(query, data, ancillary, flags, peer, network):
    """Validate legacy-unicast mDNS replies, including interface-local IP TTL."""
    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or peer[1] != 5353:
        return []
    hops = [
        struct.unpack("i", value[:4])[0]
        for level, kind, value in ancillary
        if level == socket.IPPROTO_IP and kind == socket.IP_TTL and len(value) >= 4
    ]
    if hops != [255] or ipaddress.IPv4Address(peer[0]) not in network:
        return []
    try:
        reply = DNSRecord.parse(data)
    except Exception:
        return []
    if (
        not reply.header.qr
        or reply.header.id != query.header.id
        or reply.header.rcode
        or reply.header.opcode
        or reply.header.tc
        or reply.questions != query.questions
    ):
        return []
    name = str(query.q.qname).lower()
    result = []
    for record in reply.rr + reply.ar:
        if (
            str(record.rname).lower() != name
            or record.rtype != QTYPE.A
            or record.rclass & 0x7FFF != 1
        ):
            continue
        address = ipaddress.IPv4Address(str(record.rdata))
        if address not in network or address in (
            network.network_address,
            network.broadcast_address,
        ):
            raise Unavailable("out-of-scope answer for enrolled name")
        result.append((str(address), record.ttl))
    return result


def discover(name, interface, *, state=interface_state, window=WINDOW):
    before = state(interface)
    address, network, _ = before
    query = DNSRecord.question(name, "A")
    seen, withdrawn = set(), set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b"\0")
        sock.bind((address, 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(address))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setsockopt(socket.IPPROTO_IP, 12, 1)  # Linux IP_RECVTTL
        sock.sendto(query.pack(), ("224.0.0.251", 5353))
        end, packets = time.monotonic() + window, 0
        while time.monotonic() < end:
            sock.settimeout(max(0.001, end - time.monotonic()))
            try:
                data, ancillary, flags, peer = sock.recvmsg(MAX_PACKET, 128)
            except socket.timeout:
                break
            packets += 1
            if packets > MAX_PACKETS:
                raise Unavailable("mDNS observation exceeded packet limit")
            for candidate, ttl in candidate_answers(query, data, ancillary, flags, peer, network):
                (seen if ttl else withdrawn).add(candidate)
            if len(seen) > 1 or withdrawn:
                raise Unavailable("ambiguous or withdrawn mDNS locator")
    if state(interface) != before or len(seen) != 1:
        raise Unavailable("interface changed or no fresh locator")
    return next(iter(seen))


def resolver_text(text):
    """Retain search/options while replacing only the process-view nameservers."""
    upstreams, lines = [], []
    if len(text.encode()) > 16384:
        raise Unavailable("oversized resolver configuration")
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split(";", 1)[0].split()
        if fields and fields[0] == "nameserver":
            if len(fields) != 2:
                raise Unavailable("ambiguous upstream nameserver")
            address = ipaddress.ip_address(fields[1])
            if str(address) == LISTEN or address.is_unspecified or address.is_multicast:
                raise Unavailable("recursive or invalid upstream resolver")
            upstreams.append(str(address))
        else:
            lines.append(line)
    if not 1 <= len(upstreams) <= 3 or len(set(upstreams)) != len(upstreams):
        raise Unavailable("one to three distinct upstream resolvers required")
    return upstreams, "\n".join([f"nameserver {LISTEN}", *lines]) + "\n"


def pod_resolver_text(text):
    upstreams, _ = resolver_text(text)
    # Match K3s isValidNameserver: private global-unicast LAN DNS is valid,
    # loopback/link-local is not (except its documented cloud metadata address).
    for value in upstreams:
        address = ipaddress.ip_address(value)
        if value != "169.254.169.254" and (
            address.is_loopback or address.is_link_local or value == "255.255.255.255"
        ):
            raise Unavailable("pod resolver cannot use host loopback/link-local DNS")
    return text


def select_pod_source(candidates=POD_SOURCES):
    for path in candidates:
        try:
            pod_resolver_text(path.read_text())
            return path
        except (OSError, ValueError):
            continue
    # Never invent a public fallback or silently change an owner's pod DNS.
    raise Unavailable("no existing valid K3s kubelet resolver source")


def read_exact(sock, count):
    chunks = bytearray()
    while len(chunks) < count:
        data = sock.recv(count - len(chunks))
        if not data:
            raise Unavailable("DNS TCP session ended")
        chunks.extend(data)
    return bytes(chunks)


def forward(data, upstreams, tcp=False):
    query = DNSRecord.parse(data)
    for upstream in upstreams:
        family = socket.AF_INET6 if ":" in upstream else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
                sock.settimeout(0.6)
                sock.connect((upstream, 53))
                if tcp:
                    sock.sendall(struct.pack("!H", len(data)) + data)
                    length = struct.unpack("!H", read_exact(sock, 2))[0]
                    if length > 65535:
                        raise Unavailable("oversized upstream reply")
                    answer = read_exact(sock, length)
                else:
                    sock.sendall(data)
                    answer = sock.recv(65535)
            reply = DNSRecord.parse(answer)
            if (
                not reply.header.qr
                or reply.header.id != query.header.id
                or reply.questions != query.questions
            ):
                raise Unavailable("upstream DNS response mismatch")
            if reply.header.tc and not tcp:
                return forward(data, [upstream], tcp=True)
            return answer
        except (OSError, ValueError):
            continue
    raise Unavailable("ordinary DNS upstream unavailable")


class Resolver:
    def __init__(self, enrollment, *, lookup=discover, upstream=HOST_RESOLV, send=forward):
        self.interface = enrollment["interface"]
        self.hosts = frozenset(member["hostname"] for member in enrollment["members"])
        if len(self.hosts) != 3 or any(
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.local", h) for h in self.hosts
        ):
            raise Unavailable("three exact enrolled mDNS names required")
        self.lookup, self.upstream, self.send = lookup, upstream, send

    def answer(self, data, tcp=False):
        try:
            query = DNSRecord.parse(data)
            reply = query.reply()
            if (
                query.header.qr
                or query.header.opcode
                or len(query.questions) != 1
                or query.q.qclass != 1
                or len(data) > MAX_PACKET
            ):
                reply.header.rcode = RCODE.FORMERR
                return reply.pack()
            name = str(query.q.qname).rstrip(".").lower()
            if name not in self.hosts:
                if name == "local" or name.endswith(".local"):
                    reply.header.rcode = RCODE.REFUSED
                    return reply.pack()
                upstreams, _ = resolver_text(self.upstream.read_text())
                answer = self.send(data, upstreams, tcp=tcp)
                limits = [record.rclass for record in query.ar if record.rtype == QTYPE.OPT]
                limit = min(MAX_PACKET, max(512, limits[0] if limits else 512))
                if not tcp and len(answer) > limit:
                    truncated = DNSRecord.parse(answer)
                    truncated.rr, truncated.auth, truncated.ar = [], [], []
                    truncated.header.tc = 1
                    return truncated.pack()
                return answer
            reply.header.ra = 0
            if query.q.qtype == QTYPE.AAAA:
                return reply.pack()  # Explicit IPv4-only enrolled peer policy.
            if query.q.qtype != QTYPE.A:
                reply.header.rcode = RCODE.REFUSED
                return reply.pack()
            address = self.lookup(name, self.interface)
            reply.add_answer(RR(query.q.qname, QTYPE.A, rdata=A(address), ttl=1))
            return reply.pack()
        except Exception:
            try:
                reply = DNSRecord.parse(data).reply()
                reply.header.rcode = RCODE.SERVFAIL
                return reply.pack()
            except Exception:
                return b""


def atomic(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".dns-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_config(source=HOST_RESOLV, state=STATE, pod_source=None, enrollment=None):
    directory_view = enrollment is not None and view_enabled(enrollment)
    if directory_view:
        check_view(enrollment)
    text = source.read_text()
    _, process = resolver_text(text)
    pod_text = pod_resolver_text((pod_source or source).read_text())
    for name, value in (
        ("upstream-resolv.conf", text),
        ("process-resolv.conf", process),
        ("kubelet-resolv.conf", pod_text),
    ):
        path = state / name
        if not path.exists() or path.read_text() != value:
            atomic(path, value)
    if directory_view:
        view = state / "resolved" / "stub-resolv.conf"
        if view.read_text() != process:
            atomic(view, process)
        check_view(enrollment)


def serve(
    resolver, *, address=LISTEN, port=PORT, stop=None, refresh=publish_config, ready=notify_ready
):
    """Fixed worker pool, bounded admission and deadlines; no thread per packet."""
    stop = stop or threading.Event()
    slots = threading.BoundedSemaphore(8)
    refresh()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp,
        ThreadPoolExecutor(max_workers=4) as workers,
    ):
        udp.bind((address, port))
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind((address, udp.getsockname()[1]))
        tcp.listen(8)
        ready()  # Files and both sockets exist before K3s creates its private DNS view.
        last_refresh = time.monotonic()

        def process(data, peer, client=None):
            try:
                if not ipaddress.ip_address(peer[0]).is_loopback:
                    return
                if client is not None:
                    client.settimeout(2)
                    length = struct.unpack("!H", read_exact(client, 2))[0]
                    if not 0 < length <= MAX_PACKET:
                        return
                    data = read_exact(client, length)
                answer = resolver.answer(data, tcp=client is not None)
                if answer:
                    if client is None:
                        udp.sendto(answer, peer)
                    else:
                        client.sendall(struct.pack("!H", len(answer)) + answer)
            except (OSError, ValueError):
                pass
            finally:
                if client is not None:
                    client.close()
                slots.release()

        while not stop.is_set():
            if time.monotonic() - last_refresh >= 1:
                refresh()
                last_refresh = time.monotonic()
            readable, _, _ = select.select([udp, tcp], [], [], 0.2)
            for sock in readable:
                if sock is udp:
                    data, peer = udp.recvfrom(MAX_PACKET + 1)
                    client = None
                else:
                    client, peer = tcp.accept()
                    data = b""
                if slots.acquire(blocking=False):
                    workers.submit(process, data, peer, client)
                elif client is not None:
                    client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enrollment", type=Path, required=True)
    args = parser.parse_args()
    enrollment = json.loads(args.enrollment.read_text())
    if enrollment["schema_version"] != 2:
        raise Unavailable("resolver requires version 2 enrollment")
    pod_source = Path(enrollment["pod_resolv_source"])
    if pod_source not in POD_SOURCES:
        raise Unavailable("unsupported original kubelet resolver source")
    # systemd creates the root-owned runtime directory; never repair ownership.
    if STATE.is_symlink() or STATE.stat().st_uid != 0 or STATE.stat().st_mode & 0o022:
        raise Unavailable("untrusted resolver runtime directory")
    directory_view = view_enabled(enrollment)
    if directory_view:
        initialize_view(enrollment)
    serve(
        Resolver(enrollment),
        refresh=lambda: (
            publish_config(pod_source=pod_source, enrollment=enrollment)
            if directory_view
            else publish_config(pod_source=pod_source)
        ),
    )


if __name__ == "__main__":
    main()
