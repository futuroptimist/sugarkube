"""Tests for SUGARKUBE_SIMPLE_DISCOVERY feature flag (Phase 3)."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_simple_discovery_variable_defined() -> None:
    """Test that SIMPLE_DISCOVERY variable is defined in k3s-discover.sh."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    
    # Check for the variable definition
    assert 'SIMPLE_DISCOVERY="${SUGARKUBE_SIMPLE_DISCOVERY' in script_content, \
        "SIMPLE_DISCOVERY should be defined from SUGARKUBE_SIMPLE_DISCOVERY"
    
    # Verify default is 1 (new behavior enabled by default)
    lines = script_content.splitlines()
    found_default = False
    
    for line in lines:
        if 'SIMPLE_DISCOVERY=' in line and 'SUGARKUBE_SIMPLE_DISCOVERY' in line:
            # Should default to 1
            if ':-1}' in line:
                found_default = True
                break
    
    assert found_default, "SIMPLE_DISCOVERY should default to 1 (simplified discovery enabled by default)"


def test_discover_via_nss_and_api_function_exists() -> None:
    """Test that discover_via_nss_and_api function is defined."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    
    # Check for function definition
    assert 'discover_via_nss_and_api()' in script_content, \
        "discover_via_nss_and_api function should be defined"
    
    # Verify it uses getent for NSS resolution
    assert 'getent hosts' in script_content, \
        "Function should use getent for NSS resolution"
    
    # Verify it uses wait_for_remote_api_ready
    lines = script_content.splitlines()
    in_function = False
    found_api_check = False
    
    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True
        
        if in_function and 'wait_for_remote_api_ready' in line:
            found_api_check = True
            break
        
        # Exit function scope at next function definition
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break
    
    assert found_api_check, "Function should use wait_for_remote_api_ready to check API"


def test_simple_discovery_iterates_servers() -> None:
    """Test that simple discovery iterates through sugarkube{0..N}.local."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()
    
    # Find the function and verify it iterates through servers
    in_function = False
    found_iteration = False
    found_candidate_pattern = False
    
    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True
        
        if in_function:
            # Check for loop through server indices
            if 'for idx in' in line or 'seq 0' in line:
                found_iteration = True
            
            # Check for sugarkube${idx}.local pattern
            if 'sugarkube' in line and '${idx}' in line and '.local' in line:
                found_candidate_pattern = True
            
            if found_iteration and found_candidate_pattern:
                break
        
        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break
    
    assert found_iteration, "Function should iterate through server indices"
    assert found_candidate_pattern, "Function should try sugarkube{0..N}.local pattern"


def test_simple_discovery_conditional_in_main_flow() -> None:
    """Test that main flow checks SIMPLE_DISCOVERY flag."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    
    # Check for conditional that checks SIMPLE_DISCOVERY
    assert 'SIMPLE_DISCOVERY' in script_content and '= "1"' in script_content, \
        "Main flow should check if SIMPLE_DISCOVERY = 1"
    
    lines = script_content.splitlines()
    found_conditional = False
    found_function_call = False
    
    for i, line in enumerate(lines):
        # Look for the conditional check
        if 'SIMPLE_DISCOVERY' in line and '= "1"' in line and 'if' in line:
            found_conditional = True
            
            # Check that discover_via_nss_and_api is called nearby
            for j in range(i, min(i+30, len(lines))):
                if 'discover_via_nss_and_api' in lines[j]:
                    found_function_call = True
                    break
            
            if found_function_call:
                break
    
    assert found_conditional, "Should have conditional checking SIMPLE_DISCOVERY = 1"
    assert found_function_call, "Should call discover_via_nss_and_api when enabled"


def test_simple_discovery_handles_bootstrap() -> None:
    """Test that simple discovery handles bootstrap case when no token present."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()
    
    # Find the discover_via_nss_and_api function
    in_function = False
    found_token_check = False
    found_bootstrap_path = False
    
    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True
        
        if in_function:
            # Check for TOKEN_PRESENT check (either = 0 or -eq 0)
            if 'TOKEN_PRESENT' in line and ('= 0' in line or '-eq 0' in line):
                found_token_check = True
            
            # Check for bootstrap mention
            if found_token_check and 'bootstrap' in line.lower():
                found_bootstrap_path = True
                break
        
        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break
    
    assert found_token_check, "Function should check TOKEN_PRESENT"
    assert found_bootstrap_path, "Function should handle bootstrap case when no token"


def test_simple_discovery_uses_servers_desired() -> None:
    """Test that simple discovery respects SERVERS_DESIRED variable."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()
    
    # Find the function and verify it uses SERVERS_DESIRED
    in_function = False
    found_servers_desired = False
    
    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True
        
        if in_function and 'SERVERS_DESIRED' in line:
            found_servers_desired = True
            break
        
        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break
    
    assert found_servers_desired, "Function should use SERVERS_DESIRED to determine how many servers to try"


def test_phase_3_comment_present() -> None:
    """Test that Phase 3 comments are present for documentation."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    
    # Check for Phase 3 documentation comments
    assert 'Phase 3:' in script_content or 'phase 3' in script_content.lower(), \
        "Should have Phase 3 documentation comments"
    
    # Verify it mentions simplified discovery or NSS
    lines = script_content.splitlines()
    phase3_mentioned = False
    
    for line in lines:
        if 'Phase 3' in line and ('simple' in line.lower() or 'nss' in line.lower()):
            phase3_mentioned = True
            break
    
    assert phase3_mentioned, "Phase 3 comments should mention simplified discovery or NSS"
