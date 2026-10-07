#!/usr/bin/env python3
"""Synthetic K133 replay CLI. The offline application-protocol adapter is separate."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass, field

IMAGE = (
    "ghcr.io/futuroptimist/tokenplace-relay@sha256:"
    "5d761cefc0495926b63da1e0a4119155a005e165e469da90e7f19be0f7fdff8e"
)
SOURCE = "5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49"
PROTOCOL = "tokenplace_api_v1_relay_e2ee"
MODEL = "qwen3-8b-instruct"
TIER = "8k-fast"
MEMORY = 256 * 1024 * 1024
ABORT_MEMORY = 192 * 1024 * 1024
RECOVERY_MEMORY = MEMORY * 70 // 100
PHASES = {"baseline": 300, "public": 300, "unmatched": 300, "e2ee": 540, "recovery": 900}
ROUTES = {
    "root": ("GET", "/"),
    "metadata": ("GET", "/api/v1/meta"),
    "version": ("GET", "/api/v1/version"),
    "healthz": ("GET", "/healthz"),
    "livez": ("GET", "/livez"),
    "unmatched": ("GET", "/__k133_unmatched_probe__"),
    "select": ("GET", "/api/v1/relay/servers/next"),
    "submit": ("POST", "/api/v1/relay/requests"),
    "retrieve": ("POST", "/api/v1/relay/responses/retrieve"),
    "ack": ("POST", "/api/v1/relay/responses/retrieve"),
    "cancel": ("POST", "/api/v1/relay/requests/cancel"),
}
LIMITS = {
    "attempts": 58,
    "jobs": 3,
    "job_seconds": 150,
    "polls": 12,
    "poll_spacing": 10,
    "request_seconds": 3,
    "http_bytes": 16384,
    "application_bytes": 1024,
    "plaintext_bytes": 4096,
    "assistant_bytes": 4096,
    "max_tokens": 64,
    "concurrency": 1,
    "retries": 0,
}
GATES = ("authorization", "headroom", "isolation", "edge_origin", "compute", "worker_budget")
SCENARIOS = ("healthy", "pending", "quota", "memory", "missing_telemetry", "ack_failure")

# Only these fixed outcomes may leave a replay, including injected-provider failures.
STOP_REASONS = frozenset(
    [
        "acknowledgement",
        "admission",
        "attempt_limit",
        "binding",
        "body_limit",
        "clock",
        "completion",
        "crypto_source",
        "decryption",
        "envelope",
        "expiry",
        "health",
        "identity",
        "interrupted",
        "invalid_body",
        "job_deadline",
        "malformed_pending",
        "memory",
        "offline_transport",
        "operation",
        "operation_limit",
        "poll_limit",
        "prerequisites",
        "recovery_memory",
        "redirect",
        "request_deadline",
        "reservation_deadline",
        "restart",
        "selection",
        "status",
        "telemetry_cadence",
        "telemetry_missing",
        "transport",
        "unexpected_status",
        "unknown_scenario",
    ]
)


class Stop(ValueError):
    """Only internally assigned finite reason codes may leave the replay."""


def need(condition, code):
    if not condition:
        raise Stop(code)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def encoded(value, cap):
    try:
        data = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise Stop("invalid_body") from None
    need(len(data) <= cap, "body_limit")
    return data


def plan():
    return {
        "kind": "offline-plan",
        "live_execution": False,
        "image": IMAGE,
        "source": SOURCE,
        "memory_bytes": MEMORY,
        "phases_seconds": PHASES,
        "duration_seconds": 2340,
        "limits": LIMITS,
        "routes": ROUTES,
        "required_live_gates": GATES,
        "request_scope": "test-client only; worker and existing traffic excluded",
        "expiry": "separately reviewed per-run expiry required; no permanent default",
        "crypto": "reuse application-owned encryption; fixtures are not encryption",
    }


@dataclass
class Reply:
    status: int
    body: dict = field(default_factory=dict)
    seconds: float = 0
    size: int | None = None
    redirected: bool = False


class Fixture:
    """Synthetic protocol assertions, never a provider of live evidence.

    Ciphertext, keys and decryption assertions below are placeholders. They exercise
    lifecycle binding only and must never be represented as successful encryption.
    """

    def __init__(self, scenario="healthy"):
        need(scenario in SCENARIOS, "unknown_scenario")
        self.scenario = scenario
        self.now = 0
        self.expires = 2400
        self.gates = dict.fromkeys(GATES, True)
        self.polls = 0
        self.completed_response = False
        self.calls = []

    def advance_to(self, target):
        self.now = target

    def elapse(self, seconds):
        self.now += seconds

    def new_job(self, number):
        return (f"fixture-client-{number}", f"fixture-request-{number}", f"fixture-cancel-{number}")

    def observe(self):
        return {
            "sample_at": self.now,
            "cadence": 30,
            "working_set": 70 * 1024 * 1024,
            "ready": True,
            "scrape": True,
            "restarts": 0,
            "oom": False,
            "identity": "fixture-pod",
            "image": IMAGE,
            "memory_limit": MEMORY,
            "memory_request": MEMORY,
            "replicas": 1,
            **({"working_set": ABORT_MEMORY} if self.scenario == "memory" else {}),
            **({"sample_at": self.now - 61} if self.scenario == "missing_telemetry" else {}),
        }

    def call(self, operation, body):
        self.calls.append((self.now, operation, body))
        if operation == "unmatched":
            return Reply(429 if self.scenario == "quota" else 404)
        if operation == "select":
            self.polls = 0
            self.completed_response = False
            return Reply(
                200,
                {
                    "server_public_key": "fixture-server-key",
                    "reservation_token": "fixture-reservation",
                    "request_deadline_epoch": self.now + 600,
                    "resolved_model": MODEL,
                    "selected_context_tier": TIER,
                },
            )
        if operation == "submit":
            return Reply(
                200,
                {
                    "retrieval_credential": "fixture-reservation",
                    "request_deadline_remaining_seconds": body["request_deadline_epoch"] - self.now,
                    "request_ttl_seconds": body["request_deadline_epoch"] - self.now,
                },
            )
        if operation == "retrieve":
            self.polls += 1
            if self.polls < 12 or self.scenario == "pending":
                return Reply(202, {"status": "pending"})
            self.completed_response = True
            return Reply(
                200,
                {
                    "protocol": PROTOCOL,
                    "version": 1,
                    "client_public_key": body["client_public_key"],
                    "request_id": body["request_id"],
                    "ciphertext": "fixture-ciphertext",
                    "cipherkey": "fixture-key",
                    "iv": "fixture-iv",
                    "acknowledgement_token": "fixture-ack",
                },
            )
        if operation == "ack":
            return Reply(503 if self.scenario == "ack_failure" else 200, {"status": "acknowledged"})
        if operation == "cancel":
            # The deployed store never rewrites a completed terminal outcome to cancelled,
            # including after a lost acknowledgement. Cleanup remains unconfirmed here.
            return Reply(200, {"status": "completed" if self.completed_response else "cancelled"})
        return Reply(200)

    def seal(self, plaintext, server_key):
        # The separate ProtocolAdapter delegates to pinned application crypto.
        return {"ciphertext": "fixture-ciphertext", "cipherkey": "fixture-key", "iv": "fixture-iv"}

    def open(self, body):
        return {
            "protocol": PROTOCOL,
            "version": 1,
            "request_id": body["request_id"],
            "api_v1_response": {"message": {"role": "assistant", "content": "OK"}},
        }


class Harness:
    """Deterministic offline state machine; this class does not perform I/O."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.phase = "baseline"
        self.counts = Counter()
        self.statuses = Counter()
        self.completed = 0
        self.samples = 0
        self.peak = 0
        self.identity = None
        self.baseline_restarts = None
        self.job_end = None
        self.job_counts = Counter()
        self.cleanup = "not_needed"
        self.pending = None
        self.started = fixture.now

    def observe(self):
        f = self.fixture
        need(finite(f.now) and finite(f.expires) and f.now < f.expires, "expiry")
        need(
            set(f.gates) == set(GATES) and all(x is True for x in f.gates.values()), "prerequisites"
        )
        s = f.observe()
        need(finite(s["cadence"]) and 0 < s["cadence"] <= 30, "telemetry_cadence")
        need(
            finite(s["sample_at"]) and 0 <= f.now - s["sample_at"] < 2 * s["cadence"],
            "telemetry_missing",
        )
        need(finite(s["working_set"]) and 0 <= s["working_set"], "memory")
        self.samples += 1
        self.peak = max(self.peak, s["working_set"])
        need(s["working_set"] < ABORT_MEMORY, "memory")
        if self.phase in {"baseline", "recovery"}:
            need(s["working_set"] < RECOVERY_MEMORY, "recovery_memory")
        need(s["ready"] is True and s["scrape"] is True and s["oom"] is False, "health")
        need(type(s["restarts"]) is int and s["restarts"] >= 0, "restart")
        if self.baseline_restarts is None:
            self.baseline_restarts = s["restarts"]
        need(s["restarts"] == self.baseline_restarts, "restart")
        coordinates = (
            s["identity"],
            s["image"],
            s["memory_limit"],
            s["memory_request"],
            s["replicas"],
        )
        need(type(s["replicas"]) is int, "identity")
        need(coordinates[1:] == (IMAGE, MEMORY, MEMORY, 1), "identity")
        need(isinstance(s["identity"], str) and bool(s["identity"].strip()), "identity")
        if self.identity is None:
            self.identity = coordinates
        need(coordinates == self.identity, "identity")

    def wait(self, target):
        need(finite(target) and target >= self.fixture.now, "clock")
        while self.fixture.now < target:
            self.fixture.advance_to(min(target, self.fixture.now + 30))
            self.observe()

    def request(self, operation, body=None, *, cleanup=False):
        need(operation in ROUTES, "operation")
        if not cleanup:
            self.observe()
        else:
            # No cleanup traffic after expiry or fixture identity loss.
            need(self.fixture.now < self.fixture.expires, "expiry")
            s = self.fixture.observe()
            need(
                (s["identity"], s["image"], s["memory_limit"], s["memory_request"], s["replicas"])
                == self.identity,
                "identity",
            )
        need(sum(self.counts.values()) < LIMITS["attempts"], "attempt_limit")
        if self.job_end is not None:
            need(self.fixture.now + LIMITS["request_seconds"] <= self.job_end, "job_deadline")
            cap = 12 if operation == "retrieve" else 1
            need(self.job_counts[operation] < cap, "operation_limit")
            self.job_counts[operation] += 1
        need(self.fixture.now + LIMITS["request_seconds"] < self.fixture.expires, "expiry")
        if body is not None:
            encoded(body, LIMITS["http_bytes"])
        self.counts[operation] += 1  # An uncertain response still consumes an attempt.
        reply = self.fixture.call(operation, body)
        need(finite(reply.seconds) and reply.seconds >= 0, "request_deadline")
        self.fixture.elapse(min(reply.seconds, 3))
        need(reply.seconds <= 3, "request_deadline")
        need(reply.redirected is False, "redirect")
        need(type(reply.status) is int and 100 <= reply.status <= 599, "status")
        self.statuses[str(reply.status)] += 1
        encoded(reply.body, LIMITS["http_bytes"])
        if reply.size is not None:
            need(type(reply.size) is int and 0 <= reply.size <= LIMITS["http_bytes"], "body_limit")
        if not cleanup:
            self.observe()
        return reply

    def expect(self, operation, body=None, status=200):
        reply = self.request(operation, body)
        need(reply.status == status, "unexpected_status")
        return reply.body

    def job(self, number):
        self.job_end = self.fixture.now + LIMITS["job_seconds"]
        self.job_counts = Counter()
        key, request_id, proof = self.fixture.new_job(number)
        binding = {"client_public_key": key, "request_id": request_id}
        # Selection may reserve even when its response is lost. Retain cleanup coordinates first.
        self.pending = {
            **binding,
            "cancel_token": proof,
            "status": "cancelled",
            "reason": "requester_cancelled",
        }
        selected = self.expect(
            "select", {**binding, "cancel_token": proof, "model": MODEL, "context_tier": TIER}
        )
        need(
            selected.get("resolved_model") == MODEL
            and selected.get("selected_context_tier") == TIER,
            "selection",
        )
        deadline = selected.get("request_deadline_epoch")
        need(finite(deadline) and deadline > self.fixture.now, "reservation_deadline")
        for field_name in ("reservation_token", "server_public_key"):
            need(isinstance(selected.get(field_name), str) and selected[field_name], "selection")
        application = {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "options": {"max_tokens": 64, "temperature": 0, "stream": False},
        }
        encoded(application, LIMITS["application_bytes"])
        plaintext = {**binding, "protocol": PROTOCOL, "version": 1, "api_v1_request": application}
        encoded(plaintext, LIMITS["plaintext_bytes"])
        encrypted = self.fixture.seal(plaintext, selected["server_public_key"])
        need(
            set(encrypted) == {"ciphertext", "cipherkey", "iv"}
            and all(isinstance(v, str) and v for v in encrypted.values()),
            "envelope",
        )
        submit_started = self.fixture.now
        submitted = self.expect(
            "submit",
            {
                **binding,
                **encrypted,
                "protocol": PROTOCOL,
                "version": 1,
                "cancel_token": proof,
                "server_public_key": selected["server_public_key"],
                "reservation_token": selected["reservation_token"],
                "requested_model": MODEL,
                "requested_context_tier": TIER,
                "request_deadline_epoch": deadline,
            },
        )
        remaining = submitted.get("request_deadline_remaining_seconds")
        need(
            finite(remaining)
            and 0 < remaining <= deadline - submit_started
            and finite(submitted.get("request_ttl_seconds"))
            and submitted.get("request_ttl_seconds") == remaining
            and submitted.get("retrieval_credential") == selected["reservation_token"],
            "admission",
        )
        retrieval = {**binding, "retrieval_credential": submitted["retrieval_credential"]}
        admitted = self.fixture.now
        for poll in range(1, 13):
            self.wait(admitted + poll * 10)
            need(self.fixture.now + 3 < deadline, "reservation_deadline")
            response = self.request("retrieve", retrieval)
            if response.status == 202:
                need(response.body.get("status") == "pending", "malformed_pending")
                continue
            need(response.status == 200, "unexpected_status")
            body = response.body
            need(
                body.get("protocol") == PROTOCOL
                and type(body.get("version")) is int
                and body["version"] == 1
                and all(body.get(k) == v for k, v in binding.items()),
                "binding",
            )
            need(
                all(
                    isinstance(body.get(k), str) and body[k]
                    for k in ("ciphertext", "cipherkey", "iv", "acknowledgement_token")
                ),
                "envelope",
            )
            clear = self.fixture.open(body)
            encoded(clear, LIMITS["plaintext_bytes"])
            need(
                clear.get("protocol") == PROTOCOL
                and type(clear.get("version")) is int
                and clear["version"] == 1
                and clear.get("request_id") == request_id,
                "binding",
            )
            result = clear.get("api_v1_response", {})
            message = result.get("message", {})
            need(
                not result.get("error")
                and message.get("role") == "assistant"
                and isinstance(message.get("content"), str)
                and message["content"].strip(),
                "completion",
            )
            need(len(message["content"].encode("utf-8")) <= LIMITS["assistant_bytes"], "body_limit")
            acknowledged = self.expect(
                "ack", {**retrieval, "acknowledgement_token": body["acknowledgement_token"]}
            )
            need(acknowledged.get("status") == "acknowledged", "acknowledgement")
            self.pending = None
            self.completed += 1
            self.job_end = None
            return
        raise Stop("poll_limit")

    def cancel(self):
        if self.pending is None:
            return
        self.cleanup = "unconfirmed"
        try:
            response = self.request("cancel", self.pending, cleanup=True)
            if response.status == 200 and response.body.get("status") == "cancelled":
                self.cleanup = "relay_cancelled_compute_unproven"
        except (Exception, KeyboardInterrupt):
            pass
        self.pending = None

    def run(self):
        outcome, reason = "passed", "none"
        try:
            self.observe()
            need(self.fixture.expires > self.started + 2340, "expiry")
            self.wait(self.started + 300)
            self.phase = "public"
            for index, route in enumerate(("root", "metadata", "version", "healthz", "livez")):
                self.wait(self.started + 300 + index * 60)
                self.expect(route)
            self.wait(self.started + 600)
            self.phase = "unmatched"
            for index in range(5):
                self.wait(self.started + 600 + index * 60)
                self.expect("unmatched", status=404)
            self.wait(self.started + 900)
            self.phase = "e2ee"
            for number in range(3):
                self.wait(self.started + 900 + number * 180)
                self.job(number)
            self.wait(self.started + 1440)
            self.phase = "recovery"
            self.observe()
            self.wait(self.started + 2340)
        except Stop as exc:
            code = exc.args[0] if len(exc.args) == 1 else None
            reason = code if type(code) is str and code in STOP_REASONS else "fixture_error"
            outcome = "stopped"
            self.cancel()
        except (Exception, KeyboardInterrupt):
            outcome, reason = "stopped", "fixture_error"
            self.cancel()
        return {
            "kind": "offline-replay",
            "outcome": outcome,
            "reason": reason,
            "phase": self.phase,
            "attempts": sum(self.counts.values()),
            "attempts_by_operation": dict(self.counts),
            "status_counts": dict(self.statuses),
            "completed_fixture_jobs": self.completed,
            "elapsed_seconds": self.fixture.now - self.started,
            "samples": self.samples,
            "sampled_peak_bytes": self.peak,
            "cleanup": self.cleanup,
            "live_execution": False,
            "encryption_verified": False,
            "capacity_or_headroom_proven": False,
            "worker_traffic_bounded": False,
        }


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # Unsupported live options may contain credentials or private paths. Never echo argv.
        self.exit(
            2, "load replay: invalid arguments; only offline plan or built-in scenario allowed\n"
        )


def main(argv=None):
    parser = SafeParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scenario", choices=SCENARIOS, help="run a built-in offline fixture")
    mode.add_argument("--plan", action="store_true", help="print the non-executing plan")
    args = parser.parse_args(argv)
    result = Harness(Fixture(args.scenario)).run() if args.scenario else plan()
    print(json.dumps(result, indent=2))
    return 0 if result.get("outcome", "passed") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
