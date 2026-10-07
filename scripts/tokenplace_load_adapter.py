"""Application crypto and HTTP protocol adapter for injected offline transports.

No network transport or execution CLI is supplied. Callers must provide bounded,
cancellation-cooperative async transport, clock, observation and gate providers.
"""

from __future__ import annotations

import asyncio
import base64
import builtins
import hashlib
import json
import secrets
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from scripts.tokenplace_load_replay import LIMITS, ROUTES, Harness, Reply, Stop, encoded, need

CRYPTO_SHA256 = "e661e4195fa94a78e68282526dfe16a9b2e9f27755d788a14868022506e461cb"


def load_application_crypto(source):
    """Execute verified upstream bytes using upstream's standalone config fallback.

    Never add the application checkout to sys.path or import its configuration.
    The caller materializes encrypt.py from the documented pinned source first.
    """
    raw = Path(source).read_bytes()
    need(hashlib.sha256(raw).hexdigest() == CRYPTO_SHA256, "crypto_source")
    module = types.ModuleType("_k133_application_crypto")
    original_import = builtins.__import__

    def standalone_import(name, *args, **kwargs):
        if name == "config":
            raise ImportError("standalone application crypto")
        return original_import(name, *args, **kwargs)

    module.__dict__["__builtins__"] = {**vars(builtins), "__import__": standalone_import}
    # dataclasses resolves its defining module during execution.
    previous = sys.modules.get(module.__name__)
    sys.modules[module.__name__] = module
    try:
        exec(compile(raw, "<pinned token.place encrypt.py>", "exec"), module.__dict__)
    finally:
        if previous is None:
            sys.modules.pop(module.__name__, None)
        else:
            sys.modules[module.__name__] = previous
    return module


def b64(value):
    return base64.b64encode(value).decode("ascii")


def unb64(value):
    need(isinstance(value, str) and 0 < len(value) <= LIMITS["http_bytes"], "envelope")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise Stop("envelope") from None


@dataclass(frozen=True, repr=False)
class WireRequest:
    """Private request data; never include its fields in logs or result reports."""

    method: str
    target: str
    headers: dict
    body: bytes


class ProtocolAdapter:
    """Fixture-compatible adapter executing real crypto and serialized protocol.

    transport.open(request, absolute_monotonic_deadline) returns a response with
    integer status, redirected bool, async read(max_bytes) and synchronous close().
    open/read MUST cooperate with cancellation; a cancelled open releases partial
    resources. Response close releases that exchange; transport close is final.
    No transport implementation or live evidence is selected implicitly.
    """

    def __init__(self, *, crypto, transport, clock, observe, gates, expires):
        need(getattr(transport, "offline", False) is True, "offline_transport")
        self.crypto, self.transport, self.clock = crypto, transport, clock
        self.observer, self.gates, self.expires = observe, gates, expires
        self.private_key = None
        self.local_decryptions = 0

    @property
    def now(self):
        return self.clock.now

    def advance_to(self, target):
        self.clock.advance_to(target)

    def elapse(self, seconds):
        self.clock.advance_to(self.now + seconds)

    def observe(self):
        return self.observer(self.now)

    def new_job(self, number):
        started = time.monotonic()
        try:
            self.private_key, public_key = self.crypto.generate_keys()
            return b64(public_key), secrets.token_hex(16), secrets.token_hex(32)
        finally:
            self.elapse(time.monotonic() - started)

    def seal(self, plaintext, server_key):
        started = time.monotonic()
        try:
            clear = encoded(plaintext, LIMITS["plaintext_bytes"])
            ciphertext, key, iv = self.crypto.encrypt(clear, unb64(server_key))
            return {
                "ciphertext": b64(ciphertext["ciphertext"]),
                "cipherkey": b64(key),
                "iv": b64(iv),
            }
        finally:
            self.elapse(time.monotonic() - started)

    def open(self, body):
        started = time.monotonic()
        try:
            clear = self.crypto.decrypt(
                {"ciphertext": unb64(body["ciphertext"]), "iv": unb64(body["iv"])},
                unb64(body["cipherkey"]),
                self.private_key,
            )
            need(isinstance(clear, bytes) and len(clear) <= LIMITS["plaintext_bytes"], "decryption")
            try:
                result = json.loads(clear)
            except (ValueError, UnicodeError):
                raise Stop("decryption") from None
            need(isinstance(result, dict), "decryption")
            self.local_decryptions += 1
            return result
        finally:
            self.elapse(time.monotonic() - started)

    def wire_request(self, operation, body):
        method, target = ROUTES[operation]
        fields = dict(body or {})
        if operation == "submit":
            fields["chat_history"] = fields.pop("ciphertext")
        if method == "GET":
            if fields:
                target += "?" + urlencode(fields)
            payload = b""
        else:
            payload = encoded(fields, LIMITS["http_bytes"])
        need(len(target.encode("ascii")) <= LIMITS["http_bytes"], "body_limit")
        return WireRequest(
            method,
            target,
            {"Content-Type": "application/json", "Content-Length": str(len(payload))},
            payload,
        )

    async def exchange(self, operation, request):
        response = None
        started = time.monotonic()
        deadline = started + LIMITS["request_seconds"]
        try:
            # One absolute budget covers opening, all reads, and JSON parsing.
            async with asyncio.timeout_at(
                asyncio.get_running_loop().time() + LIMITS["request_seconds"]
            ):
                response = await self.transport.open(request, deadline)
                need(response.redirected is False, "redirect")
                need(type(response.status) is int and 100 <= response.status <= 599, "status")
                data = bytearray()
                while True:
                    need(time.monotonic() < deadline, "request_deadline")
                    chunk = await response.read(min(4096, LIMITS["http_bytes"] + 1 - len(data)))
                    need(isinstance(chunk, bytes), "invalid_body")
                    data.extend(chunk)
                    need(len(data) <= LIMITS["http_bytes"], "body_limit")
                    if not chunk:
                        break
                # Public endpoints may return HTML/text, not JSON; retain no content.
                parsed = {}
                if operation in {"select", "submit", "retrieve", "ack", "cancel"}:
                    try:
                        parsed = json.loads(data)
                    except (ValueError, UnicodeError):
                        raise Stop("invalid_body") from None
                    need(isinstance(parsed, dict), "invalid_body")
                need(time.monotonic() < deadline, "request_deadline")
                if operation == "retrieve" and response.status == 200:
                    alias = parsed.get("chat_history")
                    if "chat_history" in parsed:
                        need(parsed.get("ciphertext", alias) == alias, "envelope")
                        parsed["ciphertext"] = alias
                return Reply(response.status, parsed, time.monotonic() - started, len(data))
        except TimeoutError:
            raise Stop("request_deadline") from None
        finally:
            if response is not None:
                response.close()

    def call(self, operation, body):
        started = time.monotonic()
        try:
            reply = asyncio.run(self.exchange(operation, self.wire_request(operation, body)))
            reply.seconds = time.monotonic() - started
            need(reply.seconds <= LIMITS["request_seconds"], "request_deadline")
            return reply
        except Stop:
            self.elapse(time.monotonic() - started)
            raise
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.elapse(time.monotonic() - started)
            raise Stop("interrupted") from None
        except Exception:
            self.elapse(time.monotonic() - started)
            raise Stop("transport") from None

    def close(self):
        self.private_key = None
        complete = True
        for release in (self.crypto._load_private_key_cached.cache_clear, self.transport.close):
            try:
                release()
            except (Exception, KeyboardInterrupt, asyncio.CancelledError):
                complete = False
        return complete


def run_protocol_rehearsal(adapter):
    """Run the bounded plan with real local crypto, then release private state.

    SIGINT/KeyboardInterrupt stops new jobs and permits the harness's single
    bounded cancellation. SIGKILL/process loss cannot confirm cleanup; never
    restart this plan automatically or persist keys/proofs for a retry.
    """
    try:
        report = Harness(adapter).run()
        report["kind"] = "offline-protocol-rehearsal"
        report["local_crypto_roundtrip_verified"] = report["completed_fixture_jobs"] > 0
    finally:
        released = adapter.close()
    if not released:
        report.update(outcome="stopped", reason="teardown", cleanup="unconfirmed")
    return report
