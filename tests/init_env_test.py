import subprocess
from pathlib import Path


def _run_init_env(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    script_src = repo_root / "scripts" / "cloud-init" / "init-env.sh"
    script = tmp_path / "init-env.sh"
    script.write_text(script_src.read_text())
    script.chmod(0o755)
    return subprocess.run(
        ["/bin/bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_succeeds_when_optional_repos_missing(tmp_path):
    result = _run_init_env(tmp_path)
    assert result.returncode == 0, result.stderr


def test_copies_env_example_and_sets_permissions(tmp_path):
    service = tmp_path / "svc"
    service.mkdir()
    example = service / ".env.example"
    example.write_text("FOO=1")
    result = _run_init_env(tmp_path)
    assert result.returncode == 0, result.stderr
    env_file = service / ".env"
    assert env_file.read_text() == "FOO=1"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"


def test_preserves_existing_env(tmp_path):
    service = tmp_path / "svc"
    service.mkdir()
    (service / ".env.example").write_text("FOO=1")
    env_file = service / ".env"
    env_file.write_text("EXISTING=1")
    env_file.chmod(0o644)
    result = _run_init_env(tmp_path)
    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == "EXISTING=1"


def test_creates_token_place_env_when_dir_exists(tmp_path):
    (tmp_path / "token.place").mkdir()
    result = _run_init_env(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "token.place" / ".env").exists()
