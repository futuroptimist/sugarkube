"""Real application crypto; all protocol transport remains local and in memory."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import types
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import tokenplace_load_adapter as adapter
from scripts import tokenplace_load_replay as replay


@pytest.fixture(autouse=True)
def forbid_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline protocol test attempted external I/O")

    # asyncio creates a local self-pipe; prohibit connections, not socket creation.
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture(scope="module")
def crypto():
    source = os.environ.get("TOKENPLACE_CRYPTO_SOURCE")
    if not source:
        pytest.skip("pinned application crypto absent; dedicated offline-protocol CI supplies it")
    return adapter.load_application_crypto(source)


class Clock:
    now = 1_800_000_000.0

    def advance_to(self, target):
        assert target >= self.now
        self.now = target


class Response:
    redirected = False

    def __init__(self, status, data, fault=None):
        self.status, self.data, self.fault = status, data, fault
        self.closed = False

    async def read(self, size):
        if self.fault == "stall":
            await asyncio.Event().wait()
        if self.fault == "interrupt":
            raise KeyboardInterrupt
        if self.fault == "cancelled":
            raise asyncio.CancelledError
        if self.fault == "error":
            raise RuntimeError("PRIVATE-TRANSPORT-CREDENTIAL")
        part, self.data = self.data[:size], self.data[size:]
        return part

    def close(self):
        self.closed = True


class Peer:
    offline = True

    def __init__(self, crypto, clock, fault=None):
        self.crypto, self.clock, self.fault = crypto, clock, fault
        self.private, self.public = crypto.generate_keys()
        self.requests, self.responses = [], []
        self.admitted, self.acknowledged, self.cancelled = 0, 0, 0
        self.completed = False
        self.closed = 0

    async def open(self, request, deadline):
        assert self.closed == 0, "transport session permanently closed"
        assert deadline > adapter.time.monotonic()
        self.requests.append(request)
        route = urlsplit(request.target)
        fields = (
            {k: v[0] for k, v in parse_qs(route.query).items()}
            if request.method == "GET"
            else json.loads(request.body)
        )
        status, result = 200, {}
        fault = None
        if route.path.endswith("servers/next"):
            assert request.method == "GET" and request.body == b""
            assert fields["model"] == replay.MODEL and fields["context_tier"] == replay.TIER
            self.binding = {k: fields[k] for k in ("client_public_key", "request_id")}
            self.proof = fields["cancel_token"]
            self.deadline = self.clock.now + 600
            self.completed = False
            result = {
                "server_public_key": adapter.b64(self.public),
                "reservation_token": "proof",
                "request_deadline_epoch": self.deadline,
                "resolved_model": replay.MODEL,
                "selected_context_tier": replay.TIER,
            }
        elif route.path.endswith("requests"):
            assert request.method == "POST" and "ciphertext" not in fields
            assert fields["request_deadline_epoch"] == self.deadline
            assert fields["reservation_token"] == "proof"
            assert fields["cancel_token"] == self.proof
            clear = self.crypto.decrypt(
                {
                    "ciphertext": adapter.unb64(fields["chat_history"]),
                    "iv": adapter.unb64(fields["iv"]),
                },
                adapter.unb64(fields["cipherkey"]),
                self.private,
            )
            payload = json.loads(clear)
            assert all(payload[k] == v for k, v in self.binding.items())
            assert payload["protocol"] == replay.PROTOCOL and payload["version"] == 1
            assert payload["api_v1_request"] == {
                "model": replay.MODEL,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "options": {"max_tokens": 64, "temperature": 0, "stream": False},
            }
            self.admitted += 1
            remaining = self.deadline - self.clock.now
            result = {
                "retrieval_credential": "proof",
                "request_ttl_seconds": remaining,
                "request_deadline_remaining_seconds": remaining,
            }
            if self.fault in {"submit_interrupt", "submit_cancelled"}:
                fault = "interrupt" if self.fault == "submit_interrupt" else "cancelled"
            if self.fault == "submit_error":
                fault = "error"
        elif route.path.endswith("responses/retrieve"):
            assert fields["retrieval_credential"] == "proof"
            assert all(fields[k] == v for k, v in self.binding.items())
            if "acknowledgement_token" in fields:
                assert fields["acknowledgement_token"] == "ack-proof"
                self.acknowledged += 1
                status = 503 if self.fault == "ack_failure" else 200
                result = {"status": "acknowledged"}
            else:
                clear = {
                    "protocol": replay.PROTOCOL,
                    "version": 1,
                    "request_id": self.binding["request_id"],
                    "api_v1_response": {"message": {"role": "assistant", "content": "OK"}},
                }
                if self.fault == "wrong_binding":
                    clear["request_id"] = "different"
                ciphertext, key, iv = self.crypto.encrypt(
                    json.dumps(clear).encode(), adapter.unb64(self.binding["client_public_key"])
                )
                result = {
                    **self.binding,
                    "protocol": replay.PROTOCOL,
                    "version": 1,
                    "chat_history": adapter.b64(ciphertext["ciphertext"]),
                    "cipherkey": adapter.b64(key),
                    "iv": adapter.b64(iv),
                    "acknowledgement_token": "ack-proof",
                }
                if self.fault == "alias_conflict":
                    result["ciphertext"] = "conflicting"
                if self.fault == "null_alias":
                    result["ciphertext"] = result["chat_history"]
                    result["chat_history"] = None
                if self.fault == "bad_base64":
                    result["cipherkey"] = "!"
                self.completed = True
        elif route.path.endswith("requests/cancel"):
            assert fields == {
                **self.binding,
                "cancel_token": self.proof,
                "status": "cancelled",
                "reason": "requester_cancelled",
            }
            self.cancelled += 1
            result = {"status": "completed" if self.completed else "cancelled"}
        elif route.path == "/__k133_unmatched_probe__":
            status = 404
        data = json.dumps(result).encode()
        if route.path == "/":
            data = b"<html>Public browser content</html>"
            if self.fault in {"stall", "interrupt"}:
                fault = self.fault
            if self.fault == "oversize":
                data = b"x" * (replay.LIMITS["http_bytes"] + 1)
        response = Response(status, data, fault)
        if self.fault == "redirect":
            response.redirected = True
        self.responses.append(response)
        return response

    def close(self):
        self.closed += 1


def setup(crypto, fault=None):
    clock = Clock()
    peer = Peer(crypto, clock, fault)
    fixture = replay.Fixture()

    def observe(now):
        fixture.now = now
        return fixture.observe()

    client = adapter.ProtocolAdapter(
        crypto=crypto,
        transport=peer,
        clock=clock,
        observe=observe,
        gates=dict.fromkeys(replay.GATES, True),
        expires=clock.now + 2400,
    )
    return client, peer


def test_actual_crypto_and_wire_lifecycle(crypto):
    client, peer = setup(crypto)
    report = adapter.run_protocol_rehearsal(client)
    assert report["outcome"] == "passed"
    assert report["completed_fixture_jobs"] == peer.admitted == peer.acknowledged == 3
    assert report["attempts"] == 22 <= 58
    assert report["local_crypto_roundtrip_verified"] is True
    assert report["encryption_verified"] is report["live_execution"] is False
    assert all(r.closed for r in peer.responses)
    assert client.private_key is None
    assert peer.closed == 1
    text = json.dumps(report)
    assert "BEGIN" not in text and "ack-proof" not in text and "Reply with OK" not in text


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("oversize", "body_limit"),
        ("redirect", "redirect"),
        ("alias_conflict", "envelope"),
        ("null_alias", "envelope"),
        ("wrong_binding", "binding"),
        ("bad_base64", "envelope"),
        ("ack_failure", "unexpected_status"),
        ("submit_interrupt", "interrupted"),
        ("submit_cancelled", "interrupted"),
        ("submit_error", "transport"),
        ("stall", "request_deadline"),
    ],
)
def test_transport_and_crypto_failures_stop_and_close(crypto, fault, reason):
    client, peer = setup(crypto, fault)
    report = adapter.run_protocol_rehearsal(client)
    assert report["reason"] == reason
    assert report["completed_fixture_jobs"] == 0
    assert report["attempts_by_operation"].get("select", 0) <= 1
    assert peer.cancelled <= 1
    assert all(r.closed for r in peer.responses)
    assert client.private_key is None
    assert "PRIVATE" not in json.dumps(report)
    if fault in {"ack_failure", "wrong_binding", "bad_base64", "alias_conflict"}:
        assert report["cleanup"] == "unconfirmed"
    if fault in {"submit_interrupt", "submit_cancelled", "submit_error"}:
        assert peer.cancelled == 1
        assert report["cleanup"] == "relay_cancelled_compute_unproven"


def test_pin_rejects_altered_source(tmp_path):
    source = tmp_path / "encrypt.py"
    source.write_text("raise RuntimeError('must not execute')")
    with pytest.raises(replay.Stop, match="crypto_source"):
        adapter.load_application_crypto(source)


def test_ambient_configuration_is_not_imported(crypto, monkeypatch):
    hostile = types.ModuleType("config")
    hostile.RSA_KEY_SIZE = 512
    monkeypatch.setitem(sys.modules, "config", hostile)
    previous = types.ModuleType("_k133_application_crypto")
    monkeypatch.setitem(sys.modules, "_k133_application_crypto", previous)
    loaded = adapter.load_application_crypto(os.environ["TOKENPLACE_CRYPTO_SOURCE"])
    assert loaded.RSA_KEY_SIZE == 2048
    assert sys.modules["config"] is hostile
    assert sys.modules["_k133_application_crypto"] is previous


@pytest.mark.parametrize("stage", ["open", "read", "cumulative"])
def test_absolute_deadline_cancels_stalled_io(crypto, monkeypatch, stage):
    monkeypatch.setitem(replay.LIMITS, "request_seconds", 0.05)
    client, peer = setup(crypto)
    cancelled = []

    class SlowResponse(Response):
        async def read(self, size):
            try:
                await asyncio.sleep(0.03 if stage == "cumulative" else 5)
                return b"x"
            finally:
                cancelled.append("read")

    response = SlowResponse(200, b"")

    async def slow_open(request, deadline):
        if stage == "open":
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.append("open")
        return response

    peer.open = slow_open
    start = adapter.time.monotonic()
    with pytest.raises(replay.Stop, match="request_deadline"):
        client.call("root", None)
    assert adapter.time.monotonic() - start < 1
    assert cancelled
    assert peer.closed == 0
    assert response.closed is (stage != "open")
    assert client.now >= 1_800_000_000.04
    client.close()


@pytest.mark.parametrize("data", [b"{", b"[]", b"\xff"])
def test_malformed_protocol_json_is_finite_failure(crypto, data):
    client, peer = setup(crypto)
    response = Response(200, data)

    async def open_response(request, deadline):
        return response

    peer.open = open_response
    with pytest.raises(replay.Stop, match="invalid_body"):
        client.call("select", {})
    assert response.closed and peer.closed == 0
    client.close()


def test_no_implicit_network_transport(crypto):
    client, peer = setup(crypto)
    peer.offline = False
    with pytest.raises(replay.Stop, match="offline_transport"):
        adapter.ProtocolAdapter(
            crypto=crypto,
            transport=peer,
            clock=client.clock,
            observe=client.observer,
            gates=client.gates,
            expires=client.expires,
        )
    client.close()


def test_teardown_exception_never_echoes_private_details(crypto):
    client, peer = setup(crypto)

    def broken_close():
        raise RuntimeError("PRIVATE-CREDENTIAL-SENTINEL")

    peer.close = broken_close
    report = adapter.run_protocol_rehearsal(client)
    assert report["reason"] == "teardown"
    assert report["cleanup"] == "unconfirmed"
    assert "PRIVATE" not in json.dumps(report)
    assert client.private_key is None


@pytest.mark.parametrize("operation", ["generate_keys", "encrypt", "decrypt"])
def test_crypto_time_counts_toward_job_budget(crypto, monkeypatch, operation):
    client, peer = setup(crypto)
    original = getattr(crypto, operation)
    clock = {"now": 1000.0}
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock["now"])

    def slow_crypto(*args, **kwargs):
        result = original(*args, **kwargs)
        clock["now"] += 151
        return result

    monkeypatch.setattr(crypto, operation, slow_crypto)
    if operation == "generate_keys":
        client.new_job(0)
    elif operation == "encrypt":
        client.seal({"value": "bounded"}, adapter.b64(peer.public))
    else:
        client.private_key = peer.private
        ciphertext, key, iv = crypto.encrypt(b'{"value":"bounded"}', peer.public)
        client.open(
            {
                "ciphertext": adapter.b64(ciphertext["ciphertext"]),
                "cipherkey": adapter.b64(key),
                "iv": adapter.b64(iv),
            }
        )
    assert client.now == 1_800_000_151
    client.close()


@pytest.mark.parametrize(
    "clear", [b"not-json", b"[]", b"x" * (replay.LIMITS["plaintext_bytes"] + 1)]
)
def test_decrypted_plaintext_must_be_bounded_protocol_object(crypto, clear):
    client, peer = setup(crypto)
    client.private_key = peer.private
    ciphertext, key, iv = crypto.encrypt(clear, peer.public)
    with pytest.raises(replay.Stop, match="decryption"):
        client.open(
            {
                "ciphertext": adapter.b64(ciphertext["ciphertext"]),
                "cipherkey": adapter.b64(key),
                "iv": adapter.b64(iv),
            }
        )
    client.close()


@pytest.mark.parametrize("stage", ["open", "read", "close"])
def test_transport_stop_is_sanitized(crypto, stage):
    client, peer = setup(crypto)
    response = Response(200, b"{}")

    async def private_failure(*args):
        raise replay.Stop("PRIVATE-URL-AND-CREDENTIAL")

    async def open_response(*args):
        return response

    def private_close():
        response.closed = True
        raise replay.Stop("PRIVATE-CLOSE-CREDENTIAL")

    peer.open = private_failure if stage == "open" else open_response
    if stage == "read":
        response.read = private_failure
    if stage == "close":
        response.close = private_close
    report = adapter.run_protocol_rehearsal(client)
    assert report["reason"] == "transport"
    assert "PRIVATE" not in json.dumps(report)
    assert peer.closed == 1


@pytest.mark.parametrize("field", ["redirected", "status", "read"])
def test_response_metadata_stop_is_a_transport_failure(crypto, field):
    client, peer = setup(crypto)

    class MetadataFailure:
        redirected = False
        status = 200

        def __getattribute__(self, name):
            if name == field:
                raise replay.Stop("memory")
            return object.__getattribute__(self, name)

        def close(self):
            pass

    async def open_response(*args):
        return MetadataFailure()

    peer.open = open_response
    report = adapter.run_protocol_rehearsal(client)
    assert report["reason"] == "transport"
    assert peer.closed == 1


def test_initially_unreadable_clock_is_sanitized_at_entry(crypto):
    client, peer = setup(crypto)

    class UnreadableClock:
        @property
        def now(self):
            raise RuntimeError("PRIVATE-INITIAL-CLOCK")

    client.clock = UnreadableClock()
    report = adapter.run_protocol_rehearsal(client)
    assert report["reason"] == "fixture_error"
    assert report["elapsed_seconds"] is None
    assert "PRIVATE" not in json.dumps(report, allow_nan=False)
    assert peer.requests == [] and peer.closed == 1
