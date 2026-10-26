"""Fail-closed discovery and DNS preservation, independent of etcd readiness."""

import importlib.util
import ipaddress
import socket
import struct
import threading
import time
from pathlib import Path

import pytest
from dnslib import QTYPE, RCODE, RR, A, DNSRecord

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ethernet_mdns_resolver.py"
SPEC = importlib.util.spec_from_file_location("recovery_dns", SCRIPT)
DNS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DNS)
ENROLLMENT = {
    "schema_version": 2,
    "interface": "eth0",
    "members": [{"hostname": f"pi{i}.local"} for i in range(3)],
}
NETWORK = ipaddress.IPv4Network("10.0.0.0/24")
ANCILLARY = [(socket.IPPROTO_IP, socket.IP_TTL, struct.pack("i", 255))]


def reply(query, addresses):
    result = query.reply()
    for address, ttl in addresses:
        result.add_answer(RR(query.q.qname, QTYPE.A, rdata=A(address), ttl=ttl))
    return result.pack()


def test_enrolled_lookup_withdrawal_and_no_cache():
    answers = iter(["10.0.0.21", DNS.Unavailable("withdrawn"), "10.0.0.22"])
    calls = []

    def lookup(host, interface):
        calls.append((host, interface))
        result = next(answers)
        if isinstance(result, Exception):
            raise result
        return result

    resolver = DNS.Resolver(ENROLLMENT, lookup=lookup)
    query = DNSRecord.question("pi1.local").pack()
    first = DNSRecord.parse(resolver.answer(query))
    absent = DNSRecord.parse(resolver.answer(query))
    third = DNSRecord.parse(resolver.answer(query))
    assert str(first.rr[0].rdata) == "10.0.0.21" and first.rr[0].ttl == 1
    assert absent.header.rcode == RCODE.SERVFAIL and not absent.rr
    assert str(third.rr[0].rdata) == "10.0.0.22"
    assert calls == [("pi1.local", "eth0")] * 3


@pytest.mark.parametrize(
    "name,kind,code",
    [
        ("foreign.local", "A", RCODE.REFUSED),
        ("pi1.local", "AAAA", RCODE.NOERROR),
        ("pi1.local", "TXT", RCODE.REFUSED),
        ("local", "A", RCODE.REFUSED),
    ],
)
def test_unknown_names_and_ipv6_never_discover_or_forward(name, kind, code):
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected lookup/forward")

    resolver = DNS.Resolver(ENROLLMENT, lookup=forbidden, send=forbidden)
    answer = DNSRecord.parse(resolver.answer(DNSRecord.question(name, kind).pack()))
    assert answer.header.rcode == code and not answer.rr


def test_ordinary_dns_bytes_and_current_upstream_preserved(tmp_path):
    path = tmp_path / "resolv.conf"
    path.write_text("search example.test\nnameserver 192.0.2.1\noptions edns0 timeout:2\n")
    calls = []
    query = DNSRecord.question("service.example.test").pack()
    response = DNSRecord.parse(query).reply().pack()

    def send(data, upstreams, tcp):
        calls.append((data, upstreams, tcp))
        return response

    resolver = DNS.Resolver(ENROLLMENT, upstream=path, send=send)
    assert resolver.answer(query) == response
    path.write_text("nameserver 127.0.0.53\n")
    assert resolver.answer(query, tcp=True) == response
    assert calls == [(query, ["192.0.2.1"], False), (query, ["127.0.0.53"], True)]


def test_process_view_preserves_host_and_kubelet_dns(tmp_path):
    source = tmp_path / "host-resolv.conf"
    state = tmp_path / "run"
    state.mkdir()
    original = "# DHCP supplied\nsearch lan.example\nnameserver 192.0.2.53\noptions ndots:2\n"
    source.write_text(original)
    DNS.publish_config(source, state)
    assert source.read_text() == (state / "upstream-resolv.conf").read_text() == original
    assert (state / "process-resolv.conf").read_text() == (
        "nameserver 127.0.0.55\n# DHCP supplied\nsearch lan.example\noptions ndots:2\n"
    )
    source.write_text(original.replace("192.0.2.53", "192.0.2.54"))
    DNS.publish_config(source, state)
    assert (state / "upstream-resolv.conf").read_text() == source.read_text()


def test_systemd_stub_does_not_leak_loopback_into_pod_dns(tmp_path):
    host, pod = tmp_path / "host", tmp_path / "pod"
    host.write_text("nameserver 127.0.0.53\nsearch local.example\n")
    pod.write_text("nameserver 10.0.0.53\nsearch local.example\n")
    assert DNS.select_pod_source([host, pod]) == pod
    DNS.publish_config(host, tmp_path, pod)
    assert (tmp_path / "upstream-resolv.conf").read_text() == host.read_text()
    assert (tmp_path / "kubelet-resolv.conf").read_text() == pod.read_text()
    pod.unlink()
    with pytest.raises(DNS.Unavailable, match="no existing valid"):
        DNS.select_pod_source([host, pod])


def test_inactive_service_uses_scoped_dns_and_separate_pod_source():
    e = {**ENROLLMENT, "pod_resolv_source": "/run/systemd/resolve/resolv.conf"}
    files = DNS.service_files(e)
    assert DNS.HOST_RESOLV not in files
    assert b"Type=notify" in files[DNS.SERVICE]
    assert b"StartLimitBurst=3" in files[DNS.SERVICE]
    assert (
        b"BindReadOnlyPaths=/run/sugarkube-ethernet-dns/process-resolv.conf:/etc/resolv.conf"
        in files[DNS.HOOK]
    )
    assert b"/run/sugarkube-ethernet-dns/kubelet-resolv.conf" in files[DNS.KUBELET_CONFIG]
    with pytest.raises(DNS.Unavailable):
        DNS.service_files({**e, "pod_resolv_source": "/some/credential/file"})


@pytest.mark.parametrize(
    "text",
    [
        "",
        "nameserver 127.0.0.55\n",
        "nameserver 0.0.0.0\n",
        "nameserver 192.0.2.1\nnameserver 192.0.2.1\n",
    ],
)
def test_bad_or_recursive_upstream_fails_closed(text):
    with pytest.raises(DNS.Unavailable):
        DNS.resolver_text(text)


def test_malformed_and_wrong_scope_mdns_replies():
    query = DNSRecord.question("pi1.local")
    good = reply(query, [("10.0.0.21", 120)])
    args = (query, good, ANCILLARY, 0, ("10.0.0.21", 5353), NETWORK)
    assert DNS.candidate_answers(*args) == [("10.0.0.21", 120)]
    assert DNS.candidate_answers(query, good, [], 0, ("10.0.0.21", 5353), NETWORK) == []
    assert (
        DNS.candidate_answers(
            query, good, ANCILLARY, socket.MSG_TRUNC, ("10.0.0.21", 5353), NETWORK
        )
        == []
    )
    wrong = DNSRecord.question("pi2.local")
    assert (
        DNS.candidate_answers(
            query, reply(wrong, [("10.0.0.21", 120)]), ANCILLARY, 0, ("10.0.0.21", 5353), NETWORK
        )
        == []
    )
    with pytest.raises(DNS.Unavailable, match="out-of-scope"):
        DNS.candidate_answers(
            query, reply(query, [("192.0.2.1", 120)]), ANCILLARY, 0, ("10.0.0.21", 5353), NETWORK
        )


@pytest.mark.parametrize(
    "answers,changed,allowed",
    [
        ([("10.0.0.21", 120)], False, True),
        ([("10.0.0.21", 120), ("10.0.0.22", 120)], False, False),
        ([("10.0.0.21", 120), ("10.0.0.21", 0)], False, False),
        ([], False, False),
        ([("10.0.0.21", 120)], True, False),
    ],
)
def test_discovery_ambiguity_goodbye_and_interface_change(monkeypatch, answers, changed, allowed):
    sent, options = [], []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def setsockopt(self, *args):
            options.append(args)

        def bind(self, address):
            assert address == ("10.0.0.10", 0)

        def sendto(self, data, target):
            assert target == ("224.0.0.251", 5353)
            sent.append(DNSRecord.parse(data))

        def settimeout(self, timeout):
            assert timeout > 0

        def recvmsg(self, *args):
            if answers and len(sent) == 1:
                query = sent[0]
                sent.append(None)
                return reply(query, answers), ANCILLARY, 0, ("10.0.0.21", 5353)
            raise socket.timeout()

    monkeypatch.setattr(DNS.socket, "socket", lambda *args: Socket())
    states = iter(
        [("10.0.0.10", NETWORK, 2), ("10.0.0.11" if changed else "10.0.0.10", NETWORK, 2)]
    )
    if allowed:
        assert (
            DNS.discover("pi1.local", "eth0", state=lambda interface: next(states)) == "10.0.0.21"
        )
    else:
        with pytest.raises(DNS.Unavailable):
            DNS.discover("pi1.local", "eth0", state=lambda interface: next(states))
    assert (socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"eth0\0") in options


def test_udp_tcp_service_restart_and_outage():
    resolver = DNS.Resolver(ENROLLMENT, lookup=lambda *args: "10.0.0.21")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    for _ in range(2):
        stop = threading.Event()
        worker = threading.Thread(
            target=DNS.serve,
            args=(resolver,),
            kwargs={
                "address": "127.0.0.1",
                "port": port,
                "stop": stop,
                "refresh": lambda: None,
            },
        )
        worker.start()
        try:
            query = DNSRecord.question("pi1.local")
            for _ in range(30):
                try:
                    answer = DNSRecord.parse(query.send("127.0.0.1", port, timeout=0.1))
                    break
                except socket.timeout:
                    time.sleep(0.01)
            else:
                pytest.fail("resolver did not start")
            assert str(answer.rr[0].rdata) == "10.0.0.21"
            answer = DNSRecord.parse(query.send("127.0.0.1", port, tcp=True, timeout=2))
            assert str(answer.rr[0].rdata) == "10.0.0.21"
        finally:
            stop.set()
            worker.join(timeout=3)
        assert not worker.is_alive()
        with pytest.raises(OSError):
            query.send("127.0.0.1", port, tcp=True, timeout=0.1)


@pytest.mark.parametrize("damage", [None, "id", "ttl"])
def test_stub_requires_exact_single_answer(monkeypatch, damage):
    def send(query, host, port, timeout):
        assert (host, port, timeout) == (DNS.LISTEN, DNS.PORT, 2)
        answer = query.reply()
        answer.add_answer(RR(query.q.qname, QTYPE.A, rdata=A("10.0.0.21"), ttl=1))
        if damage == "id":
            answer.header.id ^= 1
        elif damage == "ttl":
            answer.rr[0].ttl = 100
        return answer.pack()

    monkeypatch.setattr(DNSRecord, "send", send)
    if damage:
        with pytest.raises(DNS.Unavailable):
            DNS.query_stub("pi1.local")
    else:
        assert DNS.query_stub("pi1.local") == "10.0.0.21"


def test_notify_ready_uses_private_abstract_datagram(monkeypatch):
    target = "sugarkube-test-" + str(time.monotonic_ns())
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
        receiver.bind("\0" + target)
        receiver.settimeout(1)
        monkeypatch.setenv("NOTIFY_SOCKET", "@" + target)
        DNS.notify_ready()
        assert receiver.recv(100) == b"READY=1"


@pytest.mark.parametrize("damage", [None, "interface", "empty", "loopback"])
def test_interface_snapshot_is_bounded_and_primary_only(monkeypatch, damage):
    import json
    from types import SimpleNamespace

    row = {"ifindex": 3, "addr_info": [{"scope": "global", "local": "10.0.0.10", "prefixlen": 24}]}
    if damage == "empty":
        row["addr_info"] = []
    elif damage == "loopback":
        row["addr_info"][0]["local"] = "127.0.0.1"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 3 and kwargs["check"]
        return SimpleNamespace(stdout=json.dumps([row]))

    monkeypatch.setattr(DNS.subprocess, "run", run)
    if damage:
        with pytest.raises(DNS.Unavailable):
            DNS.interface_state("wlan0" if damage == "interface" else "eth0")
    else:
        assert DNS.interface_state("eth0") == ("10.0.0.10", NETWORK, 3)
    assert len(calls) == (0 if damage == "interface" else 1)


@pytest.mark.parametrize(
    "tcp,damage",
    [
        (False, None),
        (True, None),
        (False, "id"),
        (True, "eof"),
        (False, "truncate"),
        (True, "slow"),
    ],
)
def test_forward_checks_response_and_tcp_fallback(monkeypatch, tcp, damage):
    query = DNSRecord.question("example.test")
    answer = query.reply()
    answer.add_answer(RR(query.q.qname, QTYPE.A, rdata=A("192.0.2.1"), ttl=20))
    calls = []
    clock = [0.0]
    monkeypatch.setattr(DNS.time, "monotonic", lambda: clock[0])

    class Socket:
        def __init__(self, family, kind):
            self.tcp = kind == socket.SOCK_STREAM
            self.remaining = b""
            calls.append((family, kind))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, value):
            assert 0 < value <= 0.6

        def connect(self, target):
            assert target == ("::1", 53)

        def sendall(self, data):
            response = DNSRecord.parse(answer.pack())
            if damage == "id":
                response.header.id ^= 1
            if damage == "truncate" and not self.tcp:
                response.header.tc = 1
            wire = response.pack()
            self.remaining = (struct.pack("!H", len(wire)) if self.tcp else b"") + wire

        def recv(self, count):
            if damage == "eof":
                return b""
            if damage == "slow":
                clock[0] += 0.2
                count = 1
            result, self.remaining = self.remaining[:count], self.remaining[count:]
            return result

    monkeypatch.setattr(DNS.socket, "socket", Socket)
    if damage in ("id", "eof", "slow"):
        with pytest.raises(DNS.Unavailable, match="upstream unavailable"):
            DNS.forward(query.pack(), ["::1"], tcp)
    else:
        assert DNS.forward(query.pack(), ["::1"], tcp) == answer.pack()
    assert len(calls) == (2 if damage == "truncate" else 1)
    if damage == "slow":
        assert clock[0] == pytest.approx(0.6)


def test_resolver_rejects_bad_queries_and_truncates_oversized_udp(tmp_path):
    from dnslib import TXT

    with pytest.raises(DNS.Unavailable, match="three exact"):
        DNS.Resolver({**ENROLLMENT, "members": [{"hostname": "wrong"}]})
    upstream = tmp_path / "upstream"
    upstream.write_text("nameserver 192.0.2.1\n")
    query = DNSRecord.question("example.test", "TXT")
    reply = query.reply()
    for _ in range(5):
        reply.add_answer(RR(query.q.qname, QTYPE.TXT, rdata=TXT("x" * 200), ttl=10))
    resolver = DNS.Resolver(ENROLLMENT, upstream=upstream, send=lambda *a, **kw: reply.pack())
    result = DNSRecord.parse(resolver.answer(query.pack()))
    assert result.header.tc and not result.rr
    assert resolver.answer(query.pack(), tcp=True) == reply.pack()
    query.header.qr = 1
    assert DNSRecord.parse(resolver.answer(query.pack())).header.rcode == RCODE.FORMERR
    assert resolver.answer(b"broken") == b""
    for text in ("x" * 16385, "nameserver 192.0.2.1 extra\n"):
        with pytest.raises(DNS.Unavailable):
            DNS.resolver_text(text)
    mdns = DNSRecord.question("pi1.local")
    assert DNS.candidate_answers(mdns, b"broken", ANCILLARY, 0, ("10.0.0.21", 5353), NETWORK) == []
    answer = mdns.reply()
    answer.add_answer(RR("other.local", QTYPE.A, rdata=A("10.0.0.21"), ttl=1))
    assert (
        DNS.candidate_answers(mdns, answer.pack(), ANCILLARY, 0, ("10.0.0.21", 5353), NETWORK) == []
    )


def test_atomic_publish_failure_preserves_previous_generation(tmp_path, monkeypatch):
    path = tmp_path / "process-resolv.conf"
    path.write_text("previous")

    def fail(*args):
        raise OSError("publication interrupted")

    monkeypatch.setattr(DNS.os, "replace", fail)
    with pytest.raises(OSError):
        DNS.atomic(path, "next")
    assert path.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("damage", [None, "schema", "source", "state"])
def test_service_entry_validates_enrollment_and_runtime_before_serving(
    tmp_path, monkeypatch, damage
):
    import json
    import sys
    from types import SimpleNamespace

    path = tmp_path / "enrollment.json"
    e = {**ENROLLMENT, "pod_resolv_source": str(DNS.POD_SOURCES[0])}
    if damage == "schema":
        e["schema_version"] = 1
    if damage == "source":
        e["pod_resolv_source"] = "/unsupported"
    path.write_text(json.dumps(e))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--enrollment", str(path)])
    monkeypatch.setattr(
        DNS,
        "STATE",
        SimpleNamespace(
            is_symlink=lambda: False,
            stat=lambda: SimpleNamespace(st_uid=0, st_mode=0o777 if damage == "state" else 0o755),
        ),
    )
    calls = []
    monkeypatch.setattr(DNS, "publish_config", lambda **kwargs: calls.append(kwargs))

    def serve(resolver, refresh, retry_source):
        assert retry_source is False  # Legacy file-bind behavior is unchanged.
        refresh()

    monkeypatch.setattr(DNS, "serve", serve)
    if damage:
        with pytest.raises(DNS.Unavailable):
            DNS.main()
        assert calls == []
    else:
        DNS.main()
        assert calls == [{"pod_source": DNS.POD_SOURCES[0]}]


def test_resolver_cli_rejects_old_schema(tmp_path, monkeypatch):
    import json
    import runpy
    import sys

    path = tmp_path / "request"
    path.write_text(json.dumps({"schema_version": 1}))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--enrollment", str(path)])
    with pytest.raises(ValueError, match="version 2"):
        runpy.run_path(str(SCRIPT), run_name="__main__")


def test_service_releases_failed_tcp_clients_and_refreshes():
    stop = threading.Event()
    ready = threading.Event()
    refreshes = []
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    worker = threading.Thread(
        target=DNS.serve,
        args=(DNS.Resolver(ENROLLMENT, lookup=lambda *args: "10.0.0.21"),),
        kwargs={
            "address": "127.0.0.1",
            "port": port,
            "stop": stop,
            "ready": ready.set,
            "refresh": lambda: refreshes.append(time.monotonic()),
        },
    )
    worker.start()
    try:
        assert ready.wait(2)
        for prefix in (b"\0\0", b"\0"):
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                client.sendall(prefix)
                client.shutdown(socket.SHUT_WR)
                assert client.recv(1) == b""
        deadline = time.monotonic() + 3
        while len(refreshes) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(refreshes) >= 2
        query = DNSRecord.question("pi1.local")
        result = DNSRecord.parse(query.send("127.0.0.1", port, tcp=True, timeout=2))
        assert str(result.rr[0].rdata) == "10.0.0.21"
    finally:
        stop.set()
        worker.join(3)
    assert not worker.is_alive()


def test_discovery_packet_flood_fails_before_returning_locator(monkeypatch):
    received = []
    closed = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(True)

        def setsockopt(self, *args):
            pass

        def bind(self, address):
            assert address == ("10.0.0.10", 0)

        def sendto(self, data, target):
            assert target == ("224.0.0.251", 5353)
            self.packet = reply(DNSRecord.parse(data), [("10.0.0.21", 120)])

        def settimeout(self, timeout):
            assert timeout > 0

        def recvmsg(self, *args):
            received.append(True)
            assert len(received) <= DNS.MAX_PACKETS + 1
            return self.packet, ANCILLARY, 0, ("10.0.0.21", 5353)

    monkeypatch.setattr(DNS.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(DNS.time, "monotonic", lambda: 0)
    with pytest.raises(DNS.Unavailable, match="packet limit"):
        DNS.discover("pi1.local", "eth0", state=lambda _: ("10.0.0.10", NETWORK, 2))
    assert len(received) == DNS.MAX_PACKETS + 1
    assert closed == [True]


@pytest.mark.parametrize(
    "peer,count,trickle", [("192.0.2.1", 1, False), ("127.0.0.1", 9, False), ("127.0.0.1", 9, True)]
)
def test_tcp_admission_rejects_foreign_peers_and_closes_over_capacity(
    monkeypatch, peer, count, trickle
):
    from types import SimpleNamespace

    stop = threading.Event()
    query = DNSRecord.question("pi1.local").pack()
    queued, answered, clients = [], [], []
    clock = [0.0]
    monkeypatch.setattr(DNS.time, "monotonic", lambda: clock[0])

    class Client:
        def __init__(self):
            self.data = struct.pack("!H", len(query)) + query
            self.closed = False
            self.reads = 0
            self.sent = []

        def settimeout(self, value):
            assert 0 < value <= 2

        def recv(self, size):
            self.reads += 1
            if trickle:
                clock[0] += 0.5
                size = 1
            data, self.data = self.data[:size], self.data[size:]
            return data

        def sendall(self, data):
            self.sent.append(data)

        def close(self):
            assert not self.closed
            self.closed = True

    class Listener:
        def __init__(self, family, kind):
            self.kind = kind

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            assert address[0] == "127.0.0.1"

        def getsockname(self):
            return ("127.0.0.1", 12345)

        def setsockopt(self, *args):
            pass

        def listen(self, backlog):
            assert backlog == 8

        def accept(self):
            client = Client()
            clients.append(client)
            return client, (peer, 12346)

    class DeferredWorkers:
        def __init__(self, max_workers):
            assert max_workers == 4

        def __enter__(self):
            return self

        def submit(self, fn, *args):
            queued.append((fn, args))

        def __exit__(self, *args):
            # Hold admitted work until the burst has exhausted actual semaphore slots.
            if count == 9:
                assert clients[-1].closed and clients[-1].reads == 0
            for fn, args in queued:
                fn(*args)

    def readable(sockets, *args):
        stop.set()
        return [sockets[1]] * count, [], []

    def answer(data, tcp):
        assert data == query and tcp
        answered.append(data)
        return DNSRecord.parse(data).reply().pack()

    monkeypatch.setattr(DNS.socket, "socket", Listener)
    monkeypatch.setattr(DNS, "ThreadPoolExecutor", DeferredWorkers)
    monkeypatch.setattr(DNS.select, "select", readable)
    DNS.serve(
        SimpleNamespace(answer=answer),
        address="127.0.0.1",
        port=0,
        stop=stop,
        refresh=lambda: None,
        ready=lambda: None,
    )
    assert all(client.closed for client in clients)
    assert len(queued) == min(count, 8)
    if peer == "192.0.2.1":
        assert answered == [] and clients[0].reads == 0 and clients[0].sent == []
    elif trickle:
        assert answered == []
        assert all(client.reads == 4 and client.sent == [] for client in clients[:8])
        assert clock[0] == 16  # Eight slow sessions consume bounded two-second read budgets.
    else:
        assert len(answered) == 8
        assert all(len(client.sent) == 1 for client in clients[:8])
        assert clients[-1].sent == []


@pytest.mark.parametrize("budget", [0.6, 2.0])
def test_tcp_deadline_spans_header_and_trickled_body(monkeypatch, budget):
    clock = [0.0]
    timeouts = []
    payload = bytearray(b"\x00\x10" + b"x" * 16)

    class Trickle:
        def settimeout(self, value):
            timeouts.append(value)

        def recv(self, count):
            clock[0] += budget / 4
            return bytes([payload.pop(0)])

    monkeypatch.setattr(DNS.time, "monotonic", lambda: clock[0])
    sock = Trickle()
    deadline = clock[0] + budget
    length = struct.unpack("!H", DNS.read_exact(sock, 2, deadline))[0]
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        DNS.read_exact(sock, length, deadline)
    assert clock[0] == pytest.approx(budget)
    assert len(timeouts) == 4
    assert timeouts == sorted(timeouts, reverse=True)
    assert len(payload) == 14  # The slow sender cannot keep resetting the deadline.


@pytest.mark.parametrize("damage", ["empty", "missing", "malformed"])
def test_source_failure_preserves_generation_then_recovers(tmp_path, damage):
    host, pod, state = tmp_path / "host", tmp_path / "pod", tmp_path / "state"
    state.mkdir()
    host.write_text("nameserver 127.0.0.53\nsearch old\n")
    pod.write_text("nameserver 192.0.2.53\nsearch old\n")
    DNS.publish_config(host, state, pod)
    before = {p.name: (p.read_bytes(), p.stat().st_ino) for p in state.iterdir()}
    host.write_text("nameserver 127.0.0.53\nsearch renewed\n")
    if damage == "missing":
        pod.unlink()
    else:
        pod.write_text("search .\n" if damage == "empty" else "nameserver invalid\n")
    with pytest.raises(DNS.SourceUnavailable):
        DNS.publish_config(host, state, pod)
    assert {p.name: (p.read_bytes(), p.stat().st_ino) for p in state.iterdir()} == before
    pod.write_text("nameserver 192.0.2.54\nsearch renewed\n")
    DNS.publish_config(host, state, pod)
    assert (state / "kubelet-resolv.conf").read_text() == pod.read_text()
    assert (state / "process-resolv.conf").read_text() == DNS.resolver_text(host.read_text())[1]


@pytest.mark.parametrize("failure", [DNS.Unavailable("identity changed"), OSError("disk failed")])
def test_publication_and_identity_failures_are_not_retryable(tmp_path, monkeypatch, failure):
    source = tmp_path / "source"
    source.write_text("nameserver 192.0.2.53\n")

    def fail(*args):
        raise failure

    if isinstance(failure, DNS.Unavailable):
        monkeypatch.setattr(DNS, "view_enabled", lambda e: True)
        monkeypatch.setattr(DNS, "check_view", fail)
    else:
        monkeypatch.setattr(DNS, "atomic", fail)
    with pytest.raises(type(failure)) as caught:
        DNS.publish_config(source, tmp_path, enrollment={})
    assert caught.value is failure
    assert not isinstance(caught.value, DNS.SourceUnavailable)


@pytest.mark.parametrize("fatal", [None, "identity", "publication", "initial", "legacy"])
def test_running_refresh_retries_only_source_failures(monkeypatch, fatal):
    from types import SimpleNamespace

    clock = [0.0]
    stop = threading.Event()
    calls, ready, answers, closed = [], [], [], []
    query = DNSRecord.question("pi0.local").pack()

    class Listener:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append(self)

        def bind(self, *args):
            pass

        def getsockname(self):
            return ("127.0.0.1", 12345)

        def setsockopt(self, *args):
            pass

        def listen(self, *args):
            pass

        def recvfrom(self, *args):
            return query, ("127.0.0.1", 12346)

        def sendto(self, data, peer):
            answers.append(data)

    class Workers:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, *args):
            fn(*args)

    def refresh():
        calls.append(clock[0])
        if fatal == "initial":
            raise DNS.SourceUnavailable("no initial generation")
        if len(calls) == 1:
            return
        if fatal == "identity":
            raise DNS.Unavailable("identity changed")
        if fatal == "publication":
            raise OSError("publication failed")
        if len(calls) < 6:
            raise DNS.SourceUnavailable("DHCP source unavailable")
        stop.set()  # A fresh valid generation resumes without restarting the service.

    def readable(sockets, *args):
        clock[0] += 11
        return [sockets[0]], [], []

    monkeypatch.setattr(DNS.socket, "socket", Listener)
    monkeypatch.setattr(DNS, "ThreadPoolExecutor", Workers)
    monkeypatch.setattr(DNS.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(DNS.select, "select", readable)

    def run():
        DNS.serve(
            SimpleNamespace(answer=lambda data, tcp: DNSRecord.parse(data).reply().pack()),
            stop=stop,
            refresh=refresh,
            ready=lambda: ready.append(True),
            retry_source=fatal != "legacy",
        )

    if fatal:
        expected = OSError if fatal == "publication" else DNS.Unavailable
        with pytest.raises(expected):
            run()
        assert len(calls) == (1 if fatal == "initial" else 2)
        assert len(ready) == (0 if fatal == "initial" else 1)
    else:
        run()
        assert len(calls) == 6 and ready == [True]
        assert len(answers) == 6  # Peer requests continue through repeated source failures.
    assert len(closed) == (0 if fatal == "initial" else 2)
