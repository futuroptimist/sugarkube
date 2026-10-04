"""Offline evidence for rejecting a broad unmatched-path limiter."""

import importlib.util
import itertools
import json
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/tokenplace_edge_replay.py"
SPEC = importlib.util.spec_from_file_location("edge_replay", SCRIPT)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def test_replay_bounds_candidate_but_exhibits_legitimate_404_collision(capsys):
    expected = {
        "unmatched_attempts": 3000,
        "candidate_forwarded": 300,
        "disabled_forwarded": 3000,
        "preserved_attempts": 144,
        "preserved_forwarded": 144,
        "legitimate_missing_attempts": 9,
        "legitimate_missing_blocked": 9,
        "unknown_forwarded": 3,
    }
    assert replay.replay() == expected == replay.replay()
    replay.main()
    assert json.loads(capsys.readouterr().out) == expected
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize("category", replay.CATEGORIES)
@pytest.mark.parametrize("method", replay.METHODS)
def test_disabled_candidate_passes_entire_finite_matrix(category, method):
    candidate = replay.Candidate()
    for _ in range(replay.BUDGET + 1):
        assert candidate.admit(category, method, 0)


def test_window_boundary_and_shared_budget_across_methods():
    candidate = replay.Candidate(True)
    for index in range(replay.BUDGET):
        assert candidate.admit("unmatched", replay.METHODS[index % len(replay.METHODS)], 59)
    assert not candidate.admit("unmatched", "GET", 59)
    assert candidate.admit("unmatched", "GET", 60)
    assert candidate.used == 1
    assert candidate.admit("unmatched", "GET", 180)
    assert candidate.used == 1


@pytest.mark.parametrize("category,method", [("raw-input", "GET"), ("unmatched", "CUSTOM")])
def test_rejects_unbounded_categories_without_echoing_input(category, method):
    with pytest.raises(ValueError, match="^unsupported finite category$"):
        replay.Candidate(True).admit(category, method, 0)


@pytest.mark.parametrize("second", [-1, 0.5, True, "raw-input"])
def test_rejects_invalid_time(second):
    with pytest.raises(ValueError, match="monotonic integer"):
        replay.Candidate(True).admit("unmatched", "GET", second)


def test_rejects_time_reversal_without_resetting_budget():
    candidate = replay.Candidate(True)
    candidate.admit("unmatched", "GET", 60)
    with pytest.raises(ValueError, match="monotonic integer"):
        candidate.admit("unmatched", "GET", 59)
    assert candidate.used == 1


TRUSTED = dict(capability="available", provenance="verified", normalization="equivalent")


def test_signal_replay_preserves_missing_pages_but_cannot_prove_safety_or_total_bound():
    assert replay.signal_replay() == {
        "signaled_attempts": 3000,
        "signaled_forwarded": 300,
        "unsignaled_attempts": 3000,
        "unsignaled_forwarded": 3000,
        "disabled_attack_forwarded": 6000,
        "preserved_forwarded": 144,
        "legitimate_missing_forwarded": 9,
        "false_signal_legitimate_blocked": 9,
        "unknown_forwarded": 3,
    }
    assert replay.signal_replay() == replay.signal_replay()


def test_exhaustive_signal_matrix_after_budget_exhaustion():
    candidate, disabled = replay.SignalCandidate(True), replay.SignalCandidate()
    for _ in range(replay.BUDGET):
        assert candidate.admit("unmatched", "GET", 0, signal="attack", **TRUSTED)
    for category, method, capability, provenance, signal, normalization in itertools.product(
        replay.CATEGORIES,
        replay.METHODS,
        replay.CAPABILITIES,
        replay.PROVENANCE,
        replay.SIGNALS,
        replay.NORMALIZATION,
    ):
        fields = dict(
            capability=capability, provenance=provenance, signal=signal, normalization=normalization
        )
        eligible = (category, capability, provenance, signal, normalization) == (
            "unmatched",
            "available",
            "verified",
            "attack",
            "equivalent",
        )
        assert candidate.admit(category, method, 0, **fields) is not eligible
        assert disabled.admit(category, method, 0, **fields)
    assert candidate.used == replay.BUDGET


@pytest.mark.parametrize("normalization", replay.NORMALIZATION)
def test_normalization_states_never_block_preserved_or_unknown_routes(normalization):
    candidate = replay.SignalCandidate(True)
    for category in (*replay.PRESERVED, "unknown"):
        for method in replay.METHODS:
            assert candidate.admit(
                category,
                method,
                0,
                capability="available",
                provenance="verified",
                signal="attack",
                normalization=normalization,
            )
    assert candidate.used == 0


@pytest.mark.parametrize("field", ["capability", "provenance", "signal", "normalization"])
@pytest.mark.parametrize("value", ["private-unbounded-value", None, True, [], {}])
def test_signal_states_reject_arbitrary_values_without_echo(field, value):
    with pytest.raises(ValueError, match="^unsupported finite signal state$"):
        replay.SignalCandidate(True).admit("unmatched", "GET", 0, **{field: value})


def test_signal_default_and_untrusted_inputs_do_not_consume_budget():
    candidate = replay.SignalCandidate(True)
    for _ in range(2 * replay.BUDGET):
        assert candidate.admit("unmatched", "GET", 0)
        assert candidate.admit("unmatched", "GET", 0, signal="attack", provenance="spoofed")
    assert candidate.used == 0
    for _ in range(replay.BUDGET):
        assert candidate.admit("unmatched", "GET", 59, signal="attack", **TRUSTED)
    assert not candidate.admit("unmatched", "POST", 59, signal="attack", **TRUSTED)
    assert candidate.admit("unmatched", "POST", 60, signal="attack", **TRUSTED)
    with pytest.raises(ValueError, match="monotonic integer"):
        candidate.admit("unmatched", "GET", 59, signal="attack", **TRUSTED)
