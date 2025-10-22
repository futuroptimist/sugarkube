from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _extract_recipe(name: str) -> tuple[str, list[str]]:
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
                break
            break
        if line.startswith(name):
            header = line
            capture = True
    if header is None:
        raise AssertionError(f"Recipe {name} not found")
    return header, body


def test_wipe_recipe_shells_out_to_script() -> None:
    header, body = _extract_recipe("wipe:")
    assert header == "wipe:"
    assert body == [
        "    @sudo --preserve-env=SUGARKUBE_CLUSTER,SUGARKUBE_ENV,DRY_RUN,ALLOW_NON_ROOT bash scripts/wipe_node.sh",
    ]
    command = body[0]
    assert "SUGARKUBE_CLUSTER" in command
    assert "SUGARKUBE_ENV" in command
    assert "scripts/wipe_node.sh" in command
