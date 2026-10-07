"""No network or live evidence: exercise the bounded K133 protocol state machine."""

import copy
import json
import runpy
import socket
import subprocess
import sys
import urllib.request

import pytest

from scripts import tokenplace_load_replay as load


@pytest.fixture(autouse=True)
def no_network_or_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline harness attempted external I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


class Fault(load.Fixture):
    def __init__(self, *, operation=None, mutate=None, observation=None, decrypted=None):
        super().__init__()
        self.operation, self.mutate = operation, mutate
        self.observation, self.decrypted = observation, decrypted
        self.plaintexts = []

    def call(self, operation, body):
        reply = super().call(operation, body)
        if operation == self.operation:
            return self.mutate(reply, body)
        return reply

    def observe(self):
        result = super().observe()
        if self.observation:
            result.update(self.observation(self.now))
        return result

    def seal(self, plaintext, server_key):
        self.plaintexts.append(copy.deepcopy(plaintext))
        return super().seal(plaintext, server_key)

    def open(self, body):
        value = super().open(body)
        return self.decrypted(value) if self.decrypted else value


def changed(reply, **fields):
    for key, value in fields.items():
        setattr(reply, key, value)
    return reply


def body_changed(reply, **fields):
    reply.body.update(fields)
    return reply


def test_exact_schedule_and_worst_success_budget():
    fixture = Fault()
    report = load.Harness(fixture).run()
    assert report["outcome"] == "passed"
    assert report["elapsed_seconds"] == 39 * 60
    assert report["attempts"] == 55 < load.LIMITS["attempts"] == 58
    assert report["attempts_by_operation"] == {
        "root": 1,
        "metadata": 1,
        "version": 1,
        "healthz": 1,
        "livez": 1,
        "unmatched": 5,
        "select": 3,
        "submit": 3,
        "retrieve": 36,
        "ack": 3,
    }
    assert report["completed_fixture_jobs"] == 3
    assert not any(
        report[key]
        for key in (
            "live_execution",
            "encryption_verified",
            "capacity_or_headroom_proven",
            "worker_traffic_bounded",
        )
    )
    assert [
        time
        for time, op, _ in fixture.calls
        if op in ("root", "metadata", "version", "healthz", "livez")
    ] == [300, 360, 420, 480, 540]
    assert [time for time, op, _ in fixture.calls if op == "unmatched"] == [600, 660, 720, 780, 840]
    assert [time for time, op, _ in fixture.calls if op == "select"] == [900, 1080, 1260]
    polls = [time for time, op, _ in fixture.calls if op == "retrieve"]
    assert polls == [start + slot * 10 for start in (900, 1080, 1260) for slot in range(1, 13)]
    assert all(300 <= time < 1440 for time, _, _ in fixture.calls)


def test_source_protocol_bindings_and_no_plaintext_transport():
    fixture = Fault()
    assert load.Harness(fixture).run()["outcome"] == "passed"
    for number in range(3):
        plaintext = fixture.plaintexts[number]
        assert plaintext["api_v1_request"] == {
            "model": load.MODEL,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "options": {"max_tokens": 64, "temperature": 0, "stream": False},
        }
        key, request_id = f"fixture-client-{number}", f"fixture-request-{number}"
        calls = [
            (op, body)
            for _, op, body in fixture.calls
            if isinstance(body, dict) and body.get("request_id") == request_id
        ]
        select = dict(calls)["select"]
        submit = dict(calls)["submit"]
        ack = dict(calls)["ack"]
        assert select["client_public_key"] == submit["client_public_key"] == key
        assert select["cancel_token"] == submit["cancel_token"]
        assert submit["reservation_token"] == ack["retrieval_credential"] == "fixture-reservation"
        assert submit["request_deadline_epoch"] == 1500 + number * 180  # Never rewritten to 150s.
        assert ack["acknowledgement_token"] == "fixture-ack"
        assert not {"messages", "api_v1_request", "options", "model"}.intersection(submit)
        assert not {"ciphertext", "cipherkey", "iv"}.intersection(ack)
    # The deployed inner response has no client_public_key; binding is verified on the outer one.
    opened = fixture.open({"request_id": "fixture-request"})
    assert "client_public_key" not in opened


@pytest.mark.parametrize(
    "scenario,reason,attempts",
    [
        ("pending", "poll_limit", 25),
        ("quota", "unexpected_status", 6),
        ("memory", "memory", 0),
        ("missing_telemetry", "telemetry_missing", 0),
        ("ack_failure", "unexpected_status", 26),
    ],
)
def test_failure_scenarios_stop_without_retry(scenario, reason, attempts):
    fixture = load.Fixture(scenario)
    report = load.Harness(fixture).run()
    assert report["outcome"] == "stopped" and report["reason"] == reason
    assert report["attempts"] == attempts
    assert report["completed_fixture_jobs"] == 0
    assert report["attempts_by_operation"].get("select", 0) <= 1
    if scenario in {"pending", "ack_failure"}:
        assert report["cleanup"] == (
            "unconfirmed" if scenario == "ack_failure" else "relay_cancelled_compute_unproven"
        )
        assert report["attempts_by_operation"]["cancel"] == 1


@pytest.mark.parametrize("gate", load.GATES)
@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_unknown_or_forged_gate_never_starts(gate, value):
    fixture = load.Fixture()
    fixture.gates[gate] = value
    report = load.Harness(fixture).run()
    assert report["reason"] == "prerequisites"
    assert fixture.calls == []


@pytest.mark.parametrize("expiry", [0, 2340, float("nan"), float("inf"), True])
def test_expiry_is_per_run_and_requires_full_recovery(expiry):
    fixture = load.Fixture()
    fixture.expires = expiry
    assert load.Harness(fixture).run()["reason"] == "expiry"
    assert fixture.calls == []


@pytest.mark.parametrize(
    "values,reason",
    [
        ({"working_set": load.ABORT_MEMORY}, "memory"),
        ({"working_set": float("nan")}, "memory"),
        ({"working_set": load.RECOVERY_MEMORY}, "recovery_memory"),
        ({"ready": False}, "health"),
        ({"scrape": False}, "health"),
        ({"oom": True}, "health"),
        ({"cadence": 31}, "telemetry_cadence"),
        ({"cadence": 0}, "telemetry_cadence"),
        ({"sample_at": -60}, "telemetry_missing"),
        ({"sample_at": 1}, "telemetry_missing"),
        ({"restarts": True}, "restart"),
        ({"image": "different"}, "identity"),
        ({"memory_limit": load.MEMORY * 2}, "identity"),
        ({"memory_request": 1}, "identity"),
        ({"replicas": 2}, "identity"),
    ],
)
def test_invalid_baseline(values, reason):
    fixture = Fault(observation=lambda _: values)
    assert load.Harness(fixture).run()["reason"] == reason
    assert not fixture.calls


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("identity", "changed-pod", "identity"),
        ("restarts", 1, "restart"),
        ("oom", True, "health"),
        ("working_set", load.ABORT_MEMORY, "memory"),
    ],
)
def test_mid_job_telemetry_failure_stops_and_limits_cleanup(field, value, reason):
    fixture = Fault(observation=lambda time: {field: value} if time >= 910 else {})
    report = load.Harness(fixture).run()
    assert report["reason"] == reason
    assert report["attempts_by_operation"].get("retrieve", 0) == 0
    assert report["attempts_by_operation"].get("select") == 1
    assert report["cleanup"] == (
        "unconfirmed" if field == "identity" else "relay_cancelled_compute_unproven"
    )


@pytest.mark.parametrize("operation", ["root", "unmatched", "select", "submit", "retrieve", "ack"])
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_unexpected_statuses_stop(operation, status):
    fixture = Fault(operation=operation, mutate=lambda r, _: changed(r, status=status))
    report = load.Harness(fixture).run()
    assert report["outcome"] == "stopped" and report["reason"] == "unexpected_status"
    assert report["attempts_by_operation"][operation] == 1
    assert report["attempts_by_operation"].get("cancel", 0) <= 1


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"redirected": True}, "redirect"),
        ({"seconds": 3.01}, "request_deadline"),
        ({"seconds": -1}, "request_deadline"),
        ({"seconds": float("nan")}, "request_deadline"),
        ({"size": 16385}, "body_limit"),
        ({"size": True}, "body_limit"),
        ({"body": {"untrusted": "secret" * 4096}}, "body_limit"),
        ({"status": True}, "status"),
        ({"status": 600}, "status"),
    ],
)
def test_bounded_transport_model(fields, reason):
    fixture = Fault(operation="submit", mutate=lambda r, _: changed(r, **fields))
    report = load.Harness(fixture).run()
    assert report["reason"] == reason
    assert report["attempts_by_operation"]["submit"] == 1
    assert report["attempts_by_operation"]["cancel"] == 1
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize(
    "fields",
    [
        {"resolved_model": "fallback"},
        {"selected_context_tier": "64k-full"},
        {"reservation_token": ""},
        {"server_public_key": None},
    ],
)
def test_selection_never_falls_back(fields):
    fixture = Fault(operation="select", mutate=lambda r, _: body_changed(r, **fields))
    report = load.Harness(fixture).run()
    assert report["reason"] == "selection"
    assert "submit" not in report["attempts_by_operation"]
    assert report["attempts_by_operation"]["cancel"] == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"retrieval_credential": "other"},
        {"request_ttl_seconds": 1},
        {"request_deadline_remaining_seconds": float("inf")},
        {"request_ttl_seconds": 700, "request_deadline_remaining_seconds": 700},
    ],
)
def test_admission_uses_source_remaining_ttl_not_invented_epoch(fields):
    fixture = Fault(operation="submit", mutate=lambda r, _: body_changed(r, **fields))
    report = load.Harness(fixture).run()
    assert report["reason"] == (
        "invalid_body"
        if fields.get("request_deadline_remaining_seconds") == float("inf")
        else "admission"
    )
    assert "retrieve" not in report["attempts_by_operation"]


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"protocol": "other"}, "binding"),
        ({"version": True}, "binding"),
        ({"client_public_key": "other"}, "binding"),
        ({"request_id": "other"}, "binding"),
        ({"acknowledgement_token": ""}, "envelope"),
        ({"ciphertext": None}, "envelope"),
    ],
)
def test_outer_completion_binding(fields, reason):
    fixture = Fault(
        operation="retrieve",
        mutate=lambda r, _: body_changed(r, **fields) if r.status == 200 else r,
    )
    report = load.Harness(fixture).run()
    assert report["reason"] == reason
    assert "ack" not in report["attempts_by_operation"]
    assert report["attempts_by_operation"]["cancel"] == 1


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"request_id": "other"}, "binding"),
        ({"version": True}, "binding"),
        ({"api_v1_response": {"error": "private diagnostic"}}, "completion"),
        ({"api_v1_response": {"message": {"role": "user", "content": "OK"}}}, "completion"),
        ({"api_v1_response": {"message": {"role": "assistant", "content": ""}}}, "completion"),
        (
            {"api_v1_response": {"message": {"role": "assistant", "content": "x" * 4097}}},
            "body_limit",
        ),
    ],
)
def test_decrypted_assertion_binding_and_size(fields, reason):
    fixture = Fault(decrypted=lambda value: {**value, **fields})
    report = load.Harness(fixture).run()
    assert report["reason"] == reason
    assert "private diagnostic" not in json.dumps(report)
    assert "ack" not in report["attempts_by_operation"]


def test_uncertain_selection_is_not_retried_and_uses_original_cancel_proof():
    def lost(*_):
        raise RuntimeError("private URL and credentials")

    fixture = Fault(operation="select", mutate=lost)
    report = load.Harness(fixture).run()
    assert report["reason"] == "fixture_error"
    assert report["attempts_by_operation"]["select"] == 1
    assert report["attempts_by_operation"]["cancel"] == 1
    selection, cancel = fixture.calls[-2:]
    assert selection[2]["cancel_token"] == cancel[2]["cancel_token"]
    assert "private" not in json.dumps(report)


def test_failed_cancellation_is_not_success_or_retry():
    fixture = Fault(operation="cancel", mutate=lambda r, _: changed(r, status=503))
    fixture.scenario = "pending"
    report = load.Harness(fixture).run()
    assert report["cleanup"] == "unconfirmed"
    assert report["outcome"] == "stopped"
    assert report["attempts_by_operation"]["cancel"] == 1


def test_success_requires_acknowledgement_and_recovery():
    fixture = Fault(operation="ack", mutate=lambda r, _: body_changed(r, status="completed"))
    assert load.Harness(fixture).run()["reason"] == "acknowledgement"
    fixture = Fault(
        observation=lambda time: {"working_set": load.RECOVERY_MEMORY} if time >= 1441 else {}
    )
    report = load.Harness(fixture).run()
    assert report["completed_fixture_jobs"] == 3
    assert report["reason"] == "recovery_memory"
    assert report["outcome"] == "stopped"


def test_recovery_threshold_applies_at_exact_phase_entry():
    fixture = Fault(
        observation=lambda time: {"working_set": load.RECOVERY_MEMORY} if time == 1440 else {}
    )
    report = load.Harness(fixture).run()
    assert report["outcome"] == "stopped"
    assert report["reason"] == "recovery_memory"
    assert report["elapsed_seconds"] == 1440
    assert report["phase"] == "recovery"
    assert report["attempts"] == 55


def test_hard_attempt_and_job_deadline_guards():
    fixture = load.Fixture()
    harness = load.Harness(fixture)
    harness.counts["root"] = 58
    with pytest.raises(load.Stop, match="attempt_limit"):
        harness.request("root")
    harness.counts.clear()
    harness.job_end = fixture.now + 2.9
    with pytest.raises(load.Stop, match="job_deadline"):
        harness.request("select")
    assert fixture.calls == []


def test_no_live_cli_and_no_expiry_from_campaign_date(capsys):
    assert load.main(["--plan"]) == 0
    output = capsys.readouterr().out
    assert "2026-10-07" not in output
    assert json.loads(output)["live_execution"] is False
    for arguments in (
        ["--execute"],
        ["--url", "https://example.invalid"],
        ["--authorization", "evidence.json"],
    ):
        with pytest.raises(SystemExit) as error:
            load.main(arguments)
        assert error.value.code == 2
    assert load.main(["--scenario", "healthy"]) == 0
    assert load.main(["--scenario", "pending"]) == 1


@pytest.mark.parametrize("cap", [1024, 4096, 16384])
def test_byte_limits_include_utf8_and_serialization(cap):
    with pytest.raises(load.Stop, match="body_limit"):
        load.encoded("x" * cap, cap)
    assert len(load.encoded("x" * (cap - 2), cap)) == cap
    with pytest.raises(load.Stop, match="body_limit"):
        load.encoded("\u00e9" * cap, cap)


def test_script_entrypoint_still_has_no_network(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [load.__file__, "--scenario", "healthy"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(load.__file__, run_name="__main__")
    assert result.value.code == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "offline-replay"


def test_response_latency_does_not_compress_poll_slots():
    fixture = Fault(operation="retrieve", mutate=lambda r, _: changed(r, seconds=3))
    report = load.Harness(fixture).run()
    assert report["outcome"] == "passed"
    times = [time for time, op, _ in fixture.calls if op == "retrieve"]
    assert all(b - a >= 10 for a, b in zip(times, times[1:]))
    assert report["elapsed_seconds"] == 2340


def test_lost_ack_never_completes_or_retries_job():
    def interrupted(*_):
        raise KeyboardInterrupt()

    fixture = Fault(operation="ack", mutate=interrupted)
    report = load.Harness(fixture).run()
    assert report["reason"] == "fixture_error"
    assert report["completed_fixture_jobs"] == 0
    assert report["attempts_by_operation"]["ack"] == 1
    assert report["attempts_by_operation"]["cancel"] == 1
    assert report["cleanup"] == "unconfirmed"


def test_expiry_revoked_after_admission_blocks_cleanup():
    fixture = Fault()

    def expire(reply, _):
        fixture.expires = fixture.now
        return reply

    fixture.operation, fixture.mutate = "submit", expire
    report = load.Harness(fixture).run()
    assert report["reason"] == "expiry"
    assert report["cleanup"] == "unconfirmed"
    assert "cancel" not in report["attempts_by_operation"]


def test_per_operation_guard_and_missed_slot_fail_closed():
    harness = load.Harness(load.Fixture())
    harness.job_end = 150
    harness.job_counts["retrieve"] = 12
    with pytest.raises(load.Stop, match="operation_limit"):
        harness.request("retrieve")
    harness.fixture.now = 11
    with pytest.raises(load.Stop, match="clock"):
        harness.wait(10)
    assert harness.fixture.calls == []


def test_remaining_server_deadline_cannot_be_extended():
    fixture = Fault(
        operation="select", mutate=lambda r, _: body_changed(r, request_deadline_epoch=905)
    )
    report = load.Harness(fixture).run()
    assert report["reason"] == "reservation_deadline"
    assert "retrieve" not in report["attempts_by_operation"]
    assert report["attempts_by_operation"]["cancel"] == 1


def test_no_plaintext_fallback_when_sealing_fails(monkeypatch):
    fixture = load.Fixture()
    monkeypatch.setattr(fixture, "seal", lambda *args: {"messages": "private plaintext"})
    report = load.Harness(fixture).run()
    assert report["reason"] == "envelope"
    assert "submit" not in report["attempts_by_operation"]
    assert "private plaintext" not in json.dumps(report)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--url", "https://private-user:private-token@example.invalid/private-path?private-query"],
        ["--authorization", "/private-evidence-path"],
        ["--scenario", "private-value"],
        ["--plan", "--scenario", "healthy"],
    ],
)
def test_rejected_arguments_never_echo_private_values(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        load.main(arguments)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "load replay: invalid arguments; only offline plan or built-in scenario allowed\n"
    )
