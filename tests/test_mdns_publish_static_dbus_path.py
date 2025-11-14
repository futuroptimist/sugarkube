"""Test for mdns_publish_static.sh D-Bus path fix.

This test verifies that the check_service_via_dbus function in mdns_publish_static.sh
correctly uses /org/freedesktop/Avahi/Server as the D-Bus object path when calling
ResolveService.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MDNS_PUBLISH_STATIC_SCRIPT = SCRIPTS_DIR / "mdns_publish_static.sh"


def test_check_service_via_dbus_uses_correct_path():
    """Test that check_service_via_dbus uses correct D-Bus object path.
    
    This test verifies that when mdns_publish_static.sh calls ResolveService,
    it uses '/org/freedesktop/Avahi/Server' instead of '/' as the object path.
    """
    # Read the script content
    script_content = MDNS_PUBLISH_STATIC_SCRIPT.read_text()
    
    # Find the check_service_via_dbus function
    assert "check_service_via_dbus" in script_content, (
        "check_service_via_dbus function not found in mdns_publish_static.sh"
    )
    
    # Check that gdbus call uses correct path
    assert '"--object-path",\n                "/org/freedesktop/Avahi/Server",' in script_content, (
        "gdbus ResolveService call should use /org/freedesktop/Avahi/Server object path"
    )
    
    # Check that busctl call uses correct path
    # busctl doesn't use --object-path flag, path is a positional argument
    assert '"/org/freedesktop/Avahi/Server",\n                "org.freedesktop.Avahi.Server",' in script_content, (
        "busctl ResolveService call should use /org/freedesktop/Avahi/Server object path"
    )
    
    # Verify the old incorrect path is NOT present in the gdbus command
    # Look for the specific pattern where gdbus had "/" before
    assert not ('"--object-path",\n                "/",' in script_content and 
                '"org.freedesktop.Avahi.Server.ResolveService"' in script_content), (
        "Found old incorrect '/' path in gdbus ResolveService call"
    )


def test_mdns_publish_static_python_section_correct_path():
    """Test that the Python section in mdns_publish_static.sh has correct paths.
    
    Verifies both gdbus and busctl commands in the embedded Python code
    use the correct object path.
    """
    script_content = MDNS_PUBLISH_STATIC_SCRIPT.read_text()
    
    # Find the Python section
    assert 'def run_command' in script_content or 'import subprocess' in script_content, (
        "Python section not found in mdns_publish_static.sh"
    )
    
    # Check gdbus in Python section
    gdbus_section_ok = False
    busctl_section_ok = False
    
    lines = script_content.split('\n')
    for i, line in enumerate(lines):
        # Look for gdbus command building
        if '"--object-path",' in line:
            # Check next line for path
            if i + 1 < len(lines) and '"/org/freedesktop/Avahi/Server",' in lines[i + 1]:
                gdbus_section_ok = True
        
        # Look for busctl command with Server interface
        if '"org.freedesktop.Avahi",' in line:
            # Check next few lines for path
            for j in range(1, 4):
                if i + j < len(lines):
                    if '"/org/freedesktop/Avahi/Server",' in lines[i + j]:
                        busctl_section_ok = True
                        break
    
    assert gdbus_section_ok, (
        "gdbus command in Python section should use /org/freedesktop/Avahi/Server"
    )
    assert busctl_section_ok, (
        "busctl command in Python section should use /org/freedesktop/Avahi/Server"
    )
