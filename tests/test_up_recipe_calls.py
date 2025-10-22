from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _extract_recipe(target: str) -> tuple[str, list[str]]:
    lines = JUSTFILE.read_text(encoding="utf-8").splitlines()
    header = None
    body: list[str] = []
    capture = False
    for line in lines:
        if capture:
            if line.startswith("    "):
                body.append(line)
                continue
            if line.strip() == "" or line.startswith("#"):
                continue
            break
        if line.startswith(target):
            header = line
            capture = True
    if header is None:
        raise AssertionError(f"{target} recipe missing from justfile")
    return header, body


def test_up_recipe_runs_cgroup_check_and_discovery():
    header, body = _extract_recipe("up env='dev':")
    assert header == "up env='dev': prereqs"
    commands = [line.strip() for line in body if not line.lstrip().startswith("#")]
    assert any("check_memory_cgroup.sh" in line for line in commands)
    assert any(line.startswith("sudo -E bash scripts/k3s-discover.sh") for line in commands)
