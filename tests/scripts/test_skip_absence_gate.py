"""Tests for SUGARKUBE_SKIP_ABSENCE_GATE feature flag (Phase 2)."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_skip_absence_gate_variable_defined() -> None:
    """Test that SKIP_ABSENCE_GATE variable is defined in k3s-discover.sh."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for the variable definition
    assert 'SKIP_ABSENCE_GATE="${SUGARKUBE_SKIP_ABSENCE_GATE' in script_content, \
        "SKIP_ABSENCE_GATE should be defined from SUGARKUBE_SKIP_ABSENCE_GATE"

    # Verify default is 1 (new behavior enabled by default)
    lines = script_content.splitlines()
    found_default = False

    for line in lines:
        if 'SKIP_ABSENCE_GATE=' in line and 'SUGARKUBE_SKIP_ABSENCE_GATE' in line:
            # Should default to 1
            if ':-1}' in line:
                found_default = True
                break

    assert found_default, "SKIP_ABSENCE_GATE should default to 1 (absence gate skipped by default)"


def test_skip_absence_gate_conditional_logic() -> None:
    """Test that absence gate is skipped when SKIP_ABSENCE_GATE=1."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find the conditional that checks SKIP_ABSENCE_GATE
    found_conditional = False
    found_skip_call = False

    for i, line in enumerate(lines):
        # Look for the conditional check
        if 'SKIP_ABSENCE_GATE' in line and '!= "1"' in line:
            found_conditional = True

            # Check that ensure_mdns_absence_gate is called inside the conditional
            for j in range(i, min(i+20, len(lines))):
                if 'ensure_mdns_absence_gate' in lines[j]:
                    found_skip_call = True
                    break

            if found_skip_call:
                break

    assert found_conditional, "Should have conditional checking SKIP_ABSENCE_GATE != 1"
    assert found_skip_call, "ensure_mdns_absence_gate should be called inside conditional"


def test_skip_absence_gate_logs_when_skipped() -> None:
    """Test that script logs when absence gate is skipped."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Verify logging when skipped
    assert 'absence_gate_skipped' in script_content, \
        "Should log event=absence_gate_skipped when gate is skipped"

    # Should mention the reason
    assert 'SUGARKUBE_SKIP_ABSENCE_GATE=1' in script_content, \
        "Log message should mention SUGARKUBE_SKIP_ABSENCE_GATE=1"


def test_skip_absence_gate_includes_systemd_check() -> None:
    """Test that systemd health check is performed when absence gate is skipped."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find the else block for SKIP_ABSENCE_GATE
    in_skip_block = False
    found_systemctl_check = False

    for i, line in enumerate(lines):
        if 'SKIP_ABSENCE_GATE' in line and '= "1"' in line:
            # Found the else block
            for j in range(i, min(i+30, len(lines))):
                if 'else' in lines[j] and 'systemctl' not in lines[j]:
                    in_skip_block = True

                if in_skip_block and 'systemctl is-active' in lines[j] and 'avahi-daemon' in lines[j]:
                    found_systemctl_check = True
                    break

                # Exit if we hit another major conditional
                if in_skip_block and lines[j].strip().startswith('if [ "'):
                    break

    assert found_systemctl_check, \
        "Should check avahi-daemon status with systemctl when absence gate is skipped"


def test_phase_2_comment_present() -> None:
    """Test that Phase 2 comments are present for documentation."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for Phase 2 documentation comments
    assert 'Phase 2:' in script_content or 'phase 2' in script_content.lower(), \
        "Should have Phase 2 documentation comments"

    # Verify it mentions skipping absence gate
    lines = script_content.splitlines()
    phase2_mentioned = False

    for line in lines:
        if 'Phase 2' in line and 'absence gate' in line.lower():
            phase2_mentioned = True
            break

    assert phase2_mentioned, "Phase 2 comments should mention absence gate"
