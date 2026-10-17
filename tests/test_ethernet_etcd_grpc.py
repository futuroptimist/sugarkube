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
    with pytest.raises(TRANSPORT.TransportError, match="connection failed"):
        session(tls, endpoint, host="wrong.local")
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
    with pytest.raises(TRANSPORT.TransportError, match="connection failed"):
        session({**tls, "key": str(key), "cert": str(cert)}, endpoint)
    assert endpoint["calls"] == [] and endpoint["connects"] == 1
