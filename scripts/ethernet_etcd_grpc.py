"""Bounded etcd gRPC over one pinned, caller-bound TCP connection.

grpcio owns HTTP/2, protobuf framing and end-to-end mutual TLS. Its Python API
does not expose a custom dialer. A private Unix socket therefore forwards opaque
TLS bytes to exactly one caller-created TCP socket. The listener accepts once;
neither gRPC reconnects nor a retry can open another outbound connection.
"""

from __future__ import annotations

import hashlib
import select
import socket
import tempfile
import threading
from pathlib import Path

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

ROUTES = {
    "/v3/maintenance/status": "Maintenance.Status",
    "/v3/cluster/member/list": "Cluster.MemberList",
    "/v3/cluster/member/update": "Cluster.MemberUpdate",
    "/v3/kv/range": "KV.Range",
    "/v3/kv/txn": "KV.Txn",
}
LIMIT = 1024 * 1024
DEADLINE = 5
SCHEMA_SHA256 = "4ff408bd7b84e57c41b0504831efe7c4d16eb9a27ecd06d970dd55a85f67ff9d"


class TransportError(RuntimeError):
    """This session cannot be reused; a mutation outcome may be unknown."""


class OneConnection:
    """Private, single-accept encrypted-byte relay, with no retrying dial path."""

    def __init__(self, connect):
        self.closed = threading.Event()
        self.sockets = []
        self.guard = threading.Lock()
        self.accepts = 0
        self.connects = 0
        self.directory = tempfile.TemporaryDirectory(prefix="sugarkube-grpc-")
        self.path = str(Path(self.directory.name) / "socket")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.listener.bind(self.path)
            self.listener.listen(1)
            self.listener.settimeout(DEADLINE)
            self.worker = threading.Thread(target=self.run, args=(connect,), daemon=True)
            self.worker.start()
        except Exception:
            self.listener.close()
            self.directory.cleanup()
            raise

    def register(self, sock):
        with self.guard:
            if self.closed.is_set():
                sock.close()
                raise TransportError("session closed")
            self.sockets.append(sock)
        sock.settimeout(DEADLINE)
        return sock

    def run(self, connect):
        try:
            local, _ = self.listener.accept()
            self.accepts += 1
            self.listener.close()
            local = self.register(local)
            # No loop around this call, including on initial connection failure.
            remote = self.register(connect())
            self.connects += 1
            while not self.closed.is_set():
                readable, _, _ = select.select([local, remote], [], [], 0.1)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (remote if source is local else local).sendall(data)
        except Exception:
            # The caller sees an unavailable/failed TLS channel or bounded RPC error.
            pass
        finally:
            self.close()

    def close(self):
        with self.guard:
            self.closed.set()
            for sock in [self.listener, *self.sockets]:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        # unlink prevents gRPC's internal connection management accepting again.
        self.directory.cleanup()


def message_class(descriptor, pool):
    # Debian Bookworm ships protobuf 3.21; newer releases use the module API.
    if hasattr(message_factory, "GetMessageClass"):
        return message_factory.GetMessageClass(descriptor)
    return message_factory.MessageFactory(pool).GetPrototype(descriptor)


class Session:
    def __init__(self, host, cluster_id, member_id, tls, connect):
        self.cluster_id, self.member_id = int(cluster_id), int(member_id)
        self.failed = True
        self.channel = None
        self.relay = None
        schema = Path(__file__).with_name("ethernet-etcd.desc").read_bytes()
        if hashlib.sha256(schema).hexdigest() != SCHEMA_SHA256:
            raise TransportError("etcd wire schema changed")
        descriptors = descriptor_pb2.FileDescriptorSet.FromString(schema)
        self.pool = descriptor_pool.DescriptorPool()
        for descriptor in descriptors.file:
            self.pool.Add(descriptor)
        credentials = grpc.ssl_channel_credentials(
            root_certificates=Path(tls["ca"]).read_bytes(),
            private_key=Path(tls["key"]).read_bytes(),
            certificate_chain=Path(tls["cert"]).read_bytes(),
        )
        try:
            self.relay = OneConnection(connect)
            self.channel = grpc.secure_channel(
                "unix:" + self.relay.path,
                credentials,
                options=[
                    # These specify the enrolled DNS identity, not the relay's path.
                    ("grpc.ssl_target_name_override", host),
                    ("grpc.default_authority", host),
                    ("grpc.enable_http_proxy", 0),
                    ("grpc.enable_retries", 0),
                    ("grpc.max_receive_message_length", LIMIT),
                    ("grpc.max_send_message_length", LIMIT),
                ],
            )
            grpc.channel_ready_future(self.channel).result(timeout=DEADLINE)
            self.failed = False
        except Exception as exc:
            self.close()
            raise TransportError(
                "authenticated gRPC connection failed; no automatic reconnect"
            ) from exc

    def request(self, route, payload):
        if self.failed or self.relay.closed.is_set():
            raise TransportError("authenticated session ended; no automatic reconnect")
        try:
            method = self.pool.FindMethodByName("etcdserverpb." + ROUTES[route])
            request = message_class(method.input_type, self.pool)()
            json_format.ParseDict(payload, request)
            response_type = message_class(method.output_type, self.pool)
            response = self.channel.unary_unary(
                "/" + method.containing_service.full_name + "/" + method.name,
                request_serializer=lambda value: value.SerializeToString(),
                response_deserializer=response_type.FromString,
            )(request, timeout=DEADLINE, wait_for_ready=False)
            if (
                response.header.cluster_id != self.cluster_id
                or response.header.member_id != self.member_id
            ):
                raise TransportError("authenticated response identity mismatch")
            result = json_format.MessageToDict(response, preserving_proto_field_name=True)
            # Proto3 omits false. A confirmed false CAS must remain distinguishable
            # from an exception/unknown outcome; never infer success from absence.
            if method.name == "Txn":
                result["succeeded"] = response.succeeded
            return result
        except Exception as exc:
            self.close()
            if isinstance(exc, TransportError):
                raise
            raise TransportError("gRPC operation failed; outcome may be unknown") from exc

    def close(self):
        self.failed = True
        if self.channel is not None:
            self.channel.close()
        if self.relay is not None:
            self.relay.close()
