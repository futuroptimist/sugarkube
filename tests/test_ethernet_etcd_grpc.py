"""Actual gRPC/mTLS with synthetic identities; no K3s or live cluster involved."""

import base64
import importlib.util
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc
import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "etcd_transport", ROOT / "scripts/ethernet_etcd_grpc.py"
)
TRANSPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSPORT)
CID = 18446744073709551614
MID = 18446744073709551613


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    path = tmp_path_factory.mktemp("grpc-certs")

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=path, capture_output=True, check=True, timeout=15)

    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=Test CA",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
    )
    openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=pi1.local",
        "-keyout",
        "client.key",
        "-out",
        "client.csr",
    )
    (path / "extensions").write_text(
        "subjectAltName=DNS:pi1.local\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth,clientAuth\n"
    )
    openssl(
        "x509",
        "-req",
        "-in",
        "client.csr",
        "-CA",
        "ca.crt",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-days",
        "1",
        "-extfile",
        "extensions",
        "-out",
        "client.crt",
    )
    return {
        "ca": str(path / "ca.crt"),
        "cert": str(path / "client.crt"),
        "key": str(path / "client.key"),
    }


@pytest.fixture
def endpoint(tls):
    pool = descriptor_pool.DescriptorPool()
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(
        (ROOT / "scripts/ethernet-etcd.desc").read_bytes()
    )
    for descriptor in descriptors.file:
        pool.Add(descriptor)
    state = {
        "calls": [],
        "updates": [],
        "wrong_id": False,
        "abort_after_commit": False,
        "abort_transaction": False,
        "succeeded": True,
        "connects": 0,
    }
    server = grpc.server(ThreadPoolExecutor(max_workers=2))
    for service in ("Maintenance", "Cluster", "KV"):
        handlers = {}
        for method in pool.FindServiceByName("etcdserverpb." + service).methods:
            if service + "." + method.name not in TRANSPORT.ROUTES.values():
                continue
            response_type = TRANSPORT.message_class(method.output_type, pool)

            def call(request, context, method=method, response_type=response_type):
                state["calls"].append((method.name, request))
                response = response_type()
                response.header.cluster_id = CID
                response.header.member_id = MID - 1 if state["wrong_id"] else MID
                if method.name == "MemberUpdate":
                    state["updates"].append((request.ID, list(request.peerURLs)))
                    if state["abort_after_commit"]:
                        context.abort(grpc.StatusCode.UNAVAILABLE, "response lost after commit")
                if method.name == "Txn":
                    response.succeeded = state["succeeded"]
                    if state["abort_transaction"]:
                        context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "unknown CAS outcome")
                return response

            handlers[method.name] = grpc.unary_unary_rpc_method_handler(
                call,
                request_deserializer=TRANSPORT.message_class(method.input_type, pool).FromString,
                response_serializer=lambda value: value.SerializeToString(),
            )
        server.add_generic_rpc_handlers(
            (grpc.method_handlers_generic_handler("etcdserverpb." + service, handlers),)
        )
    credentials = grpc.ssl_server_credentials(
        [(Path(tls["key"]).read_bytes(), Path(tls["cert"]).read_bytes())],
        root_certificates=Path(tls["ca"]).read_bytes(),
        require_client_auth=True,
    )
    port = server.add_secure_port("127.0.0.1:0", credentials)
    server.start()

    def connect():
        state["connects"] += 1
        return socket.create_connection(("127.0.0.1", port), timeout=2)

    state.update(connect=connect, stop=lambda: server.stop(0).wait())
    yield state
    server.stop(0).wait()


def session(tls, endpoint, **overrides):
    args = dict(
        host="pi1.local",
        cluster_id=str(CID),
        member_id=str(MID),
        tls=tls,
        connect=endpoint["connect"],
    )
    args.update(overrides)
    return TRANSPORT.Session(**args)


def test_native_rpc_exact_uint64_repeated_urls_and_false_cas(tls, endpoint):
    client = session(tls, endpoint)
    try:
        result = client.request("/v3/maintenance/status", {})
        assert result["header"] == {"cluster_id": str(CID), "member_id": str(MID)}
        client.request("/v3/cluster/member/list", {"linearizable": True})
        urls = ["https://10.0.0.21:2380", "https://pi1.local:2380"]
        client.request("/v3/cluster/member/update", {"ID": str(MID), "peerURLs": urls})
        assert endpoint["updates"] == [(MID, urls)]
        key = base64.b64encode(b"/lock").decode()
        endpoint["succeeded"] = False
        result = client.request(
            "/v3/kv/txn",
            {
                "compare": [{"key": key, "target": "VERSION", "result": "EQUAL", "version": "0"}],
                "success": [{"request_put": {"key": key, "value": key}}],
                "failure": [],
            },
        )
        assert result["succeeded"] is False
        assert endpoint["calls"][1][1].linearizable is True
        assert client.relay.accepts == client.relay.connects == endpoint["connects"] == 1
        assert Path(client.relay.directory.name).stat().st_mode & 0o077 == 0
    finally:
        client.close()
    assert not Path(client.relay.path).exists()


@pytest.mark.parametrize("field", ["member_id", "cluster_id"])
def test_wrong_authenticated_response_identity_latches(tls, endpoint, field):
    client = session(tls, endpoint, **{field: "1"})
    with pytest.raises(TRANSPORT.TransportError, match="identity mismatch"):
        client.request("/v3/maintenance/status", {})
    with pytest.raises(TRANSPORT.TransportError, match="no automatic reconnect"):
        client.request("/v3/maintenance/status", {})
    assert len(endpoint["calls"]) == endpoint["connects"] == 1


def test_wrong_tls_hostname_cannot_dispatch(tls, endpoint):
    with pytest.raises(TRANSPORT.TransportError, match="connection failed") as caught:
        session(tls, endpoint, host="wrong.local")
    assert not isinstance(caught.value, TRANSPORT.Unavailable)
    assert endpoint["calls"] == []
    assert endpoint["connects"] == 1


def test_mutation_committed_but_response_lost_is_never_replayed(tls, endpoint):
    client = session(tls, endpoint)
    endpoint["abort_after_commit"] = True
    payload = {"ID": str(MID), "peerURLs": ["https://10.0.0.21:2380"]}
    with pytest.raises(TRANSPORT.TransportError, match="outcome may be unknown"):
        client.request("/v3/cluster/member/update", payload)
    endpoint["abort_after_commit"] = False
    with pytest.raises(TRANSPORT.TransportError, match="no automatic reconnect"):
        client.request("/v3/cluster/member/update", payload)
    assert len(endpoint["updates"]) == endpoint["connects"] == 1


def test_lost_transport_does_not_dial_again(tls, endpoint):
    client = session(tls, endpoint)
    client.request("/v3/maintenance/status", {})
    endpoint["stop"]()
    with pytest.raises(TRANSPORT.TransportError):
        client.request("/v3/maintenance/status", {})
    with pytest.raises(TRANSPORT.TransportError, match="no automatic reconnect"):
        client.request("/v3/maintenance/status", {})
    assert endpoint["connects"] == len(endpoint["calls"]) == 1


def test_unsupported_rpc_fails_before_dispatch(tls, endpoint):
    client = session(tls, endpoint)
    with pytest.raises(TRANSPORT.TransportError):
        client.request("/v3/cluster/member/remove", {"ID": str(MID)})
    assert endpoint["calls"] == []


def test_unknown_cas_is_not_reported_as_definitive_false(tls, endpoint):
    client = session(tls, endpoint)
    endpoint["abort_transaction"] = True
    with pytest.raises(TRANSPORT.TransportError, match="outcome may be unknown"):
        client.request("/v3/kv/txn", {"compare": []})
    with pytest.raises(TRANSPORT.TransportError, match="no automatic reconnect"):
        client.request("/v3/kv/txn", {"compare": []})
    assert len(endpoint["calls"]) == endpoint["connects"] == 1


def test_missing_client_authentication_cannot_dispatch(tls, endpoint, tmp_path):
    # A different self-signed client is untrusted by the server, even though the
    # client still has the correct CA for authenticating the enrolled server.
    key, cert = tmp_path / "key", tmp_path / "cert"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=foreign",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    with pytest.raises(TRANSPORT.TransportError, match="connection failed") as caught:
        session({**tls, "key": str(key), "cert": str(cert)}, endpoint)
    assert not isinstance(caught.value, TRANSPORT.Unavailable)
    assert endpoint["calls"] == [] and endpoint["connects"] == 1


def test_closed_relay_rejects_new_socket_and_constructor_cleans_up(monkeypatch, tmp_path):
    import threading
    from types import SimpleNamespace

    closed = []
    relay = TRANSPORT.OneConnection.__new__(TRANSPORT.OneConnection)
    relay.guard = threading.Lock()
    relay.closed = threading.Event()
    relay.closed.set()
    with pytest.raises(TRANSPORT.TransportError, match="closed"):
        relay.register(SimpleNamespace(close=lambda: closed.append(True)))
    assert closed == [True]

    def fail_bind(path):
        raise OSError("bind failed")

    sock = SimpleNamespace(bind=fail_bind, close=lambda: closed.append(True))
    monkeypatch.setattr(TRANSPORT.socket, "socket", lambda *args: sock)
    monkeypatch.setattr(TRANSPORT.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(OSError, match="bind failed"):
        TRANSPORT.OneConnection(lambda: pytest.fail("must not connect"))
    assert closed == [True, True] and list(tmp_path.iterdir()) == []


def test_schema_tamper_and_legacy_protobuf_factory_are_checked(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(TRANSPORT.Path, "read_bytes", lambda _: b"tampered")
    with pytest.raises(TRANSPORT.TransportError, match="schema changed"):
        TRANSPORT.Session("pi1.local", CID, MID, {}, lambda: pytest.fail("must not connect"))
    calls = []
    monkeypatch.setattr(
        TRANSPORT,
        "message_factory",
        SimpleNamespace(
            MessageFactory=lambda pool: SimpleNamespace(
                GetPrototype=lambda descriptor: calls.append((pool, descriptor)) or "legacy-message"
            )
        ),
    )
    assert TRANSPORT.message_class("descriptor", "pool") == "legacy-message"
    assert calls == [("pool", "descriptor")]


@pytest.mark.parametrize("failure", ["connect", "timeout", "permission", "forward"])
def test_offline_relay_marks_only_tcp_connect_failures(monkeypatch, failure):
    import threading
    from types import SimpleNamespace

    relay = TRANSPORT.OneConnection.__new__(TRANSPORT.OneConnection)
    relay.closed = threading.Event()
    relay.accepts = relay.connects = 0
    relay.connect_error = None
    relay.guard = threading.Lock()
    relay.client_bytes = relay.server_bytes = 0
    relay.relay_failed = False
    calls = []
    local = SimpleNamespace(recv=lambda _: (_ for _ in ()).throw(ConnectionResetError()))
    relay.listener = SimpleNamespace(accept=lambda: (local, None), close=lambda: None)
    relay.register = lambda sock: sock
    relay.close = relay.closed.set
    monkeypatch.setattr(TRANSPORT.select, "select", lambda *args: ([local], [], []))

    def connect():
        calls.append(True)
        if failure == "connect":
            raise ConnectionRefusedError()
        if failure == "timeout":
            raise TimeoutError()
        if failure == "permission":
            raise PermissionError()
        return object()

    relay.run(connect)
    assert calls == [True] and relay.closed.is_set()
    assert (relay.connect_error is not None) is (failure in ("connect", "timeout"))
    assert relay.connects == (1 if failure == "forward" else 0)


@pytest.mark.parametrize("failure", ["tcp", "tls", "permission", "success"])
def test_offline_session_handshake_classification(monkeypatch, tmp_path, failure):
    import threading
    from types import SimpleNamespace

    cert = tmp_path / "synthetic-credential"
    cert.write_bytes(b"offline fixture")
    closed = []
    relay = SimpleNamespace(
        path="unused",
        connect_error=ConnectionRefusedError() if failure == "tcp" else None,
        closed=threading.Event(),
        close=lambda: closed.append("relay"),
        startup_pending=lambda: False,
    )
    channel = SimpleNamespace(close=lambda: closed.append("channel"))
    monkeypatch.setattr(TRANSPORT, "OneConnection", lambda _: relay)
    monkeypatch.setattr(grpc, "ssl_channel_credentials", lambda **kwargs: object())
    monkeypatch.setattr(grpc, "secure_channel", lambda *args, **kwargs: channel)

    def ready(timeout):
        assert timeout == TRANSPORT.DEADLINE
        if failure == "permission":
            raise PermissionError()
        if failure != "success":
            raise grpc.FutureTimeoutError()

    monkeypatch.setattr(grpc, "channel_ready_future", lambda _: SimpleNamespace(result=ready))
    tls = {name: str(cert) for name in ("ca", "key", "cert")}
    if failure == "success":
        session = TRANSPORT.Session("pi1.local", CID, MID, tls, lambda: None)
        assert session.failed is False
        session.close()
    else:
        with pytest.raises(TRANSPORT.TransportError) as caught:
            TRANSPORT.Session("pi1.local", CID, MID, tls, lambda: None)
        assert isinstance(caught.value, TRANSPORT.Unavailable) is (failure == "tcp")
    assert closed == ["channel", "relay"]


@pytest.mark.parametrize(
    "failure",
    [
        "unavailable",
        "deadline",
        "permission",
        "unauthenticated",
        "identity",
        "schema",
        "eof",
        "failed",
    ],
)
@pytest.mark.parametrize(
    "route",
    [
        "/v3/maintenance/status",
        "/v3/cluster/member/list",
        "/v3/kv/range",
        "/v3/cluster/member/update",
        "/v3/kv/txn",
    ],
)
def test_offline_authenticated_rpc_classification_never_replays(failure, route):
    import threading
    from types import SimpleNamespace

    session = TRANSPORT.Session.__new__(TRANSPORT.Session)
    session.failed = failure == "failed"
    session.cluster_id, session.member_id = CID, MID
    session.pool = descriptor_pool.DescriptorPool()
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(
        (ROOT / "scripts/ethernet-etcd.desc").read_bytes()
    )
    for descriptor in descriptors.file:
        session.pool.Add(descriptor)
    closed, calls = [], []
    session.relay = SimpleNamespace(closed=threading.Event(), close=lambda: closed.append("relay"))
    if failure == "eof":
        session.relay.closed.set()

    class RpcFailure(grpc.RpcError):
        def code(self):
            return {
                "unavailable": grpc.StatusCode.UNAVAILABLE,
                "deadline": grpc.StatusCode.DEADLINE_EXCEEDED,
                "permission": grpc.StatusCode.PERMISSION_DENIED,
                "unauthenticated": grpc.StatusCode.UNAUTHENTICATED,
            }[failure]

    def rpc(request, **kwargs):
        calls.append(request)
        if failure == "identity":
            descriptor = session.pool.FindMessageTypeByName("etcdserverpb.StatusResponse")
            response = TRANSPORT.message_class(descriptor, session.pool)()
            response.header.cluster_id, response.header.member_id = CID, MID - 1
            return response
        raise RpcFailure()

    session.channel = SimpleNamespace(
        unary_unary=lambda *args, **kwargs: rpc, close=lambda: closed.append("channel")
    )
    read_only = route in ("/v3/maintenance/status", "/v3/cluster/member/list", "/v3/kv/range")
    route = "unknown" if failure == "schema" else route
    with pytest.raises(TRANSPORT.TransportError) as caught:
        session.request(route, {})
    assert isinstance(caught.value, TRANSPORT.Unavailable) is (
        read_only and failure in ("unavailable", "deadline", "eof")
    )
    if not read_only and failure in ("unavailable", "deadline"):
        assert str(caught.value) == "gRPC operation failed; outcome may be unknown"
    if not read_only and failure == "eof":
        assert "outcome may be unknown; no automatic reconnect" in str(caught.value)
    expected = 0 if failure in ("eof", "failed", "schema") else 1
    assert len(calls) == expected and session.failed
    with pytest.raises(TRANSPORT.TransportError) as repeated:
        session.request(route, {})
    assert not isinstance(repeated.value, TRANSPORT.Unavailable)
    assert "no automatic reconnect" in str(repeated.value)
    assert len(calls) == expected


@pytest.mark.parametrize(
    "state", ["silent", "server", "eof", "error", "closed", "unsent", "undialed", "permission"]
)
@pytest.mark.parametrize("latched", [False, True])
@pytest.mark.parametrize("route", list(TRANSPORT.ROUTES))
def test_real_session_startup_snapshot_through_staged_backend(
    tmp_path, monkeypatch, state, route, latched
):
    import threading
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location(
        "staged_bridge", ROOT / "scripts/ethernet_staged_recovery.py"
    )
    staged = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staged)
    cert = tmp_path / "synthetic"
    cert.write_bytes(b"offline")
    relay = TRANSPORT.OneConnection.__new__(TRANSPORT.OneConnection)
    relay.guard = threading.Lock()
    relay.closed = threading.Event()
    relay.connects = 0 if state == "undialed" else 1
    relay.client_bytes = 0 if state == "unsent" else 1
    relay.server_bytes = 1 if state == "server" else 0
    relay.relay_failed = state in ("eof", "error")
    relay.connect_error = None
    relay.path = "unused"
    if state == "closed":
        relay.closed.set()
    closes = []

    def close():
        closes.append("relay")
        relay.closed.set()

    relay.close = close
    channel = SimpleNamespace(close=lambda: closes.append("channel"))
    dials = []
    monkeypatch.setattr(TRANSPORT, "OneConnection", lambda connect: dials.append(True) or relay)
    monkeypatch.setattr(grpc, "ssl_channel_credentials", lambda **kwargs: object())
    monkeypatch.setattr(grpc, "secure_channel", lambda *args, **kwargs: channel)

    def ready(timeout):
        assert timeout == TRANSPORT.DEADLINE
        if state == "permission":
            raise PermissionError()
        raise grpc.FutureTimeoutError()

    monkeypatch.setattr(grpc, "channel_ready_future", lambda _: SimpleNamespace(result=ready))
    b = staged.Backend(
        {
            "members": [{"hostname": "pi1.local", "id": str(MID)}],
            "cluster_id": str(CID),
            "etcd_tls": {k: str(cert) for k in ("ca", "key", "cert")},
        },
        {},
    )
    b.transport = TRANSPORT
    b.write_failed = latched
    monkeypatch.setattr(b, "resolve", lambda _: "10.0.0.1")
    with pytest.raises(staged.Q.Stop) as caught:
        b.request("pi1.local", route, {})
    mutation = route in ("/v3/kv/txn", "/v3/cluster/member/update")
    assert isinstance(caught.value, staged.ReadUnavailable) is (
        state == "silent" and not mutation and not latched
    )
    assert isinstance(
        (
            caught.value.__cause__.__cause__
            if isinstance(caught.value, staged.ReadUnavailable)
            else caught.value.__cause__
        ),
        TRANSPORT.Unavailable,
    ) is (state == "silent")
    assert b.connections == {"pi1.local": None}
    assert closes == ["channel", "relay"] and len(dials) == 1
    with pytest.raises(staged.Q.Stop):
        b.request("pi1.local", route, {})
    assert len(dials) == 1
    assert b.write_failed is (latched or mutation)
    if mutation or latched:
        with pytest.raises(staged.Q.Stop, match="uncertain mutation"):
            b.retry_reads()
        assert len(dials) == 1
    elif state == "silent":
        b.retry_reads()
        relay.closed.clear()
        monkeypatch.setattr(
            grpc, "channel_ready_future", lambda _: SimpleNamespace(result=lambda **kwargs: None)
        )
        pool = descriptor_pool.DescriptorPool()
        descriptors = descriptor_pb2.FileDescriptorSet.FromString(
            (ROOT / "scripts/ethernet-etcd.desc").read_bytes()
        )
        for descriptor in descriptors.file:
            pool.Add(descriptor)
        method = pool.FindMethodByName("etcdserverpb." + TRANSPORT.ROUTES[route])
        response = TRANSPORT.message_class(method.output_type, pool)()
        response.header.cluster_id, response.header.member_id = CID, MID
        channel.unary_unary = lambda *args, **kwargs: lambda *args, **kwargs: response
        result = b.request("pi1.local", route, {})
        assert result["header"]["cluster_id"] == str(CID)
        assert len(dials) == 2 and not b.write_failed
        b.close()


def test_real_socket_silent_tls_startup_is_unavailable(tls, endpoint):
    import threading

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(10)
    received = threading.Event()
    release = threading.Event()

    def serve():
        with listener.accept()[0] as peer:
            peer.settimeout(10)
            assert peer.recv(65536)
            received.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(serve)
        try:
            with pytest.raises(TRANSPORT.Unavailable, match="startup response pending"):
                TRANSPORT.Session(
                    "pi1.local",
                    CID,
                    MID,
                    tls,
                    lambda: socket.create_connection(listener.getsockname(), timeout=5),
                )
            assert received.is_set()
        finally:
            release.set()
            listener.close()
        worker.result(timeout=10)
    fresh = session(tls, endpoint)
    try:
        assert fresh.request("/v3/maintenance/status", {})["header"]["cluster_id"] == str(CID)
        assert endpoint["connects"] == 1
    finally:
        fresh.close()


@pytest.mark.parametrize("event", ["client", "server", "eof", "send-error", "recv-error"])
def test_relay_records_startup_evidence_before_cleanup(monkeypatch, event):
    import threading
    from types import SimpleNamespace

    relay = TRANSPORT.OneConnection.__new__(TRANSPORT.OneConnection)
    relay.guard = threading.Lock()
    relay.closed = threading.Event()
    relay.connect_error = None
    relay.accepts = relay.connects = relay.client_bytes = relay.server_bytes = 0
    relay.relay_failed = False
    snapshots = []

    def recv(_):
        if event == "recv-error":
            raise OSError("read failed")
        return b"" if event == "eof" else b"handshake"

    def send(data):
        assert not relay.guard.locked()
        if event == "server":
            assert relay.server_bytes == len(data)
        else:
            assert relay.client_bytes == 0
        if event == "send-error":
            raise OSError("send failed")

    local = SimpleNamespace(recv=recv, sendall=send)
    remote = SimpleNamespace(recv=recv, sendall=send)
    relay.listener = SimpleNamespace(accept=lambda: (local, None), close=lambda: None)
    relay.register = lambda sock: sock
    count = []

    def select(*args):
        count.append(True)
        if len(count) == 1:
            return ([remote if event == "server" else local], [], [])
        snapshots.append(relay.startup_pending())
        relay.closed.set()
        return ([], [], [])

    def close():
        snapshots.append(relay.startup_pending())
        relay.closed.set()

    relay.close = close
    monkeypatch.setattr(TRANSPORT.select, "select", select)
    relay.run(lambda: remote)
    assert relay.connects == 1
    assert any(snapshots) is (event == "client")
    assert relay.relay_failed is (event in ("eof", "send-error", "recv-error"))
    assert relay.client_bytes == (9 if event == "client" else 0)
    assert relay.server_bytes == (9 if event == "server" else 0)
