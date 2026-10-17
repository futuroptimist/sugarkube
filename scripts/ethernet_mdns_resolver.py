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


class Unavailable(ValueError):
    """No single fresh interface-local locator can be established."""


def service_files(enrollment):
    """Inactive installation only. No daemon-reload, restart or host DNS edit."""
    Resolver(enrollment)  # Validate the exact allowlist before rendering it.
    if Path(enrollment["pod_resolv_source"]) not in POD_SOURCES:
        raise Unavailable("unsupported original kubelet resolver source")
    config = {
        "schema_version": 2,
        "interface": enrollment["interface"],
        "pod_resolv_source": enrollment["pod_resolv_source"],
        "members": [{"hostname": m["hostname"]} for m in enrollment["members"]],
    }
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
            f"ExecStart=/usr/bin/python3 -I {RUNTIME} --enrollment {CONFIG}\n"
            "TimeoutStartSec=15\nTimeoutStopSec=5\nRestart=on-failure\nRestartSec=10\n"
        ).encode(),
        HOOK: (
            "# Managed by ethernet_quorum_recover.py\n[Unit]\n"
            "Requires=sugarkube-ethernet-dns.service\nAfter=sugarkube-ethernet-dns.service\n"
            "[Service]\n"
            f"BindReadOnlyPaths={STATE}/process-resolv.conf:/etc/resolv.conf\n"
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


def publish_config(source=HOST_RESOLV, state=STATE, pod_source=None):
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
    serve(Resolver(enrollment), refresh=lambda: publish_config(pod_source=pod_source))


if __name__ == "__main__":
    main()
