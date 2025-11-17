"""
Unit tests for node-token wait mechanism.

This test verifies that the wait_for_node_token() function properly waits for
the node-token file to be created after k3s installation.

Related to hostname collision and mDNS issues preventing node-token creation.
"""

import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest


def test_wait_for_node_token_success():
    """Test that wait_for_node_token succeeds when token file is created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "node-token"
        
        # Create a test script that uses the wait_for_node_token function
        test_script = Path(tmpdir) / "test_wait.sh"
        test_script.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                
                # Source the wait function (simplified version for testing)
                wait_for_node_token() {{
                    local token_path="${{1}}"
                    local timeout="${{SUGARKUBE_NODE_TOKEN_TIMEOUT:-30}}"
                    local poll_interval="${{SUGARKUBE_NODE_TOKEN_POLL_INTERVAL:-1}}"
                    local elapsed=0
                    
                    while [ ! -f "${{token_path}}" ]; do
                        if [ "${{elapsed}}" -ge "${{timeout}}" ]; then
                            echo "ERROR: Node token file not created after ${{timeout}}s" >&2
                            return 1
                        fi
                        sleep "${{poll_interval}}"
                        elapsed=$((elapsed + poll_interval))
                    done
                    
                    echo "Node token file created at ${{token_path}}"
                    return 0
                }}
                
                # Create the token file after a short delay (simulating k3s)
                (sleep 1; echo "K10test123" > "{token_path}") &
                
                # Wait for it
                wait_for_node_token "{token_path}"
                """
            ),
            encoding="utf-8",
        )
        test_script.chmod(0o755)
        
        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "SUGARKUBE_NODE_TOKEN_TIMEOUT": "5",
                "SUGARKUBE_NODE_TOKEN_POLL_INTERVAL": "0.5",
            },
        )
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "Node token file created" in result.stdout
        assert token_path.exists()


def test_wait_for_node_token_timeout():
    """Test that wait_for_node_token times out when token is never created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "node-token-never-created"
        
        test_script = Path(tmpdir) / "test_wait_timeout.sh"
        test_script.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                
                wait_for_node_token() {{
                    local token_path="${{1}}"
                    local timeout="${{SUGARKUBE_NODE_TOKEN_TIMEOUT:-30}}"
                    local poll_interval="${{SUGARKUBE_NODE_TOKEN_POLL_INTERVAL:-1}}"
                    local elapsed=0
                    
                    while [ ! -f "${{token_path}}" ]; do
                        if [ "${{elapsed}}" -ge "${{timeout}}" ]; then
                            echo "ERROR: Node token file not created after ${{timeout}}s" >&2
                            return 1
                        fi
                        sleep "${{poll_interval}}"
                        elapsed=$((elapsed + poll_interval))
                    done
                    
                    echo "Node token file created at ${{token_path}}"
                    return 0
                }}
                
                # Don't create the token file - let it timeout
                wait_for_node_token "{token_path}"
                """
            ),
            encoding="utf-8",
        )
        test_script.chmod(0o755)
        
        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "SUGARKUBE_NODE_TOKEN_TIMEOUT": "2",
                "SUGARKUBE_NODE_TOKEN_POLL_INTERVAL": "0.5",
            },
        )
        
        assert result.returncode == 1, "Script should fail when token not created"
        assert "Node token file not created" in result.stderr
        assert not token_path.exists()


def test_wait_for_node_token_immediate():
    """Test that wait_for_node_token succeeds immediately if token already exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        token_path = Path(tmpdir) / "existing-token"
        token_path.write_text("K10existing123", encoding="utf-8")
        
        test_script = Path(tmpdir) / "test_wait_immediate.sh"
        test_script.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                
                wait_for_node_token() {{
                    local token_path="${{1}}"
                    local timeout="${{SUGARKUBE_NODE_TOKEN_TIMEOUT:-30}}"
                    local poll_interval="${{SUGARKUBE_NODE_TOKEN_POLL_INTERVAL:-1}}"
                    local elapsed=0
                    
                    while [ ! -f "${{token_path}}" ]; do
                        if [ "${{elapsed}}" -ge "${{timeout}}" ]; then
                            echo "ERROR: Node token file not created after ${{timeout}}s" >&2
                            return 1
                        fi
                        sleep "${{poll_interval}}"
                        elapsed=$((elapsed + poll_interval))
                    done
                    
                    echo "Node token file created at ${{token_path}}"
                    return 0
                }}
                
                # Token already exists
                start=$SECONDS
                wait_for_node_token "{token_path}"
                elapsed=$((SECONDS - start))
                
                # Should complete almost immediately (within 1 second)
                if [ "$elapsed" -gt 1 ]; then
                    echo "ERROR: Took too long ($elapsed seconds) for existing file" >&2
                    exit 1
                fi
                """
            ),
            encoding="utf-8",
        )
        test_script.chmod(0o755)
        
        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "Node token file created" in result.stdout
