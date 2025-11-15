"""Test that browse verification properly overrides SUGARKUBE_MDNS_NO_TERMINATE."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_publish_api_service_browse_verification_overrides_no_terminate() -> None:
    """Test that publish_api_service browse verification sets NO_TERMINATE=0."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()
    
    # Find publish_api_service function
    in_function = False
    found_browse_verification = False
    found_no_terminate_override = False
    
    for i, line in enumerate(lines):
        if 'publish_api_service()' in line:
            in_function = True
        
        if in_function:
            # Look for browse_verification assignment
            if 'browse_verification="$(' in line and 'run_avahi_query server-select' in line:
                found_browse_verification = True
                # Check if SUGARKUBE_MDNS_NO_TERMINATE=0 is in the same line
                if 'SUGARKUBE_MDNS_NO_TERMINATE=0' in line:
                    found_no_terminate_override = True
                    break
        
        # Exit function scope when we hit the next function
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'publish_api_service' not in line:
            break
    
    assert found_browse_verification, \
        "publish_api_service should have browse_verification when SAVE_DEBUG_LOGS=1"
    assert found_no_terminate_override, \
        "publish_api_service browse_verification should set SUGARKUBE_MDNS_NO_TERMINATE=0 to avoid infinite loop"


def test_publish_bootstrap_service_browse_verification_overrides_no_terminate() -> None:
    """Test that publish_bootstrap_service browse verification sets NO_TERMINATE=0."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()
    
    # Find publish_bootstrap_service function
    in_function = False
    found_browse_verification = False
    found_no_terminate_override = False
    
    for i, line in enumerate(lines):
        if 'publish_bootstrap_service()' in line:
            in_function = True
        
        if in_function:
            # Look for browse_verification assignment
            if 'browse_verification="$(' in line and 'run_avahi_query server-select' in line:
                found_browse_verification = True
                # Check if SUGARKUBE_MDNS_NO_TERMINATE=0 is in the same line
                if 'SUGARKUBE_MDNS_NO_TERMINATE=0' in line:
                    found_no_terminate_override = True
                    break
        
        # Exit function scope when we hit the next function
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'publish_bootstrap_service' not in line:
            break
    
    assert found_browse_verification, \
        "publish_bootstrap_service should have browse_verification when SAVE_DEBUG_LOGS=1"
    assert found_no_terminate_override, \
        "publish_bootstrap_service browse_verification should set SUGARKUBE_MDNS_NO_TERMINATE=0 to avoid infinite loop"


def test_discover_via_nss_and_api_sets_no_terminate() -> None:
    """Test that discover_via_nss_and_api sets SUGARKUBE_MDNS_NO_TERMINATE=1 for initial discovery."""
    
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()
    
    # Find discover_via_nss_and_api function
    in_function = False
    found_no_terminate_export = False
    
    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True
        
        if in_function:
            # Look for export SUGARKUBE_MDNS_NO_TERMINATE=1
            if 'export SUGARKUBE_MDNS_NO_TERMINATE=1' in line:
                found_no_terminate_export = True
                break
        
        # Exit function scope when we hit the next function
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break
    
    assert found_no_terminate_export, \
        "discover_via_nss_and_api should export SUGARKUBE_MDNS_NO_TERMINATE=1 for initial discovery"
