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
    "tcp,damage", [(False, None), (True, None), (False, "id"), (True, "eof"), (False, "truncate")]
)
def test_forward_checks_response_and_tcp_fallback(monkeypatch, tcp, damage):
    query = DNSRecord.question("example.test")
    answer = query.reply()
    answer.add_answer(RR(query.q.qname, QTYPE.A, rdata=A("192.0.2.1"), ttl=20))
    calls = []

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
            assert value == 0.6

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
            result, self.remaining = self.remaining[:count], self.remaining[count:]
            return result

    monkeypatch.setattr(DNS.socket, "socket", Socket)
    if damage in ("id", "eof"):
        with pytest.raises(DNS.Unavailable, match="upstream unavailable"):
            DNS.forward(query.pack(), ["::1"], tcp)
    else:
        assert DNS.forward(query.pack(), ["::1"], tcp) == answer.pack()
    assert len(calls) == (2 if damage == "truncate" else 1)


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
    monkeypatch.setattr(DNS, "serve", lambda resolver, refresh: refresh())
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
