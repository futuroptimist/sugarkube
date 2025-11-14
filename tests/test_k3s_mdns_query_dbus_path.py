"""Test for k3s_mdns_query.py D-Bus path fix.

This test verifies that k3s_mdns_query.py correctly uses /org/freedesktop/Avahi/Server
as the D-Bus object path when calling ServiceBrowserNew.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
K3S_MDNS_QUERY_SCRIPT = SCRIPTS_DIR / "k3s_mdns_query.py"


def test_k3s_mdns_query_gdbus_uses_correct_path():
    """Test that k3s_mdns_query.py gdbus call uses correct object path.
    
    Verifies that ServiceBrowserNew is called with /org/freedesktop/Avahi/Server
    instead of /.
    """
    script_content = K3S_MDNS_QUERY_SCRIPT.read_text()
    
    # Find the gdbus command construction
    assert '"--object-path",' in script_content, (
        "gdbus command not found in k3s_mdns_query.py"
    )
    
    # Check for correct path in gdbus command
    assert '"/org/freedesktop/Avahi/Server",' in script_content, (
        "gdbus command should use /org/freedesktop/Avahi/Server object path"
    )
    
    # Verify it's in the right context (near ServiceBrowserNew)
    lines = script_content.split('\n')
    found_correct_pattern = False
    for i, line in enumerate(lines):
        if '"--object-path",' in line:
            # Check surrounding lines for context
            context = '\n'.join(lines[max(0, i-5):min(len(lines), i+10)])
            if 'ServiceBrowserNew' in context and '"/org/freedesktop/Avahi/Server",' in context:
                found_correct_pattern = True
                # Make sure we don't have the old "/" path
                assert '"/",' not in '\n'.join(lines[i:i+3]), (
                    "Found incorrect '/' path near --object-path"
                )
    
    assert found_correct_pattern, (
        "Could not find correct /org/freedesktop/Avahi/Server path near ServiceBrowserNew"
    )


def test_k3s_mdns_query_busctl_uses_correct_path():
    """Test that k3s_mdns_query.py busctl call uses correct object path.
    
    Verifies that ServiceBrowserNew via busctl is called with
    /org/freedesktop/Avahi/Server instead of /.
    """
    script_content = K3S_MDNS_QUERY_SCRIPT.read_text()
    
    # Find the busctl command construction
    lines = script_content.split('\n')
    found_busctl_correct = False
    
    for i, line in enumerate(lines):
        # Look for busctl command building
        if '"busctl",' in line or 'busctl' in line:
            # Look at surrounding lines
            context = '\n'.join(lines[max(0, i-3):min(len(lines), i+15)])
            if 'ServiceBrowserNew' in context:
                # busctl path is positional, should be after org.freedesktop.Avahi
                if ('"/org/freedesktop/Avahi/Server",' in context or
                    '"/org/freedesktop/Avahi/Server"' in context):
                    found_busctl_correct = True
                    # Make sure the OLD path isn't there
                    # Check lines after "org.freedesktop.Avahi"
                    for j in range(i, min(len(lines), i + 12)):
                        if '"org.freedesktop.Avahi",' in lines[j]:
                            # Next line should be the path
                            if j + 1 < len(lines):
                                next_line = lines[j + 1].strip()
                                assert next_line != '"/",' and not next_line.startswith('"/"'), (
                                    f"Found incorrect '/' path in busctl command at line {j+1}"
                                )
    
    assert found_busctl_correct, (
        "Could not find correct /org/freedesktop/Avahi/Server path in busctl ServiceBrowserNew command"
    )


def test_k3s_mdns_query_no_root_path_in_dbus_calls():
    """Test that k3s_mdns_query.py doesn't use '/' for Avahi Server methods.
    
    This is a negative test to ensure the old incorrect path is not present.
    """
    script_content = K3S_MDNS_QUERY_SCRIPT.read_text()
    lines = script_content.split('\n')
    
    # Look for patterns that would indicate using "/" for Server methods
    for i, line in enumerate(lines):
        if 'ServiceBrowserNew' in line or '"ServiceBrowserNew"' in line:
            # Check nearby lines for "/" as object path
            context = '\n'.join(lines[max(0, i-10):min(len(lines), i+5)])
            # If we find "/" as object-path AND it's near ServiceBrowserNew, that's wrong
            if '--object-path' in context:
                # Make sure "/" isn't used as the path
                assert not ('--object-path", "/"' in context or 
                           '--object-path",\n                "/"' in context), (
                    f"Found incorrect '/' object path near ServiceBrowserNew at line {i}"
                )
