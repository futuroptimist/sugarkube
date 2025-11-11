from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_script_unsets_environment_and_writes_snippet(tmp_path) -> None:
    cache_home = tmp_path / "cache"
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(cache_home)
    command = """
    set -euo pipefail
    export SUGARKUBE_SERVERS=3
    export SAVE_DEBUG_LOGS=1
    export SUGARKUBE_API_REGADDR=demo
    . scripts/unset_doc_env_vars.sh
    python3 - <<'PY'
import os
print(os.environ.get('SUGARKUBE_SERVERS'))
print(os.environ.get('SAVE_DEBUG_LOGS'))
print(os.environ.get('SUGARKUBE_API_REGADDR'))
PY
    """
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines[-3:] == ["None", "None", "None"], lines
    snippet_path = cache_home / "sugarkube" / "wipe-env.sh"
    assert snippet_path.exists()
    snippet_text = snippet_path.read_text(encoding="utf-8")
    assert "unset SUGARKUBE_SERVERS" in snippet_text
    assert "unset SAVE_DEBUG_LOGS" in snippet_text
    assert "unset SUGARKUBE_API_REGADDR" in snippet_text
