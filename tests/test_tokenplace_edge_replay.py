"""Offline evidence for rejecting a broad unmatched-path limiter."""

import importlib.util
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
