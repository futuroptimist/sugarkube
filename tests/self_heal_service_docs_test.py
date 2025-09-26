from pathlib import Path


def test_self_heal_service_readme_exists_and_highlights_paths() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    readme = repo_root / "scripts" / "systemd" / "self-heal-service" / "README.md"
    assert readme.exists(), "Expected self-heal service README to be present"

    contents = readme.read_text()
    assert "sugarkube-self-heal@.service" in contents
    assert "self_heal_service.py" in contents
    assert "/boot/first-boot-report/self-heal/" in contents
    assert "/var/log/sugarkube/self-heal/" in contents
