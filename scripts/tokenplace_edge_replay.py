#!/usr/bin/env python3
"""Offline counterexample for a shared unmatched-request budget; never an edge rule."""

import json
import random
from collections import Counter

PRESERVED = ("browser", "public", "health", "metrics", "e2ee", "compute")
CATEGORIES = (*PRESERVED, "unmatched", "unknown")
METHODS = ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "other")
BUDGET = 100
WINDOW_SECONDS = 60


class Candidate:
    """Hypothetical fixed-window budget with an oracle unmatched classifier.

    No path classifier or production adapter exists. Even perfect route knowledge
    cannot distinguish an ordinary missing URL from automated unmatched requests.
    One counter is shared, never keyed by a path or a client identity.
    """

    def __init__(self, enabled=False):
        self.enabled = enabled
        self.window = -1
        self.used = 0
        self.last_second = -1

    def admit(self, category, method, second):
        if category not in CATEGORIES or method not in METHODS:
            raise ValueError("unsupported finite category")
        if type(second) is not int or second < 0 or second < self.last_second:
            raise ValueError("replay time must be a nonnegative monotonic integer")
        self.last_second = second
        window = second // WINDOW_SECONDS
        if window != self.window:
            self.window, self.used = window, 0
        if not self.enabled or category != "unmatched":
            return True
        if self.used == BUDGET:
            return False
        self.used += 1
        return True


def replay():
    """Return only fixed aggregate keys from deterministic category-level traffic.

    Randomized methods/order stand in for distinct unmatched requests. No raw
    paths are generated or retained and no real router is exercised by this model.
    """
    rng = random.Random(2780)
    enabled, disabled = Candidate(True), Candidate()
    counts = Counter(
        unmatched_attempts=0,
        candidate_forwarded=0,
        disabled_forwarded=0,
        preserved_attempts=0,
        preserved_forwarded=0,
        legitimate_missing_attempts=0,
        legitimate_missing_blocked=0,
        unknown_forwarded=0,
    )
    for window in range(3):
        second = window * WINDOW_SECONDS
        for _ in range(1000):
            method = rng.choice(METHODS)
            counts["unmatched_attempts"] += 1
            counts["candidate_forwarded"] += enabled.admit("unmatched", method, second)
            counts["disabled_forwarded"] += disabled.admit("unmatched", method, second)
        matrix = [(category, method) for category in PRESERVED for method in METHODS]
        rng.shuffle(matrix)
        for category, method in matrix:
            counts["preserved_attempts"] += 1
            counts["preserved_forwarded"] += enabled.admit(category, method, second)
        # The matcher sees the same category for an ordinary stale bookmark.
        for method in ("GET", "HEAD", "OPTIONS"):
            counts["legitimate_missing_attempts"] += 1
            counts["legitimate_missing_blocked"] += not enabled.admit("unmatched", method, second)
        counts["unknown_forwarded"] += enabled.admit("unknown", "GET", second)
    return dict(counts)


def main():
    print(json.dumps(replay(), sort_keys=True))


if __name__ == "__main__":
    main()
