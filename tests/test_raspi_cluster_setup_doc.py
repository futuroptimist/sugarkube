from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "raspi_cluster_setup.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_highlights_happy_path_heading(doc_text: str) -> None:
    assert (
        "## Happy path: HA 3-server bootstrap" in doc_text
    ), "Guide should lead with the HA 3-server happy path"


def test_doc_calls_for_double_just_up_run(doc_text: str) -> None:
    first_run = doc_text.find("just up dev")
    assert first_run != -1, "Happy path must instruct users to run 'just up dev'"
    second_run = re.search(
        r"export SUGARKUBE_SERVERS=3\s+just up dev",
        doc_text,
    )
    assert (
        second_run is not None
    ), "Happy path should show 'export SUGARKUBE_SERVERS=3' followed by 'just up dev'"
    assert (
        second_run.start() > first_run
    ), "The HA rerun must appear after the initial 'just up dev' invocation"


def test_doc_guides_control_plane_bootstrap_exports(doc_text: str) -> None:
    assert re.search(
        r"export SUGARKUBE_SERVERS=3\s+export SUGARKUBE_TOKEN_DEV=",
        doc_text,
    ), "Control-plane bring-up must export server count and join token together"
