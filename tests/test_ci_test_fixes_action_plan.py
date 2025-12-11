"""Ensure the CI test fixes action plan no longer frames work as pending."""

from pathlib import Path


def test_action_plan_not_labelled_future_work():
    """The action plan now documents shipped fixes rather than future work."""

    doc = Path("notes/ci-test-fixes-action-plan.md").read_text(encoding="utf-8")
    lowered = doc.lower()

    assert "future work" not in lowered, "Action plan still frames items as future work"
    assert (
        "tests/test_ci_test_fixes_action_plan.py" in doc
    ), "Action plan should note regression coverage for the future-work cleanup"
