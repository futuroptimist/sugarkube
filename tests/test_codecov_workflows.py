"""Regression tests ensuring Codecov uploads stay enabled on PRs."""

from __future__ import annotations

from pathlib import Path


def _load_workflow(path: str) -> str:
    return Path(path).read_text()


def test_ci_workflow_uses_oidc_for_codecov():
    workflow = _load_workflow(".github/workflows/ci.yml")
    assert "codecov/codecov-action@v5" in workflow
    assert "use_oidc: true" in workflow
    assert "id-token: write" in workflow


def test_tests_workflow_uses_oidc_for_codecov_upload():
    workflow = _load_workflow(".github/workflows/tests.yml")
    assert "codecov/codecov-action@v5" in workflow
    assert "use_oidc: true" in workflow
    assert "upload-coverage:" in workflow
    upload_job = workflow.split("upload-coverage:", maxsplit=1)[1]
    assert "id-token: write" in upload_job
    assert "hashFiles('coverage.xml') != ''" in workflow
    assert "actions/upload-artifact@v4" in workflow
