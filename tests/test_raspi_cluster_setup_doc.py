from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "raspi_cluster_setup.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_happy_path_section_exists(doc_text: str) -> None:
    assert "## Happy Path: 3-server `dev` cluster in two runs" in doc_text


def test_happy_path_commands_present(doc_text: str) -> None:
    assert "export SUGARKUBE_SERVERS=3" in doc_text
    # ensure the guidance to rerun just up is copyable and explicit
    assert "just up dev              # 1st run patches memory cgroups and reboots" in doc_text
    assert "just up dev              # 2nd run bootstraps or joins k3s" in doc_text


def test_double_run_explained(doc_text: str) -> None:
    assert "Each additional Pi repeats the same two `just up dev` runs" in doc_text
    assert "runs `just up dev` twice" in doc_text or "Run `just up dev` twice" in doc_text


def test_doc_mentions_automatic_cgroup_fix(doc_text: str) -> None:
    assert "scripts/check_memory_cgroup.sh" in doc_text
    assert "No manual editing of `/boot/cmdline.txt`" in doc_text


def test_manual_cmdline_edits_removed(doc_text: str) -> None:
    assert "cgroup_enable=memory" not in doc_text


def test_token_export_is_documented(doc_text: str) -> None:
    assert "export SUGARKUBE_TOKEN_DEV" in doc_text


def test_recovery_wipe_block_present(doc_text: str) -> None:
    assert "```bash\njust wipe\n```" in doc_text


def test_recovery_mdns_command_present(doc_text: str) -> None:
    assert "avahi-browse --all --resolve --terminate" in doc_text


def test_doc_describes_save_debug_logs(doc_text: str) -> None:
    assert "export SAVE_DEBUG_LOGS=1" in doc_text
    assert "unset SAVE_DEBUG_LOGS" in doc_text
    assert "logs/debug/just-up/" in doc_text
