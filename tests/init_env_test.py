import subprocess
from pathlib import Path


def test_succeeds_when_optional_repos_missing(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script_src = repo_root / "scripts" / "cloud-init" / "init-env.sh"
    script = tmp_path / "init-env.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
