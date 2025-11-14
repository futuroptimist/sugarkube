"""Tests for API readiness check with 401 responses."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_apiready.sh"


def test_api_readiness_rejects_401_by_default(tmp_path: Path) -> None:
    """By default, 401 responses should be treated as failure."""
    
    # Create a mock server script that returns 401
    mock_server = tmp_path / "mock_curl"
    mock_server.write_text(
        "#!/usr/bin/env bash\n"
        "echo '401'\n"
        "exit 0\n",
        encoding="utf-8"
    )
    mock_server.chmod(0o755)
    
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SERVER_HOST": "test.local",
        "SERVER_PORT": "6443",
        "TIMEOUT": "1",
        "POLL_INTERVAL": "0.5",
    }
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    
    # Should fail with timeout
    assert result.returncode != 0
    assert "outcome=timeout" in result.stderr or "reason=http_error" in result.stderr


def test_api_readiness_accepts_401_when_enabled(tmp_path: Path) -> None:
    """When ALLOW_HTTP_401=1, 401 responses should be treated as 'alive'."""
    
    # Create a mock server script that returns 401
    mock_server = tmp_path / "mock_curl"
    mock_server.write_text(
        "#!/usr/bin/env bash\n"
        "# Mock curl that returns 401\n"
        "echo '401'\n"
        "exit 0\n",
        encoding="utf-8"
    )
    mock_server.chmod(0o755)
    
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SERVER_HOST": "test.local",
        "SERVER_PORT": "6443",
        "TIMEOUT": "1",
        "POLL_INTERVAL": "0.5",
        "ALLOW_HTTP_401": "1",
    }
    
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    
    # Should succeed with 'alive' outcome
    assert result.returncode == 0
    assert "outcome=alive" in result.stderr
    assert "status=401" in result.stderr
    assert "mode=alive" in result.stderr


def test_wait_for_remote_api_ready_includes_allow_401(tmp_path: Path) -> None:
    """wait_for_remote_api_ready should pass ALLOW_HTTP_401=1 to check_apiready.sh."""
    
    # Create a stub k3s-discover.sh test that verifies the environment variable is set
    test_script = tmp_path / "test_wait_for_remote.sh"
    test_script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../scripts/k3s-discover.sh"

# Mock the API_READY_CHECK_BIN
API_READY_CHECK_BIN="${BATS_TEST_TMPDIR}/mock_check_apiready.sh"
cat > "${API_READY_CHECK_BIN}" <<'EOF'
#!/usr/bin/env bash
if [ "${ALLOW_HTTP_401:-0}" = "1" ]; then
    echo "ALLOW_HTTP_401 is set" >&2
    exit 0
else
    echo "ALLOW_HTTP_401 is not set" >&2
    exit 1
fi
EOF
chmod +x "${API_READY_CHECK_BIN}"

# Test the function
if wait_for_remote_api_ready "sugarkube0.local"; then
    echo "SUCCESS"
else
    echo "FAILURE"
fi
""",
        encoding="utf-8"
    )
    test_script.chmod(0o755)
    
    env = {
        **os.environ,
        "BATS_TEST_TMPDIR": str(tmp_path),
        "ALLOW_NON_ROOT": "1",
    }
    
    result = subprocess.run(
        ["bash", str(test_script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should see that ALLOW_HTTP_401 was set
    assert "ALLOW_HTTP_401 is set" in result.stderr
    assert "SUCCESS" in result.stdout or result.returncode == 0
